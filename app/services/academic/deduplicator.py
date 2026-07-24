"""Deduplication for paper lists (Section 4.7)."""

from __future__ import annotations

import re
from typing import Any


def _title_key(title: str) -> str:
    """Normalise a title for fuzzy-comparison."""
    t = title.lower().strip()
    t = re.sub(r"[^a-z0-9一-鿿]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def deduplicate(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate a list of normalised paper dicts.

    Priority order (Section 4.7):
    1. Same DOI
    2. Same source ID
    3. Same normalised title + year
    4. Highly similar title + first‑author match
    """
    if len(papers) <= 1:
        return papers

    seen: list[dict[str, Any]] = []

    for paper in papers:
        doi = paper.get("doi")
        sid = paper.get("source_id")
        title = _title_key(paper.get("title", ""))
        year = paper.get("year")
        authors = paper.get("authors", [])
        first_author = authors[0].lower().strip() if authors else ""

        matched = False
        for existing in seen:
            # 1. DOI match
            if doi and doi == existing.get("doi"):
                _merge(existing, paper)
                matched = True
                break
            # 2. source ID match
            if (
                sid
                and sid == existing.get("source_id")
                and paper.get("source") == existing.get("source")
            ):
                _merge(existing, paper)
                matched = True
                break
            # 3. Title + year match
            e_title = _title_key(existing.get("title", ""))
            if title and e_title and title == e_title and year and year == existing.get("year"):
                _merge(existing, paper)
                matched = True
                break
            # 4. Title similarity + first author
            e_authors = existing.get("authors", [])
            e_first = e_authors[0].lower().strip() if e_authors else ""
            if (
                first_author
                and e_first
                and first_author == e_first
                and _title_similarity(title, e_title) > 0.85
            ):
                existing["possible_duplicate_of"] = existing.get("paper_id")
                # Keep both but mark the second
                paper["possible_duplicate_of"] = existing["paper_id"]
                break

        if not matched:
            seen.append(paper)

    return seen


def _merge(keep: dict[str, Any], new: dict[str, Any]) -> None:
    """Merge metadata from *new* into *keep*, preferring non‑empty values."""
    sources = set(keep.get("matched_sources", [keep.get("source")]))
    if new.get("source"):
        sources.add(new["source"])
    keep["matched_sources"] = sorted(sources)

    for field in ("abstract", "doi", "pdf_url", "canonical_url", "citation_count", "venue"):
        if not keep.get(field) and new.get(field):
            keep[field] = new[field]
    # Prefer journal version over preprint
    if keep.get("is_preprint") and not new.get("is_preprint"):
        keep["is_preprint"] = False


def _title_similarity(a: str, b: str) -> float:
    """Simple token‑overlap similarity: Jaccard on word tokens."""
    if not a or not b:
        return 0.0
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
