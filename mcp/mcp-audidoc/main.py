from __future__ import annotations

import json
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader

APP_NAME = "mcp-audidoc"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8075"))
AUDIDOC_ROOT = (os.getenv("AUDIDOC_ROOT") or os.getcwd()).strip()
AUDIDOC_PDF_DIR = (os.getenv("AUDIDOC_PDF_DIR") or "audidoc-pdfs").strip()


def _utc_ms() -> int:
    import time

    return int(time.time() * 1000)


def _safe_resolve_under_root(raw_path: str) -> Path:
    if not raw_path or not isinstance(raw_path, str):
        raise HTTPException(status_code=400, detail="missing_path")

    root = Path(AUDIDOC_ROOT).resolve()
    candidate = (root / raw_path).resolve()

    try:
        candidate.relative_to(root)
    except Exception:
        raise HTTPException(status_code=403, detail="path_outside_root")

    return candidate


def _discover_pdfs() -> List[Path]:
    root = Path(AUDIDOC_ROOT).resolve()
    base = (root / AUDIDOC_PDF_DIR).resolve()
    try:
        base.relative_to(root)
    except Exception:
        raise HTTPException(status_code=500, detail="AUDIDOC_PDF_DIR_outside_root")
    if not base.exists() or not base.is_dir():
        return []
    pdfs = sorted([p for p in base.rglob("*.pdf") if p.is_file()])
    return pdfs


def _html_escape(value: Any) -> str:
    import html

    return html.escape(str(value) if value is not None else "")


@dataclass(frozen=True)
class FrontmatterParse:
    frontmatter: Dict[str, Any]
    body: str


def _parse_frontmatter(text: str) -> FrontmatterParse:
    if not isinstance(text, str) or not text.startswith("---\n"):
        return FrontmatterParse(frontmatter={}, body=text if isinstance(text, str) else "")

    end = text.find("\n---\n", 4)
    if end == -1:
        return FrontmatterParse(frontmatter={}, body=text)

    raw = text[4:end]
    body = text[end + 5 :]

    try:
        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    return FrontmatterParse(frontmatter=data, body=body)


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


class AuditDocumentsArgs(BaseModel):
    paths: List[str] = Field(..., description="Document paths relative to AUDIDOC_ROOT")
    required_frontmatter_fields: List[str] = Field(default_factory=list)
    field_aliases: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Map canonical field -> list of acceptable aliases (e.g. {title:[name,subject]})",
    )


class AuditPdfSubdocumentsArgs(BaseModel):
    path: str = Field(..., description="PDF path relative to AUDIDOC_ROOT")
    expected_names: List[str] = Field(
        default_factory=list,
        description="Expected sub-document names to verify (matched against attachment names and outline titles).",
    )
    match_mode: str = Field(
        "contains",
        description="How to match expected_names against found names: 'contains' or 'equals'",
    )


class PdfGeneralInfoArgs(BaseModel):
    paths: List[str] = Field(..., description="PDF paths relative to AUDIDOC_ROOT")
    max_pages: int = Field(5, description="Max pages to extract text preview from (bounded)")
    max_chars_per_page: int = Field(1200, description="Max characters of extracted text per page (bounded)")


class AuditCrossChecksArgs(BaseModel):
    paths: List[str] = Field(default_factory=list, description="PDF paths relative to AUDIDOC_ROOT")
    auto_discover: bool = Field(True, description="If true, ignore paths and scan AUDIDOC_PDF_DIR")
    required_doc_types: List[str] = Field(
        default_factory=lambda: ["บัญชี", "เช็ค"],
        description="Doc types required for each (project, period) group",
    )
    period_filter: str = Field("", description="Optional period filter (e.g. 2568-08)")


class ChatArgs(BaseModel):
    message: str


def _tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "audit_documents",
            "description": "Audit documents for missing/mismatched frontmatter metadata fields.",
            "inputSchema": AuditDocumentsArgs.model_json_schema(),
        }
        ,
        {
            "name": "audit_pdf_subdocuments",
            "description": "Audit a PDF for missing sub-documents (embedded attachments and outline/bookmark titles).",
            "inputSchema": AuditPdfSubdocumentsArgs.model_json_schema(),
        }
        ,
        {
            "name": "pdf_general_info",
            "description": "Extract general info from PDFs: metadata, sha256, page count, and text preview/stats.",
            "inputSchema": PdfGeneralInfoArgs.model_json_schema(),
        }
        ,
        {
            "name": "audit_cross_checks",
            "description": "Minimal cross-doc checks across PDFs using filename/folder claims (project, period, doc_type).",
            "inputSchema": AuditCrossChecksArgs.model_json_schema(),
        }
    ]


