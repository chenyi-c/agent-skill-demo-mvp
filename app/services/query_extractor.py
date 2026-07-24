"""Deterministic, LLM-free extraction of academic search terms."""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, Field


class QueryExtractionResult(BaseModel):
    original_text: str
    normalized_query: str = ""
    keywords: list[str] = Field(default_factory=list)
    removed_phrases: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    needs_clarification: bool = False


_TECH_TERMS = (
    "检索增强生成", "计算机视觉", "自然语言处理", "演化博弈法", "演化博弈",
    "深度学习", "机器学习", "强化学习", "大语言模型", "知识图谱",
    "图神经网络", "联邦学习", "迁移学习", "对比学习", "推荐系统",
    "目标检测", "图像分割", "语音识别", "多模态", "扩散模型",
    "RAG", "LLM", "Agent", "Transformer", "BERT", "GPT", "GAN",
)

_REMOVE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"我想(?:要)?(?:研究|了解|看看|查找|检索|搜索)?",
        r"(?:请|麻烦|能否|能不能|可以不可以)?(?:帮我|给我|为我)?"
        r"(?:查找|检索|搜索|找|查|看看|研究)?",
        r"(?:有没有|是否有|有哪些|有什么)(?:相关|有关)?",
        r"(?:论文|文献|资料|文章)(?:清单|列表)?",
        r"数据来源.{0,12}(?:不清楚|不太清楚|不知道|不确定|未确定)",
        r"(?:不太清楚|不清楚|不知道|不确定|还没确定)",
        r"(?:谢谢|感谢|拜托|麻烦了)",
        r"(?:关于|有关|方面|方向|领域|这个|这些|一下)",
    )
)

_STOP_WORDS = {
    "研究", "论文", "文献", "资料", "文章", "方法", "问题", "相关", "方向",
    "领域", "内容", "信息", "来源", "帮忙", "需要", "希望", "想要",
}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def extract_query(text: str) -> QueryExtractionResult:
    original = text
    normalized_text = unicodedata.normalize("NFKC", text).strip()
    removed: list[str] = []

    quoted = [
        value.strip()
        for value in re.findall(r'["“”「」『』《》]([^"“”「」『』《》]+)["“”「」『』《》]', normalized_text)
        if value.strip()
    ]

    cleaned = normalized_text
    for pattern in _REMOVE_PATTERNS:
        matches = [m.group(0).strip() for m in pattern.finditer(cleaned) if m.group(0).strip()]
        removed.extend(matches)
        cleaned = pattern.sub(" ", cleaned)

    # Search constraints are useful to the SearchPlan, but not to the query itself.
    cleaned = re.sub(r"(?:近\s*\d+\s*年|\d{4}\s*[-–—至到]\s*\d{4}|\d{4}\s*年(?:以后|以前)?)", " ", cleaned)
    cleaned = re.sub(r"(?:只要|不要|排除|包含)?\s*(?:期刊|会议|预印本|arxiv)", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[，。！？、；：,.!?;:/()（）\[\]{}]+", " ", cleaned)

    terms: list[str] = []
    terms.extend(quoted)
    for term in sorted(_TECH_TERMS, key=len, reverse=True):
        if re.search(re.escape(term), normalized_text, re.IGNORECASE):
            terms.append(term)

    # Preserve explicit English technical tokens and acronyms.
    terms.extend(
        token
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9+_.-]{1,30}\b", cleaned)
        if token.casefold() not in {"paper", "papers", "literature", "search"}
    )

    # Remaining Chinese phrase is useful when it is specific enough.
    chinese_chunks = re.findall(r"[\u4e00-\u9fff]{2,16}", cleaned)
    for chunk in chinese_chunks:
        if chunk not in _STOP_WORDS and not all(word in chunk for word in ("研究", "方法")):
            reduced = chunk
            for stop in sorted(_STOP_WORDS, key=len, reverse=True):
                reduced = reduced.replace(stop, " ")
            terms.extend(part for part in reduced.split() if len(part) >= 2)

    keywords = _dedupe([term.strip() for term in terms if term.strip()])[:8]
    query = " ".join(keywords)

    if quoted or any(term in normalized_text for term in _TECH_TERMS):
        confidence = 0.9
    elif len(keywords) >= 2:
        confidence = 0.7
    elif len(keywords) == 1 and len(keywords[0]) >= 3:
        confidence = 0.55
    else:
        confidence = 0.1

    return QueryExtractionResult(
        original_text=original,
        normalized_query=query,
        keywords=keywords,
        removed_phrases=_dedupe(removed),
        confidence=confidence,
        needs_clarification=confidence < 0.5,
    )
