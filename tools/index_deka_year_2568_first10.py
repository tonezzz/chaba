import json
import time
from typing import Any, Dict, List, Optional
import urllib.request


MCP_DEKA_URL = "http://127.0.0.1:8270/invoke"
MCP_RAG_DEKA_URL = "http://127.0.0.1:8056/invoke"

YEAR = 2568
MAX_PAGES = 3
N_DOCS = 10

SLEEP_BETWEEN_DOCS_SECONDS = 2.0


def _post_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = resp.read().decode("utf-8", errors="replace")
    data = json.loads(out) if out else {}
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected response: {out[:200]}")
    return data


def _mcp_deka(tool: str, args: Dict[str, Any], *, timeout: int = 240) -> Dict[str, Any]:
    return _post_json(MCP_DEKA_URL, {"tool": tool, "arguments": args}, timeout=timeout)


def _mcp_rag_deka(tool: str, args: Dict[str, Any], *, timeout: int = 300) -> Dict[str, Any]:
    return _post_json(MCP_RAG_DEKA_URL, {"tool": tool, "arguments": args}, timeout=timeout)


def _split_paragraphs(text: str) -> List[str]:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    paras: List[str] = []
    buff: List[str] = []
    for ln in lines:
        if not ln:
            if buff:
                paras.append(" ".join(buff).strip())
                buff = []
            continue
        buff.append(ln)
    if buff:
        paras.append(" ".join(buff).strip())

    out: List[str] = []
    seen = set()
    for p in paras:
        p2 = " ".join(p.split()).strip()
        if not p2:
            continue
        if p2 in seen:
            continue
        seen.add(p2)
        out.append(p2)
    return out


def _upsert_doc(doc_id: str, *, source_year: Optional[int], short_text: str, long_text: str) -> int:
    items: List[Dict[str, Any]] = []

    for field_name, text in (("short_text", short_text), ("long_text", long_text)):
        if not (text or "").strip():
            continue
        paras = _split_paragraphs(text)
        for idx, p in enumerate(paras, start=1):
            items.append(
                {
                    "id": f"deka:{doc_id}:{field_name}:{idx}",
                    "text": p,
                    "metadata": {
                        "doc_id": doc_id,
                        "source_year": source_year,
                        "field": field_name,
                        "paragraph": idx,
                        "source": "mcp_deka_hydrate",
                    },
                }
            )

    if not items:
        return 0

    res = _mcp_rag_deka("upsert_text", {"items": items}, timeout=600)
    result = res.get("result") or {}
    return int(result.get("upserted") or 0)


def _hydrate_parse_upsert(doc_id: str) -> Dict[str, Any]:
    hydrate = _mcp_deka(
        "hydrate_doc",
        {
            "docId": doc_id,
            "startYear": YEAR,
            "endYear": YEAR,
            "clickShort": True,
            "timeoutMs": 120000,
        },
        timeout=240,
    )
    run_id = ((hydrate.get("result") or {}).get("run_id") or "").strip()
    if not run_id:
        raise RuntimeError(f"hydrate_doc returned no run_id for doc_id={doc_id}")

    parsed = _mcp_deka(
        "parse_hydrated_run",
        {"runId": run_id, "docId": doc_id},
        timeout=180,
    )

    hydrated = _mcp_deka(
        "get_hydrated_doc",
        {"docId": doc_id, "maxChars": 450000},
        timeout=60,
    )
    h = hydrated.get("result") or {}

    upserted = _upsert_doc(
        doc_id,
        source_year=h.get("source_year"),
        short_text=str(h.get("short_text") or ""),
        long_text=str(h.get("long_text") or ""),
    )

    return {
        "doc_id": doc_id,
        "run_id": run_id,
        "parse": parsed.get("result") or {},
        "upserted": upserted,
    }


def main() -> None:
    print(f"Discovering year {YEAR} (maxPages={MAX_PAGES})...")
    _mcp_deka(
        "discover_basic_year",
        {"startYear": YEAR, "endYear": YEAR, "maxPages": MAX_PAGES, "timeoutMs": 90000},
        timeout=300,
    )

    print("Listing discovered doc_ids...")
    discovered = _mcp_deka(
        "list_discovered",
        {"sourceYear": YEAR, "limit": 200},
        timeout=60,
    )
    docs = (discovered.get("result") or {}).get("docs") or []
    doc_ids = [str(d.get("doc_id") or "").strip() for d in docs if isinstance(d, dict)]
    doc_ids = [d for d in doc_ids if d]

    if not doc_ids:
        raise SystemExit(f"No discovered doc_ids for year {YEAR}.")

    target = doc_ids[:N_DOCS]
    print(f"Hydrating + indexing {len(target)} docs...")

    results: List[Dict[str, Any]] = []
    for i, doc_id in enumerate(target, start=1):
        print(f"[{i}/{len(target)}] doc_id={doc_id}")
        try:
            results.append(_hydrate_parse_upsert(doc_id))
        except Exception as e:
            results.append({"doc_id": doc_id, "error": str(e)})
        time.sleep(SLEEP_BETWEEN_DOCS_SECONDS)

    ok = [r for r in results if not r.get("error")]
    fail = [r for r in results if r.get("error")]

    print(json.dumps({"ok": len(ok), "fail": len(fail), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