def _normalize_text(v: str) -> str:
    return " ".join((v or "").strip().split())


def _infer_project_from_path(path: Path) -> Optional[str]:
    root = Path(AUDIDOC_ROOT).resolve()
    try:
        rel = path.resolve().relative_to(root)
    except Exception:
        rel = path

    parts = list(rel.parts)
    if not parts:
        return None
    if parts[0].lower() == AUDIDOC_PDF_DIR.lower() and len(parts) >= 2:
        return _normalize_text(parts[1]) or None
    if len(parts) >= 2:
        return _normalize_text(parts[0]) or None
    return None


def _infer_doc_type_from_path(path: Path) -> Optional[str]:
    name = _normalize_text(path.parent.name)
    if not name:
        return None
    lowered = name.lower()
    if "บัญชี" in lowered:
        return "บัญชี"
    if "เช็ค" in lowered:
        return "เช็ค"
    if "รายรับ" in lowered:
        return "รายรับ"
    return name


def _infer_period_from_path(path: Path) -> Optional[str]:
    text = _normalize_text(path.name)
    m = re.search(r"(\d{4})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m2 = re.search(r"(\d{4})-(\d{2})", _normalize_text(path.parent.name))
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}"
    return None


def _extract_claims_from_path(path: Path) -> Dict[str, Any]:
    project = _infer_project_from_path(path)
    period = _infer_period_from_path(path)
    doc_type = _infer_doc_type_from_path(path)
    issues: List[Dict[str, Any]] = []
    if not project:
        issues.append({"code": "missing_project_claim", "path": str(path)})
    if not period:
        issues.append({"code": "missing_period_claim", "path": str(path)})
    if not doc_type:
        issues.append({"code": "missing_doc_type_claim", "path": str(path)})
    return {
        "path": str(path),
        "claims": {"project": project, "period": period, "doc_type": doc_type},
        "issues": issues,
    }


def _audit_cross_checks(args: AuditCrossChecksArgs) -> Dict[str, Any]:
    root = Path(AUDIDOC_ROOT).resolve()
    pdfs: List[Path]
    if args.auto_discover:
        pdfs = _discover_pdfs()
    else:
        pdfs = [_safe_resolve_under_root(p) for p in (args.paths or [])]

    period_filter = _normalize_text(args.period_filter)
    required = [_normalize_text(x) for x in (args.required_doc_types or []) if _normalize_text(x)]
    if not required:
        required = ["บัญชี", "เช็ค"]

    docs: List[Dict[str, Any]] = []
    groups: Dict[str, Dict[str, Any]] = {}
    for p in pdfs:
        if p.suffix.lower() != ".pdf":
            continue
        doc = _extract_claims_from_path(p)
        claims = doc.get("claims") or {}
        project = claims.get("project")
        period = claims.get("period")
        doc_type = claims.get("doc_type")

        try:
            rel_out = str(p.relative_to(root))
        except Exception:
            rel_out = str(p)
        doc["path"] = rel_out
        docs.append(doc)

        if period_filter and period != period_filter:
            continue
        if not project or not period:
            continue

        key = f"{project}::{period}"
        g = groups.get(key)
        if not g:
            g = {
                "project": project,
                "period": period,
                "docs": [],
                "doc_types": [],
                "issues": [],
            }
            groups[key] = g

        g["docs"].append({"path": rel_out, "doc_type": doc_type})
        if isinstance(doc_type, str) and doc_type not in g["doc_types"]:
            g["doc_types"].append(doc_type)

    cross_issues: List[Dict[str, Any]] = []
    for key, g in groups.items():
        types = g.get("doc_types") or []
        missing = [t for t in required if t not in types]
        if missing:
            issue = {
                "code": "missing_required_doc_type",
                "project": g.get("project"),
                "period": g.get("period"),
                "missing": missing,
            }
            g["issues"].append(issue)
            cross_issues.append(issue)

    return {
        "root": str(root),
        "pdf_dir": AUDIDOC_PDF_DIR,
        "required_doc_types": required,
        "period_filter": period_filter or None,
        "documents": docs,
        "groups": list(groups.values()),
        "issues": cross_issues,
        "timestampMs": _utc_ms(),
    }


