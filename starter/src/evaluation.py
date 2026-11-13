"""Evaluate retrieved top-k chunks and preserve full per-query traces."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _matches_filter(hit: dict[str, Any], required_filter: dict[str, Any]) -> bool:
    for key, expected in required_filter.items():
        actual = hit.get(key)
        if actual is None:
            actual = (hit.get("metadata") or {}).get(key)
        if actual != expected:
            return False
    return True


def evaluate_query(
    question: dict[str, Any],
    hits: list[dict[str, Any]],
    applied_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate Hit@1, Evidence Hit@3, and filter compliance for a single query."""
    gold_source = question["gold_source_id"]
    valid_pages = {int(question["gold_page"])} | {
        int(p) for p in question.get("alt_gold_pages", [])
    }

    evidence_candidates = [_norm_ws(question["evidence_quote"])]
    for alt in question.get("alt_evidence_quotes", []):
        evidence_candidates.append(_norm_ws(alt))
    evidence_candidates = [e for e in evidence_candidates if e]

    required_filter = question.get("filter") or None
    evaluated_hits: list[dict[str, Any]] = []
    same_page_texts: list[str] = []

    for hit in hits:
        norm_hit_text = _norm_ws(hit.get("text", ""))
        source_match = hit.get("document_id") == gold_source
        page_match = int(hit.get("page", -1)) in valid_pages
        evidence_match = any(ev in norm_hit_text for ev in evidence_candidates)
        is_hit = source_match and page_match and evidence_match
        if source_match and page_match:
            same_page_texts.append(norm_hit_text)

        filter_ok: bool | None = None
        if required_filter:
            filter_ok = _matches_filter(hit, required_filter)

        evaluated_hits.append(
            {
                "rank": hit["rank"],
                "chunk_id": hit["chunk_id"],
                "document_id": hit["document_id"],
                "source": hit["source"],
                "page": hit["page"],
                "category": hit.get("category"),
                "year": hit.get("year"),
                "section": hit.get("section"),
                "score": hit.get("score"),
                "source_match": source_match,
                "page_match": page_match,
                "evidence_match": evidence_match,
                "is_hit": is_hit,
                "filter_compliant": filter_ok,
                "text": hit["text"],
            }
        )

    hit_at_1 = bool(evaluated_hits and evaluated_hits[0]["is_hit"])
    hit_at_3 = any(h["is_hit"] for h in evaluated_hits[:3])

    # Diagnostic flag: gold page appeared in top-3, but evidence was split across chunks
    evidence_split_across_chunks = False
    if not hit_at_3 and same_page_texts:
        combined = " ".join(same_page_texts)
        if any(ev in combined for ev in evidence_candidates):
            evidence_split_across_chunks = True

    all_top3_filter_compliant: bool | None = None
    if required_filter:
        all_top3_filter_compliant = bool(evaluated_hits) and all(
            bool(h["filter_compliant"]) for h in evaluated_hits[:3]
        )

    return {
        "question_id": question["id"],
        "split": question["split"],
        "type": question.get("type", "unknown"),
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "gold_source_id": gold_source,
        "gold_page": question["gold_page"],
        "evidence_quote": question["evidence_quote"],
        "question_filter": required_filter,
        "applied_filter": applied_filter,
        "hit_at_1": hit_at_1,
        "hit_at_3": hit_at_3,
        "evidence_split_across_chunks": evidence_split_across_chunks,
        "all_top3_filter_compliant": all_top3_filter_compliant,
        "top_hits": evaluated_hits[:3],
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1, Evidence Hit@3, and filter compliance by strategy and split."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        grouped[(t["strategy"], t["split"])].append(t)

    summary_rows: list[dict[str, Any]] = []
    for (strategy, split), items in sorted(grouped.items()):
        total = len(items)
        h1 = sum(1 for x in items if x["hit_at_1"])
        h3 = sum(1 for x in items if x["hit_at_3"])
        filtered_items = [x for x in items if x["question_filter"]]
        filter_total = len(filtered_items)
        filter_ok = sum(1 for x in filtered_items if x["all_top3_filter_compliant"])

        summary_rows.append(
            {
                "strategy": strategy,
                "split": split,
                "n_total": total,
                "hit1_count": h1,
                "hit1_fraction": f"{h1}/{total}",
                "hit1_rate": round(h1 / total, 4) if total else 0.0,
                "hit3_count": h3,
                "hit3_fraction": f"{h3}/{total}",
                "hit3_rate": round(h3 / total, 4) if total else 0.0,
                "filter_questions": filter_total,
                "filter_compliant_count": filter_ok if filter_total else None,
                "filter_compliant_fraction": (
                    f"{filter_ok}/{filter_total}" if filter_total else "N/A"
                ),
            }
        )

    return {"by_strategy_split": summary_rows}
