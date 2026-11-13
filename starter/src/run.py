"""End-to-end Day 06 Data Ingestion & Benchmark Pipeline."""
from __future__ import annotations

import csv
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_pdf
from .models import Chunk, DocumentPage
from .store import PgVectorStore


def _repo_root() -> Path:
    # starter/src/run.py -> starter -> repo_root
    return Path(__file__).resolve().parents[2]


def _length_stats(chunks: list[Chunk]) -> dict[str, Any]:
    lengths = sorted(len(c.text) for c in chunks)
    n = len(lengths)
    if n == 0:
        return {"count": 0}
    p95_idx = min(n - 1, int(0.95 * (n - 1)))
    total_chars = sum(lengths)
    return {
        "chunk_count": n,
        "min_chars": lengths[0],
        "mean_chars": round(total_chars / n, 2),
        "median_chars": round(statistics.median(lengths), 2),
        "p95_chars": lengths[p95_idx],
        "max_chars": lengths[-1],
        "total_chars": total_chars,
        "approx_tokens": round(total_chars / 4),
    }


def _write_json(paths: list[Path], payload: Any) -> None:
    content = json.dumps(payload, indent=2, ensure_ascii=False)
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _write_summary_csv(paths: list[Path], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def main() -> None:
    root = _repo_root()
    starter_dir = root / "starter"
    load_dotenv(starter_dir / ".env")

    database_url = os.getenv("DATABASE_URL")
    model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set in starter/.env")

    manifest_path = root / "data" / "manifest.json"
    benchmark_path = root / "benchmark" / "questions.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))

    valid_page_count = int(manifest.get("total_valid_content_pages", 0))
    if valid_page_count < 30:
        raise RuntimeError(f"Corpus must have >= 30 valid content pages, got {valid_page_count}")

    # 1. Load and normalize valid pages
    ingestion_log: list[dict[str, Any]] = []
    pages: list[DocumentPage] = []
    for doc in manifest["documents"]:
        pdf_path = root / doc["source_path"]
        doc_pages = load_pdf(
            path=pdf_path,
            document_id=doc["source_id"],
            source=doc["source_path"],
            valid_pages=doc["valid_page_ids"],
            base_metadata=doc["metadata"],
            ingestion_log=ingestion_log,
        )
        pages.extend(doc_pages)

    if len(pages) < 30:
        raise RuntimeError(f"Loaded only {len(pages)} valid pages (< 30).")

    # 2. Initialize real local embedder & pgvector store
    embedder = MyEmbedder(model_name=model_name)
    store = PgVectorStore(database_url=database_url, dimensions=embedder.dimensions)
    store.create_schema()

    # 3. Configure and ingest strategies A, B, C
    strategy_defs = [
        {
            "strategy": "A",
            "description": "Fixed-size chunking (size=500, overlap=50), no metadata filtering",
            "chunker": lambda p: fixed_size(p, size=500, overlap=50),
            "use_filter": False,
        },
        {
            "strategy": "B",
            "description": "Structure/paragraph-aware chunking (max_size=900), no metadata filtering",
            "chunker": lambda p: by_paragraph(p, max_size=900),
            "use_filter": False,
        },
        {
            "strategy": "C",
            "description": "Same chunking as B (max_size=900) + SQL metadata filter when query provides filter",
            "chunker": lambda p: by_paragraph(p, max_size=900),
            "use_filter": True,
        },
    ]

    strategy_stats: dict[str, Any] = {
        "model_name": embedder.model_name,
        "dimensions": embedder.dimensions,
        "vector_store": "PostgreSQL 16 + pgvector 0.8.7 (exact cosine distance <=>)",
        "cost_usd": 0.0,
        "valid_pages_ingested": len(pages),
        "strategies": {},
    }

    for sdef in strategy_defs:
        sname = sdef["strategy"]
        t0 = time.perf_counter()
        chunks: list[Chunk] = []
        for page in pages:
            chunks.extend(sdef["chunker"](page))

        vectors = embedder.embed_documents([c.text for c in chunks])
        embed_elapsed = time.perf_counter() - t0

        t1 = time.perf_counter()
        upsert_info = store.upsert(sname, chunks, vectors)
        db_elapsed = time.perf_counter() - t1

        count_first = store.count_chunks(sname)
        # Re-ingest same version to verify idempotency (no duplicates)
        reingest_info = store.upsert(sname, chunks, vectors)
        count_second = store.count_chunks(sname)
        if count_first != len(chunks) or count_second != count_first:
            raise RuntimeError(
                f"Idempotency check failed for {sname}: expected {len(chunks)}, "
                f"got first={count_first}, second={count_second}"
            )

        stats = _length_stats(chunks)
        stats.update(
            {
                "description": sdef["description"],
                "use_filter": sdef["use_filter"],
                "embed_seconds": round(embed_elapsed, 3),
                "upsert_seconds": round(db_elapsed, 3),
                "total_ingest_seconds": round(embed_elapsed + db_elapsed, 3),
                "first_upsert": upsert_info,
                "reingest_upsert": reingest_info,
                "db_count_after_first": count_first,
                "db_count_after_reingest": count_second,
                "idempotent_no_duplicates": count_first == count_second == len(chunks),
            }
        )
        strategy_stats["strategies"][sname] = stats

    # 4. Run benchmark queries across A, B, C
    questions = benchmark["questions"]
    query_vectors = {
        q["id"]: embedder.embed_query(q["question"]) for q in questions
    }

    all_traces: list[dict[str, Any]] = []
    for sdef in strategy_defs:
        sname = sdef["strategy"]
        use_filter = sdef["use_filter"]
        q_t0 = time.perf_counter()

        for q in questions:
            applied_filter = q.get("filter") if (use_filter and q.get("filter")) else None
            hits = store.search(
                strategy=sname,
                query_vector=query_vectors[q["id"]],
                top_k=3,
                filters=applied_filter,
            )
            trace = evaluate_query(q, hits, applied_filter=applied_filter)
            trace["strategy"] = sname
            all_traces.append(trace)

        strategy_stats["strategies"][sname]["query_seconds_20q"] = round(
            time.perf_counter() - q_t0, 3
        )

    summary = summarize(all_traces)
    summary["model_name"] = embedder.model_name
    summary["dimensions"] = embedder.dimensions
    summary["cost_usd"] = 0.0

    # 5. Persist artifacts to both results/ and starter/results/
    out_dirs = [root / "results", starter_dir / "results"]
    _write_json([d / "ingestion_log.json" for d in out_dirs], ingestion_log)
    _write_json([d / "strategy_stats.json" for d in out_dirs], strategy_stats)
    _write_json([d / "traces_all.json" for d in out_dirs], all_traces)
    _write_json([d / "metrics_summary.json" for d in out_dirs], summary)
    _write_summary_csv(
        [d / "metrics_summary.csv" for d in out_dirs], summary["by_strategy_split"]
    )

    print(f"Pipeline completed with model={embedder.model_name} (dim={embedder.dimensions})")
    for sname, st in strategy_stats["strategies"].items():
        print(
            f"  Strategy {sname}: chunks={st['chunk_count']} mean_len={st['mean_chars']} "
            f"ingest={st['total_ingest_seconds']}s idempotent={st['idempotent_no_duplicates']}"
        )
    print("\nMetrics Summary:")
    for row in summary["by_strategy_split"]:
        print(
            f"  {row['strategy']} [{row['split']}]: Hit@1={row['hit1_fraction']} ({row['hit1_rate']:.1%}) | "
            f"Hit@3={row['hit3_fraction']} ({row['hit3_rate']:.1%}) | "
            f"Filter={row['filter_compliant_fraction']}"
        )


if __name__ == "__main__":
    main()