def _canonicalize_frontmatter(frontmatter: Dict[str, Any], field_aliases: Dict[str, List[str]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    lower_map = {str(k).strip().lower(): k for k in frontmatter.keys()}

    for canonical, aliases in (field_aliases or {}).items():
        if not canonical:
            continue
        canonical_key = canonical.strip()
        candidates = [canonical_key] + list(aliases or [])

        found_value: Any = None
        found_key: Optional[str] = None

        for candidate in candidates:
            c = str(candidate).strip().lower()
            if not c:
                continue
            original_key = lower_map.get(c)
            if original_key is None:
                continue
            found_key = str(original_key)
            found_value = frontmatter.get(original_key)
            break

        if found_key is not None:
            out[canonical_key] = found_value

    for k, v in (frontmatter or {}).items():
        if k not in out:
            out[str(k)] = v

    return out


def _audit_single(path: Path, args: AuditDocumentsArgs) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if not path.exists():
        return {}, [{"code": "missing_file", "path": str(path)}]
    if not path.is_file():
        return {}, [{"code": "not_a_file", "path": str(path)}]

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _audit_pdf_basic(path)

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {}, [{"code": "read_failed", "path": str(path), "detail": str(exc)}]

    parsed = _parse_frontmatter(text)
    canonical = _canonicalize_frontmatter(parsed.frontmatter, args.field_aliases)

    issues: List[Dict[str, Any]] = []

    required = [str(f).strip() for f in (args.required_frontmatter_fields or []) if str(f).strip()]
    for field in required:
        if field not in canonical or canonical.get(field) in (None, "", [], {}):
            issues.append({"code": "missing_field", "path": str(path), "field": field})

    if args.field_aliases:
        for canonical_field, aliases in args.field_aliases.items():
            if not canonical_field:
                continue
            canonical_field = str(canonical_field).strip()
            if canonical_field in parsed.frontmatter:
                continue
            for alias in aliases or []:
                alias_key = str(alias).strip()
                if not alias_key:
                    continue
                if alias_key in parsed.frontmatter:
                    issues.append(
                        {
                            "code": "alias_used",
                            "path": str(path),
                            "field": canonical_field,
                            "alias": alias_key,
                        }
                    )
                    break

    summary = {
        "path": str(path),
        "has_frontmatter": bool(parsed.frontmatter),
        "frontmatter": canonical,
    }

    return summary, issues


def _audit_pdf_basic(path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    issues: List[Dict[str, Any]] = []
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return {}, [{"code": "pdf_parse_failed", "path": str(path), "detail": str(exc)}]

    attachments = _pdf_list_attachments(reader)
    outline_titles = _pdf_list_outline_titles(reader)

    summary: Dict[str, Any] = {
        "path": str(path),
        "type": "pdf",
        "pages": len(reader.pages) if getattr(reader, "pages", None) is not None else None,
        "attachments": attachments,
        "outline_titles": outline_titles,
    }

    if not attachments and not outline_titles:
        issues.append({"code": "pdf_no_subdoc_signals", "path": str(path)})

    return summary, issues


def _pdf_list_attachments(reader: PdfReader) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    root = getattr(reader, "root_object", None)
    if not root:
        return out

    try:
        names = root.get("/Names")
        if not names:
            return out
        embedded = names.get("/EmbeddedFiles")
        if not embedded:
            return out
        name_tree = embedded.get("/Names")
        if not name_tree:
            return out
        if not isinstance(name_tree, list):
            return out

        # name_tree is [name1, filespec1, name2, filespec2, ...]
        for i in range(0, len(name_tree), 2):
            name = name_tree[i]
            file_spec = name_tree[i + 1] if i + 1 < len(name_tree) else None
            filename = None
            size = None

            try:
                filename = str(name)
            except Exception:
                filename = None

            try:
                if file_spec and isinstance(file_spec, dict):
                    ef = file_spec.get("/EF")
                    if ef and isinstance(ef, dict):
                        fobj = ef.get("/F") or ef.get("/UF")
                        if fobj is not None:
                            data = fobj.get_data()  # type: ignore[attr-defined]
                            size = len(data) if data is not None else None
            except Exception:
                size = None

            out.append({"name": filename, "size": size})
    except Exception:
        return out

    return out


def _pdf_list_outline_titles(reader: PdfReader) -> List[str]:
    titles: List[str] = []
    try:
        outline = getattr(reader, "outline", None)
        if not outline:
            return titles
    except Exception:
        return titles

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return

        title = getattr(node, "title", None)
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())

        children = getattr(node, "children", None)
        if children is not None:
            walk(children)

    walk(outline)
    # de-dup (keep order)
    seen = set()
    out: List[str] = []
    for t in titles:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _match_expected(found: List[str], expected: str, mode: str) -> bool:
    e = (expected or "").strip().lower()
    if not e:
        return True
    for f in found:
        f2 = (f or "").strip().lower()
        if not f2:
            continue
        if mode == "equals":
            if f2 == e:
                return True
        else:
            if e in f2:
                return True
    return False


def _audit_pdf_subdocuments(path: Path, args: AuditPdfSubdocumentsArgs) -> Dict[str, Any]:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"pdf_parse_failed: {exc}")

    attachments = _pdf_list_attachments(reader)
    attachment_names = [a.get("name") for a in attachments if isinstance(a.get("name"), str)]
    outline_titles = _pdf_list_outline_titles(reader)

    found_names = [*attachment_names, *outline_titles]
    match_mode = (args.match_mode or "contains").strip().lower()
    if match_mode not in ("contains", "equals"):
        raise HTTPException(status_code=400, detail="invalid_match_mode")

    expected = [str(x).strip() for x in (args.expected_names or []) if str(x).strip()]
    missing: List[str] = []
    for e in expected:
        if not _match_expected(found_names, e, match_mode):
            missing.append(e)

    issues: List[Dict[str, Any]] = []
    for e in missing:
        issues.append({"code": "missing_subdocument", "path": str(path), "expected": e})

    if not expected:
        issues.append({"code": "no_expected_names_provided", "path": str(path)})

    return {
        "path": str(path),
        "pages": len(reader.pages) if getattr(reader, "pages", None) is not None else None,
        "attachments": attachments,
        "outline_titles": outline_titles,
        "expected": expected,
        "missing": missing,
        "issues": issues,
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_pdf_text_preview(
    reader: PdfReader, *, max_pages: int, max_chars_per_page: int
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    previews: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    page_count = len(reader.pages) if getattr(reader, "pages", None) is not None else 0
    pages_to_read = min(max_pages, page_count)

    for i in range(pages_to_read):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception as exc:
            issues.append({"code": "pdf_text_extract_failed", "page": i + 1, "detail": str(exc)})
            text = ""

        cleaned = " ".join(text.split())
        preview = cleaned[: max_chars_per_page]
        previews.append(
            {
                "page": i + 1,
                "chars": len(cleaned),
                "preview": preview,
                "truncated": len(cleaned) > max_chars_per_page,
            }
        )

    return previews, issues


def _pdf_general_info_one(path: Path, args: PdfGeneralInfoArgs) -> Dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "issues": [{"code": "missing_file", "path": str(path)}]}
    if not path.is_file():
        return {"path": str(path), "issues": [{"code": "not_a_file", "path": str(path)}]}
    if path.suffix.lower() != ".pdf":
        return {"path": str(path), "issues": [{"code": "not_a_pdf", "path": str(path)}]}

    st = path.stat()
    issues: List[Dict[str, Any]] = []

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return {"path": str(path), "issues": [{"code": "pdf_parse_failed", "path": str(path), "detail": str(exc)}]}

    meta: Dict[str, str] = {}
    try:
        meta = {str(k): str(v) for k, v in (reader.metadata or {}).items()}
    except Exception:
        meta = {}

    attachments = _pdf_list_attachments(reader)
    outline_titles = _pdf_list_outline_titles(reader)

    max_pages = int(args.max_pages or 0)
    if max_pages < 0:
        max_pages = 0
    max_pages = min(max_pages, 50)

    max_chars_per_page = int(args.max_chars_per_page or 0)
    if max_chars_per_page < 0:
        max_chars_per_page = 0
    max_chars_per_page = min(max_chars_per_page, 20000)

    previews, preview_issues = _extract_pdf_text_preview(
        reader, max_pages=max_pages, max_chars_per_page=max_chars_per_page
    )
    issues.extend(preview_issues)

    sha256 = _sha256_file(path)

    return {
        "path": str(path),
        "type": "pdf",
        "bytes": int(st.st_size),
        "modified_ts": int(st.st_mtime),
        "sha256": sha256,
        "pages": len(reader.pages) if getattr(reader, "pages", None) is not None else None,
        "meta": meta,
        "attachments": attachments,
        "outline_titles": outline_titles,
        "text_preview": previews,
        "issues": issues,
    }


app = FastAPI(title=APP_NAME, version=APP_VERSION)


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return """<!doctype html><html><head><meta charset='utf-8' /><meta http-equiv='refresh' content='0; url=/www/status' /></head><body><a href='/www/status'>Open status</a></body></html>"""


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "root": str(Path(AUDIDOC_ROOT).resolve()),
        "pdf_dir": AUDIDOC_PDF_DIR,
        "timestampMs": _utc_ms(),
    }


@app.get("/status")
async def status(max_pages: int = 1, max_chars_per_page: int = 200) -> Dict[str, Any]:
    args = PdfGeneralInfoArgs(paths=[], max_pages=max_pages, max_chars_per_page=max_chars_per_page)
    root = Path(AUDIDOC_ROOT).resolve()
    pdfs = _discover_pdfs()
    docs: List[Dict[str, Any]] = []
    for p in pdfs:
        info = _pdf_general_info_one(p, args)
        try:
            rel_out = str(p.relative_to(root))
        except Exception:
            rel_out = str(p)
        info["path"] = rel_out
        docs.append(info)

    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "root": str(root),
        "pdf_dir": AUDIDOC_PDF_DIR,
        "documents": docs,
        "count": len(docs),
        "timestampMs": _utc_ms(),
    }


