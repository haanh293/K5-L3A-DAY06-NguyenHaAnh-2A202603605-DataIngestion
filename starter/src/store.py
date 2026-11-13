"""PostgreSQL + pgvector persistent storage, idempotent upsert, and filtered cosine search."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import Chunk

ALLOWED_FILTER_COLUMNS = {"category", "year", "document_id", "section"}


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL must be configured.")
        if dimensions <= 0:
            raise ValueError(f"dimensions must be > 0, got {dimensions}")
        self.database_url = database_url
        self.dimensions = dimensions

    def create_schema(self) -> None:
        """Create table and indexes with vector column and source/page/filter metadata."""
        ddl = f"""
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE IF NOT EXISTS rag_chunks (
            strategy TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            source TEXT NOT NULL,
            page INTEGER NOT NULL,
            category TEXT NOT NULL,
            year INTEGER NOT NULL,
            section TEXT NOT NULL,
            text TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding vector({self.dimensions}) NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (strategy, chunk_id)
        );
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_strategy_cat_year
            ON rag_chunks (strategy, category, year);
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_strategy_doc
            ON rag_chunks (strategy, document_id);
        """
        with psycopg.connect(self.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()

    def upsert(
        self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> dict[str, int]:
        """Idempotently upsert chunks and remove obsolete chunks for re-ingested documents."""
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks ({len(chunks)}) and vectors ({len(vectors)}) length mismatch")
        for idx, vec in enumerate(vectors):
            if len(vec) != self.dimensions:
                raise ValueError(
                    f"Vector at index {idx} has dimension {len(vec)}, expected {self.dimensions}"
                )

        doc_chunk_ids: dict[str, list[str]] = defaultdict(list)
        for c in chunks:
            doc_chunk_ids[c.document_id].append(c.chunk_id)

        deleted_obsolete = 0
        upserted = 0

        with psycopg.connect(self.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Remove obsolete chunks if a document changed and produced fewer/different chunks
                for doc_id, valid_ids in doc_chunk_ids.items():
                    cur.execute(
                        """
                        DELETE FROM rag_chunks
                        WHERE strategy = %s
                          AND document_id = %s
                          AND NOT (chunk_id = ANY(%s))
                        """,
                        (strategy, doc_id, valid_ids),
                    )
                    deleted_obsolete += cur.rowcount or 0

                sql = """
                INSERT INTO rag_chunks (
                    strategy, chunk_id, document_id, source, page,
                    category, year, section, text, metadata, embedding, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id,
                    source = EXCLUDED.source,
                    page = EXCLUDED.page,
                    category = EXCLUDED.category,
                    year = EXCLUDED.year,
                    section = EXCLUDED.section,
                    text = EXCLUDED.text,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding,
                    updated_at = now();
                """
                for chunk, vec in zip(chunks, vectors):
                    category = str(chunk.metadata.get("category", "unknown"))
                    year = int(chunk.metadata.get("year", 0))
                    section = str(chunk.metadata.get("section", "general"))
                    cur.execute(
                        sql,
                        (
                            strategy,
                            chunk.chunk_id,
                            chunk.document_id,
                            chunk.source,
                            chunk.page,
                            category,
                            year,
                            section,
                            chunk.text,
                            Jsonb(chunk.metadata),
                            _vector_literal(vec),
                        ),
                    )
                    upserted += 1
            conn.commit()

        return {"upserted": upserted, "deleted_obsolete": deleted_obsolete}

    def count_chunks(self, strategy: str) -> int:
        with psycopg.connect(self.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM rag_chunks WHERE strategy = %s",
                    (strategy,),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter permitted metadata in SQL, rank by exact cosine distance, and return top-k."""
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"Query vector dimension {len(query_vector)} != expected {self.dimensions}"
            )

        q_lit = _vector_literal(query_vector)
        where_clauses = ["strategy = %s"]
        where_params: list[Any] = [strategy]

        if filters:
            for key, val in filters.items():
                if key not in ALLOWED_FILTER_COLUMNS:
                    raise ValueError(f"Unsupported filter column: {key}")
                where_clauses.append(f"{key} = %s")
                where_params.append(val)

        where_sql = " AND ".join(where_clauses)
        query_sql = f"""
        SELECT
            chunk_id,
            document_id,
            source,
            page,
            category,
            year,
            section,
            text,
            metadata,
            1.0 - (embedding <=> %s::vector) AS cosine_similarity
        FROM rag_chunks
        WHERE {where_sql}
        ORDER BY embedding <=> %s::vector ASC, chunk_id ASC
        LIMIT %s
        """
        params: list[Any] = [q_lit, *where_params, q_lit, top_k]

        results: list[dict[str, Any]] = []
        with psycopg.connect(self.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(query_sql, params)
                for rank, row in enumerate(cur.fetchall(), start=1):
                    meta = row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}")
                    results.append(
                        {
                            "rank": rank,
                            "chunk_id": row[0],
                            "document_id": row[1],
                            "source": row[2],
                            "page": int(row[3]),
                            "category": row[4],
                            "year": int(row[5]),
                            "section": row[6],
                            "text": row[7],
                            "metadata": meta,
                            "score": round(float(row[9]), 6),
                        }
                    )
        return results
