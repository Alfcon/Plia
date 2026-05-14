"""
Multi-hop research with citations (planner loop + evidence aggregation)

This module is intentionally UI-agnostic:
- It runs the multi-hop search loop via Plia's existing `web_search` executor.
- It produces a STRICT final-synthesis context prompt that instructs the LLM
  to output:
    1) an answer containing only provided numbered citations like [1], [2]...
    2) a "Sources:" bibliography mapping each [n] to a URL from the evidence list.

The UI layer (`gui/handlers.py`) is responsible for streaming the final synthesis
through Ollama (so existing TTS + sentence buffering keep working).

No attempt is made here to stream output.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from core.function_executor import executor as function_executor


@dataclass(frozen=True)
class EvidenceSource:
    # 1-based bibliography index
    cite_id: int
    title: str
    snippet: str
    url: str
    query: str
    hop: int


def _ollama_chat_url(ollama_url: str) -> str:
    """
    Accept either:
      - http://localhost:11434
      - http://localhost:11434/api
    Return:
      http://localhost:11434/api/chat
    """
    base = ollama_url.rstrip("/api").rstrip("/")
    return f"{base}/api/chat"


def _safe_truncate(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1] + "…"


def _extract_json_array(text: str) -> List[str]:
    """
    Extract a JSON array of strings from arbitrary model output.
    """
    if not text:
        return []
    # Prefer fenced JSON
    m = re.search(r"```json\s*(\[[\s\S]*?\])\s*```", text, re.IGNORECASE)
    if m:
        candidate = m.group(1)
    else:
        # Fallback: first [...] block
        m2 = re.search(r"(\[[\s\S]*?\])", text)
        candidate = m2.group(1) if m2 else text

    try:
        parsed = json.loads(candidate)
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []
    out: List[str] = []
    for item in parsed:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
    return out


def plan_subqueries(
    *,
    question: str,
    hops: int,
    ollama_url: str,
    model: str,
    session: Optional[requests.Session] = None,
    max_subqueries: Optional[int] = None,
) -> List[str]:
    """
    Generate N focused search queries (planner loop).

    Returns exactly `hops` strings when possible.
    """
    if hops <= 0:
        return []

    session = session or requests.Session()
    chat_url = _ollama_chat_url(ollama_url)

    hops_int = int(hops)
    want = hops_int if max_subqueries is None else min(hops_int, int(max_subqueries))

    planner_system = (
        "You are a research planner. Generate search queries for multi-hop web research.\n"
        "Output ONLY a JSON array of strings.\n"
        "Rules:\n"
        f"- Return exactly {want} queries.\n"
        "- Each query should be short, specific, and useful for the next hop.\n"
        "- Avoid duplicates.\n"
        "- Do not include URLs.\n"
        "- Queries should be in natural language suitable for DuckDuckGo.\n"
    )

    payload: Dict[str, Any] = {
        "model": model,
        "stream": False,
        "keep_alive": "5m",
        "options": {
            "temperature": 0.25,
            "num_predict": 256,
        },
        "messages": [
            {"role": "system", "content": planner_system},
            {
                "role": "user",
                "content": (
                    f"User question:\n{question}\n\n"
                    f"Generate {want} search queries for multi-hop research to answer it."
                ),
            },
        ],
    }

    r = session.post(chat_url, json=payload, timeout=60)
    r.raise_for_status()
    content = r.json().get("message", {}).get("content", "")
    queries = _extract_json_array(content)

    # Best-effort fallback if the model didn't follow format
    if len(queries) < want:
        # Try to split by lines/bullets
        lines = [ln.strip(" -\t\r\n") for ln in (content or "").splitlines() if ln.strip()]
        for ln in lines:
            if len(queries) >= want:
                break
            # crude heuristic: skip very short fragments
            if len(ln) >= 3 and ln not in queries:
                queries.append(ln)
    return queries[:want]


def _iter_search_results(
    search_result_payload: Any,
) -> Iterable[Dict[str, str]]:
    """
    Normalize `FunctionExecutor._web_search` output structure.
    Expected:
      { "success": bool, "data": { "query": ..., "results": [ {title, body, url}, ...]}}
    """
    if not isinstance(search_result_payload, dict):
        return []
    data = search_result_payload.get("data") if search_result_payload else None
    if not isinstance(data, dict):
        return []
    results = data.get("results", [])
    if not isinstance(results, list):
        return []
    for r in results:
        if not isinstance(r, dict):
            continue
        yield {
            "title": str(r.get("title", "") or ""),
            "snippet": str(r.get("body", "") or ""),
            "url": str(r.get("url", "") or ""),
        }


def gather_evidence_for_queries(
    *,
    queries: Sequence[str],
    results_per_hop: int,
    max_sources: int,
    snippet_chars: int,
) -> List[EvidenceSource]:
    """
    Run `web_search` for each query and collect evidence sources.

    Deduplication: by URL.
    """
    evidence: List[EvidenceSource] = []
    seen_urls: set[str] = set()

    cite_id = 1
    results_per_hop_int = max(1, int(results_per_hop))
    max_sources_int = max(1, int(max_sources))
    snippet_chars_int = max(0, int(snippet_chars))

    for hop_index, q in enumerate(queries, start=1):
        if len(evidence) >= max_sources_int:
            break

        q = (q or "").strip()
        if not q:
            continue

        r = function_executor.execute("web_search", {"query": q})
        if not isinstance(r, dict) or not r.get("success"):
            continue

        hop_results = []
        for item in _iter_search_results(r):
            if not item.get("url"):
                continue
            hop_results.append(item)

        # Limit hop results to keep prompt small
        hop_results = hop_results[:results_per_hop_int]

        for item in hop_results:
            if len(evidence) >= max_sources_int:
                break
            url = item.get("url", "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            evidence.append(
                EvidenceSource(
                    cite_id=cite_id,
                    title=_safe_truncate(item.get("title", ""), 120),
                    snippet=_safe_truncate(item.get("snippet", ""), snippet_chars_int),
                    url=url,
                    query=q,
                    hop=hop_index,
                )
            )
            cite_id += 1

    return evidence


def build_citation_context_prompt(
    *,
    question: str,
    evidence: Sequence[EvidenceSource],
    max_sources: int,
) -> Tuple[str, List[EvidenceSource]]:
    """
    Build a strict prompt for final synthesis that includes:
    - Evidence snippets
    - Citation rules: only use [n] from bibliography
    - A bibliography section (Sources: list) with [n] -> URL

    Returns (context_msg, bibliography_evidence).
    """
    max_sources_int = max(1, int(max_sources))
    trimmed = list(evidence)[:max_sources_int]

    # Re-index to ensure contiguous [1..k] even after trimming
    reindexed: List[EvidenceSource] = []
    for i, e in enumerate(trimmed, start=1):
        reindexed.append(
            EvidenceSource(
                cite_id=i,
                title=e.title,
                snippet=e.snippet,
                url=e.url,
                query=e.query,
                hop=e.hop,
            )
        )

    bib_lines = []
    for e in reindexed:
        bib_lines.append(f"[{e.cite_id}] {e.title} — {e.url}")

    evidence_blocks = []
    for e in reindexed:
        evidence_blocks.append(
            "----\n"
            f"SOURCE [{e.cite_id}] (hop {e.hop}):\n"
            f"Title: {e.title}\n"
            f"Query: {e.query}\n"
            f"Snippet: {e.snippet}\n"
            f"URL: {e.url}\n"
        )

    context_msg = (
        "You are performing multi-hop research with strict citations.\n\n"
        "USER QUESTION:\n"
        f"{question}\n\n"
        "EVIDENCE SNIPPETS (use ONLY these):\n\n"
        + "".join(evidence_blocks)
        + "\n"
        "CITATION RULES (MUST FOLLOW):\n"
        "1) Every factual sentence/claim in your answer MUST include at least one citation token like [n].\n"
        "2) You may only cite using [n] values that appear in the bibliography below.\n"
        "3) Do not invent sources. If you cannot support something with evidence, say so.\n"
        "4) Output format:\n"
        "   - First: your answer text\n"
        "   - Then: a section exactly starting with 'Sources:'\n"
        "   - In 'Sources:', list every bibliography line exactly once.\n\n"
        "BIBLIOGRAPHY (citations must map to these URLs):\n"
        + "\n".join(bib_lines)
    )

    return context_msg, reindexed


def parse_citation_ids(text: str) -> List[int]:
    """
    Return citation IDs found in the text, in order of appearance.
    """
    if not text:
        return []
    ids = []
    for m in re.finditer(r"\[(\d+)\]", text):
        try:
            ids.append(int(m.group(1)))
        except Exception:
            continue
    return ids


def validate_citations(text: str, evidence_count: int) -> bool:
    """
    Validate that all citations are in-range [1..evidence_count].

    Note: this does not confirm that each claim has citations; it only checks
    that citations refer to existing bibliography numbers.
    """
    if evidence_count <= 0:
        return False
    ids = parse_citation_ids(text)
    if not ids:
        return False
    for cid in ids:
        if cid < 1 or cid > evidence_count:
            return False
    return True


def research_with_citations_context(
    *,
    question: str,
    hops: int,
    results_per_hop: int,
    max_sources: int,
    snippet_chars: int,
    ollama_url: str,
    planner_model: str,
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    """
    High-level convenience: plan queries, gather evidence, build context prompt.

    Returns:
      {
        "queries": [...],
        "evidence": [EvidenceSource...],
        "context_msg": str,
      }
    """
    session = session or requests.Session()

    queries = plan_subqueries(
        question=question,
        hops=hops,
        ollama_url=ollama_url,
        model=planner_model,
        session=session,
    )

    evidence = gather_evidence_for_queries(
        queries=queries,
        results_per_hop=results_per_hop,
        max_sources=max_sources,
        snippet_chars=snippet_chars,
    )

    context_msg, reindexed = build_citation_context_prompt(
        question=question,
        evidence=evidence,
        max_sources=max_sources,
    )

    return {
        "queries": queries,
        "evidence": reindexed,
        "context_msg": context_msg,
    }