@app.get("/www/status", response_class=HTMLResponse)
async def status_page(max_pages: int = 1, max_chars_per_page: int = 0) -> str:
    data = await status(max_pages=max_pages, max_chars_per_page=max_chars_per_page)
    docs = data.get("documents") or []

    rows: List[str] = []
    for d in docs:
        meta = d.get("meta") or {}
        title = meta.get("/Title") or ""
        creator = meta.get("/Creator") or ""
        sha256 = d.get("sha256") or ""
        pages = d.get("pages")
        issues = d.get("issues") or []
        issues_count = len(issues) if isinstance(issues, list) else 0
        rows.append(
            "<tr>"
            f"<td style=\"white-space:nowrap;\">{_html_escape(d.get('path'))}</td>"
            f"<td>{_html_escape(pages)}</td>"
            f"<td>{_html_escape(title)}</td>"
            f"<td>{_html_escape(creator)}</td>"
            f"<td style=\"font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;\">{_html_escape(sha256)[:16]}…</td>"
            f"<td>{_html_escape(issues_count)}</td>"
            "</tr>"
        )

    table_body = "\n".join(rows) if rows else "<tr><td colspan=\"6\" style=\"opacity:.8;\">No PDFs found.</td></tr>"

    return f"""
<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>mcp-audidoc status</title>
    <style>
      body {{ font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: #0f1115; color: #e5e7eb; margin: 0; padding: 24px; }}
      h1 {{ margin: 0 0 6px 0; font-size: 20px; }}
      .meta {{ opacity: .8; font-size: 13px; margin-bottom: 16px; }}
      table {{ width: 100%; border-collapse: collapse; background: #151922; border: 1px solid #262b36; }}
      th, td {{ border-bottom: 1px solid #1f2430; padding: 10px 10px; vertical-align: top; }}
      th {{ background: #1d2431; color: #9ca3af; text-transform: uppercase; letter-spacing: .06em; font-size: 12px; text-align: left; }}
      tr:hover td {{ background: #1c2230; }}
      a {{ color: #7dd3fc; text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
      .toolbar {{ display:flex; gap:10px; align-items:center; margin-bottom: 10px; }}
      .btn {{ background:#2563eb; border-radius: 999px; padding: 6px 12px; color:white; font-size: 13px; }}
      .btn.secondary {{ background:#374151; }}
    </style>
  </head>
  <body>
    <div class=\"toolbar\">
      <h1 style=\"flex:1;\">mcp-audidoc · Documents ({_html_escape(data.get('count'))})</h1>
      <a class=\"btn secondary\" href=\"/status?max_pages={int(max_pages)}&max_chars_per_page={int(max_chars_per_page)}\">JSON</a>
      <a class=\"btn secondary\" href=\"/www/chat\">Chat</a>
      <a class=\"btn\" href=\"/www/status?max_pages={int(max_pages)}&max_chars_per_page={int(max_chars_per_page)}\">Refresh</a>
    </div>
    <div class=\"meta\">
      Root: <code>{_html_escape(data.get('root'))}</code> · PDF dir: <code>{_html_escape(data.get('pdf_dir'))}</code> · Updated: <code>{_html_escape(data.get('timestampMs'))}</code>
    </div>
    <table>
      <thead>
        <tr>
          <th>Path</th>
          <th>Pages</th>
          <th>Title</th>
          <th>Creator</th>
          <th>SHA256</th>
          <th>Issues</th>
        </tr>
      </thead>
      <tbody>
        {table_body}
      </tbody>
    </table>
  </body>
</html>
"""


