"""Normalise raw paper data into PaperRecord-compatible dicts (Section 4.6)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def normalise_authors(raw: Any) -> list[str]:
    """Return a flat list of author name strings regardless of input shape."""
    if raw is None:
        return []
    if isinstance(raw, list):
        result: list[str] = []
        for item in raw:
            if isinstance(item, str):
                result.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name", item.get("author", ""))
                if isinstance(name, str) and name.strip():
                    result.append(name.strip())
            elif isinstance(item, (int, float)):
                result.append(str(item))
        return result
    if isinstance(raw, str):
        # Semicolon or comma separated
        parts = re.split(r"[;；]\s*", raw)
        if len(parts) == 1:
            parts = re.split(r",\s*", raw)
        return [p.strip() for p in parts if p.strip()]
    return []


def normalise_year(raw: Any) -> int | None:
    """Extract an integer year from any common date representation."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        y = int(raw)
        return y if 1900 <= y <= 2100 else None
    if isinstance(raw, datetime):
        return raw.year
    if isinstance(raw, str):
        m = re.search(r"(19|20)\d{2}", raw)
        if m:
            return int(m.group())
    if isinstance(raw, list):
        for item in raw:
            yr = normalise_year(item)
            if yr is not None:
                return yr
    return None


def normalise_doi(raw: Any) -> str | None:
    """Lowercase, strip prefix.  Returns None for obviously invalid values."""
    if raw is None:
        return None
    if isinstance(raw, str):
        doi = raw.strip().lower()
        # Remove common prefixes
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi/"):
            if doi.startswith(prefix):
                doi = doi[len(prefix):]
        if re.match(r"^10\.\d{4,}/", doi):
            return doi
    return None


def normalise_url(raw: Any) -> str | None:
    """Only allow http/https URLs."""
    if raw is None:
        return None
    url = str(raw).strip()
    if url.startswith(("https://", "http://")):
        return url
    return None


def normalise_record(raw: dict[str, Any], source: str) -> dict[str, Any]:
    """Convert a raw paper dict into a PaperRecord-ready dict."""
    title = str(raw.get("title", "")).strip() or "无标题"
    authors = normalise_authors(raw.get("authors"))
    year = normalise_year(raw.get("published_date", raw.get("year")))
    doi = normalise_doi(raw.get("doi"))
    url = normalise_url(raw.get("url", raw.get("canonical_url")))

    citations = raw.get("citation_count", raw.get("citations"))
    try:
        citation_count = int(citations) if citations is not None else None
    except (TypeError, ValueError):
        citation_count = None
    abstract = raw.get("abstract")
    if abstract is not None and not isinstance(abstract, str):
        abstract = str(abstract)
    venue = raw.get("venue") or raw.get("container_title")
    if isinstance(venue, list):
        venue = next((str(v) for v in venue if v), None)
    elif venue is not None:
        venue = str(venue)
    source_id = raw.get("paper_id") or raw.get("id") or raw.get("doi")

    return {
        "paper_id": str(source_id or f"{source}:{title}:{year or ''}"),
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "year": year,
        "published_date": str(raw.get("published_date") or raw.get("year") or "") or None,
        "doi": doi,
        "canonical_url": url,
        "pdf_url": normalise_url(raw.get("pdf_url")),
        "citation_count": citation_count,
        "source": source,
        "source_id": str(source_id) if source_id else None,
        "is_preprint": source == "arxiv" or "preprint" in str(raw.get("publication_type", "")).lower(),
        "venue": venue,
        "publication_type": raw.get("publication_type") or (
            "preprint" if source == "arxiv" else "journal_article"
        ),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "raw_metadata": raw,
    }
