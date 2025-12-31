import json
import re
import html as html_lib
from pathlib import Path
import urllib.request


def main() -> None:
    html_path = Path(r"c:\chaba_wt\dev-features\stacks\pc1-stack\data\mcp-playwright\output\1767091587902-1yn8u8pbkfg.html")
    data = html_path.read_text(encoding="utf-8", errors="ignore")

    doc_id = "712126"
    m = re.search(
        rf"<li[^>]*id=\"long_text_docid_{doc_id}\"[^>]*>(.*?)</li>",
        data,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        raise SystemExit(f"Could not find long_text block for doc_id {doc_id}")

    block = m.group(1)

    ps = re.findall(
        r"<p[^>]*class=\"content-detail\"[^>]*>(.*?)</p>",
        block,
        flags=re.IGNORECASE | re.DOTALL,
    )

    paras: list[str] = []
    for p in ps:
        t = re.sub(r"<[^>]+>", " ", p)
        t = html_lib.unescape(t)
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            paras.append(t)

    seen: set[str] = set()
    uniq: list[str] = []
    for t in paras:
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)

    items: list[dict] = []
    for i, t in enumerate(uniq, start=1):
        items.append(
            {
                "id": f"deka:{doc_id}:long:{i}",
                "text": t,
                "metadata": {
                    "doc_id": doc_id,
                    "source_year": 2567,
                    "field": "long_text",
                    "paragraph": i,
                    "source": "captured_html",
                    "capture_file": str(html_path),
                },
            }
        )

    payload = {"tool": "upsert_text", "arguments": {"items": items}}

    url = "http://127.0.0.1:8056/invoke"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        out = resp.read().decode("utf-8", errors="replace")
    print(out)


if __name__ == "__main__":
    main()