def _summarize_paths(paths: List[Path]) -> List[Dict[str, Any]]:
    root = Path(AUDIDOC_ROOT).resolve()
    out: List[Dict[str, Any]] = []
    for i, p in enumerate(paths, start=1):
        try:
            rel = str(p.relative_to(root))
        except Exception:
            rel = str(p)
        out.append({"index": i, "path": rel})
    return out


def _search_previews_in_status(docs: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return []
    hits: List[Dict[str, Any]] = []
    for d in docs:
        previews = d.get("text_preview")
        if not isinstance(previews, list):
            continue
        for p in previews:
            if not isinstance(p, dict):
                continue
            preview_text = str(p.get("preview") or "")
            if q in preview_text.lower():
                hits.append(
                    {
                        "path": d.get("path"),
                        "page": p.get("page"),
                        "snippet": preview_text,
                    }
                )
                break
    return hits


@app.post("/api/chat")
async def chat(req: ChatArgs = Body(...)) -> Dict[str, Any]:
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="missing_message")

    lower = msg.lower().strip()
    pdfs = _discover_pdfs()

    if lower in {"help", "?"}:
        return {
            "reply": "Commands:\n- list\n- show <index>\n- show <path>\n- search <text>\n- cross\n- cross <period>\n\nNotes: 'cross' runs minimal cross-doc checks using folder/filename claims.",
            "mode": "help",
        }

    if lower in {"list", "ls"}:
        items = _summarize_paths(pdfs)
        return {"reply": json.dumps({"documents": items}, ensure_ascii=False, indent=2), "mode": "list"}

    if lower.startswith("show "):
        arg = msg[5:].strip()
        if not arg:
            raise HTTPException(status_code=400, detail="missing_show_arg")

        selected: Optional[Path] = None
        if arg.isdigit():
            idx = int(arg)
            if 1 <= idx <= len(pdfs):
                selected = pdfs[idx - 1]
        else:
            try:
                selected = _safe_resolve_under_root(arg)
            except HTTPException:
                selected = None

        if not selected:
            return {"reply": json.dumps({"error": "not_found"}, ensure_ascii=False), "mode": "show"}

        info = _pdf_general_info_one(selected, PdfGeneralInfoArgs(paths=[], max_pages=5, max_chars_per_page=1200))
        return {"reply": json.dumps(info, ensure_ascii=False, indent=2), "mode": "show"}

    if lower.startswith("search "):
        q = msg[7:].strip()
        data = await status(max_pages=1, max_chars_per_page=800)
        docs = data.get("documents") or []
        hits = _search_previews_in_status(docs, q)
        return {"reply": json.dumps({"query": q, "hits": hits}, ensure_ascii=False, indent=2), "mode": "search"}

    if lower == "cross":
        out = _audit_cross_checks(AuditCrossChecksArgs(auto_discover=True))
        compact = {"groups": out.get("groups"), "issues": out.get("issues"), "required": out.get("required_doc_types")}
        return {"reply": json.dumps(compact, ensure_ascii=False, indent=2), "mode": "cross"}

    if lower.startswith("cross "):
        period = msg[6:].strip()
        out = _audit_cross_checks(AuditCrossChecksArgs(auto_discover=True, period_filter=period))
        compact = {"groups": out.get("groups"), "issues": out.get("issues"), "required": out.get("required_doc_types")}
        return {"reply": json.dumps(compact, ensure_ascii=False, indent=2), "mode": "cross"}

    return {
        "reply": "Try: list | show <index> | search <text> | cross | help",
        "mode": "unknown",
    }


@app.get("/www/chat", response_class=HTMLResponse)
async def chat_page() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>mcp-audidoc chat</title>
    <style>
      body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: #0f1115; color: #e5e7eb; margin: 0; }
      .wrap { max-width: 980px; margin: 0 auto; padding: 18px; }
      .top { display:flex; gap:10px; align-items:center; margin-bottom: 12px; }
      .top a { color: #7dd3fc; text-decoration: none; }
      .top a:hover { text-decoration: underline; }
      h1 { margin: 0; font-size: 18px; flex: 1; }
      .log { background: #151922; border: 1px solid #262b36; border-radius: 12px; padding: 12px; height: 60vh; overflow: auto; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size: 12.5px; }
      .bar { display:flex; gap:10px; margin-top: 12px; }
      input { flex:1; background:#0b0d12; border:1px solid #262b36; color:#e5e7eb; border-radius: 10px; padding: 10px 12px; }
      button { background:#2563eb; border:none; color:white; border-radius: 10px; padding: 10px 14px; cursor:pointer; }
      button.secondary { background:#374151; }
      .hint { opacity:.8; font-size: 12px; margin-top: 10px; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="top">
        <h1>mcp-audidoc · chat</h1>
        <a href="/www/status">status</a>
      </div>
      <div id="log" class="log"></div>
      <div class="bar">
        <input id="msg" placeholder="Try: list | show 1 | search สิงหาคม | help" autocomplete="off" />
        <button id="send">Send</button>
        <button id="clear" class="secondary">Clear</button>
      </div>
      <div class="hint">This is a simple local chat helper (no external LLM). It can list docs, show PDF info, and search text previews.</div>
    </div>

    <script>
      const log = document.getElementById('log');
      const msg = document.getElementById('msg');
      const send = document.getElementById('send');
      const clear = document.getElementById('clear');

      function write(role, text) {
        const prefix = role === 'you' ? '> ' : '';
        log.textContent += `${prefix}${text}\n\n`;
        log.scrollTop = log.scrollHeight;
      }

      async function callChat(message) {
        const r = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ message })
        });
        const data = await r.json();
        if (!r.ok) {
          throw new Error(data?.detail || data?.error || 'chat_failed');
        }
        return data;
      }

      async function doSend() {
        const text = (msg.value || '').trim();
        if (!text) return;
        msg.value = '';
        write('you', text);
        try {
          const out = await callChat(text);
          write('bot', out.reply || JSON.stringify(out));
        } catch (e) {
          write('bot', `error: ${e.message}`);
        }
      }

      send.addEventListener('click', doSend);
      clear.addEventListener('click', () => { log.textContent = ''; });
      msg.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSend();
      });

      (async () => {
        write('bot', 'Type "help" for commands.');
        try {
          const out = await callChat('list');
          write('bot', out.reply || '');
        } catch {}
      })();
    </script>
  </body>
</html>"""


@app.get("/.well-known/mcp.json")
async def well_known() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Document audit MCP provider (missing/mismatched metadata).",
        "capabilities": {"tools": _tool_definitions()},
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": _tool_definitions()}


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args_raw = (payload or {}).get("arguments") or (payload or {}).get("args") or {}

    if tool == "audit_documents":
        args = AuditDocumentsArgs.model_validate(args_raw or {})
        root = Path(AUDIDOC_ROOT).resolve()
        docs: List[Dict[str, Any]] = []
        issues: List[Dict[str, Any]] = []

        for rel in args.paths:
            resolved = _safe_resolve_under_root(rel)
            doc, doc_issues = _audit_single(resolved, args)
            docs.append({"path": str(resolved.relative_to(root)), **doc})
            issues.extend(doc_issues)

        return {"tool": tool, "result": {"documents": docs, "issues": issues}}

    if tool == "audit_pdf_subdocuments":
        args = AuditPdfSubdocumentsArgs.model_validate(args_raw or {})
        resolved = _safe_resolve_under_root(args.path)
        if resolved.suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="not_a_pdf")
        result = _audit_pdf_subdocuments(resolved, args)
        return {"tool": tool, "result": result}

    if tool == "pdf_general_info":
        args = PdfGeneralInfoArgs.model_validate(args_raw or {})
        root = Path(AUDIDOC_ROOT).resolve()
        docs: List[Dict[str, Any]] = []
        for rel in args.paths:
            resolved = _safe_resolve_under_root(rel)
            info = _pdf_general_info_one(resolved, args)
            try:
                rel_out = str(resolved.relative_to(root))
            except Exception:
                rel_out = str(resolved)
            docs.append({"path": rel_out, **info})
        return {"tool": tool, "result": {"documents": docs}}

    if tool == "audit_cross_checks":
        args = AuditCrossChecksArgs.model_validate(args_raw or {})
        result = _audit_cross_checks(args)
        return {"tool": tool, "result": result}

    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data)).model_dump(
        exclude_none=True
    )


@app.post("/mcp")
async def mcp(payload: Dict[str, Any] = Body(...)) -> Any:
    request = JsonRpcRequest.model_validate(payload or {})
    if request.id is None:
        return None

    method = (request.method or "").strip()
    params = request.params or {}

    if method == "initialize":
        return JsonRpcResponse(
            id=request.id,
            result={
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "capabilities": {"tools": {}},
            },
        ).model_dump(exclude_none=True)

    if method in ("tools/list", "list_tools"):
        return JsonRpcResponse(id=request.id, result={"tools": _tool_definitions()}).model_dump(exclude_none=True)

    if method in ("tools/call", "call_tool"):
        tool_name = (params.get("name") or params.get("tool") or "").strip()
        arguments_raw = params.get("arguments") or {}
        if not tool_name:
            return _jsonrpc_error(request.id, -32602, "Missing tool name")

        try:
            if tool_name == "audit_documents":
                args = AuditDocumentsArgs.model_validate(arguments_raw or {})
                root = Path(AUDIDOC_ROOT).resolve()
                docs: List[Dict[str, Any]] = []
                issues: List[Dict[str, Any]] = []

                for rel in args.paths:
                    resolved = _safe_resolve_under_root(rel)
                    doc, doc_issues = _audit_single(resolved, args)
                    docs.append({"path": str(resolved.relative_to(root)), **doc})
                    issues.extend(doc_issues)

                out = {"documents": docs, "issues": issues}
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "audit_cross_checks":
                args = AuditCrossChecksArgs.model_validate(arguments_raw or {})
                out = _audit_cross_checks(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "audit_pdf_subdocuments":
                args = AuditPdfSubdocumentsArgs.model_validate(arguments_raw or {})
                resolved = _safe_resolve_under_root(args.path)
                if resolved.suffix.lower() != ".pdf":
                    raise HTTPException(status_code=400, detail="not_a_pdf")
                out = _audit_pdf_subdocuments(resolved, args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "pdf_general_info":
                args = PdfGeneralInfoArgs.model_validate(arguments_raw or {})
                root = Path(AUDIDOC_ROOT).resolve()
                docs: List[Dict[str, Any]] = []
                for rel in args.paths:
                    resolved = _safe_resolve_under_root(rel)
                    info = _pdf_general_info_one(resolved, args)
                    try:
                        rel_out = str(resolved.relative_to(root))
                    except Exception:
                        rel_out = str(resolved)
                    docs.append({"path": rel_out, **info})
                out = {"documents": docs}
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'")

        except HTTPException as e:
            return _jsonrpc_error(request.id, -32000, str(e.detail), {"status": e.status_code})
        except Exception as e:
            return _jsonrpc_error(request.id, -32000, str(e))

    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
