"""MCP Debug report generation."""
import csv
import io
import json
from datetime import datetime
from .config import REPO_DIR, load_report_config
from .tools import mcp_savings


def generate_savings_report(savings, report_cfg):
    cfg = report_cfg.get("reports", {}).get("savings_table", {})
    columns = cfg.get("columns", [
        {"key": "command", "label": "Command"},
        {"key": "raw_chars", "label": "Raw chars"},
        {"key": "compact_chars", "label": "Compact chars"},
        {"key": "saved_chars", "label": "Saved chars"},
        {"key": "savings_pct_chars", "label": "Char %"},
        {"key": "savings_pct", "label": "Word %"},
    ])
    sort_by = cfg.get("sort", {}).get("by", "savings_pct_chars")
    sort_desc = cfg.get("sort", {}).get("descending", True)
    neg_marker = cfg.get("negative_marker", "")
    include_totals = cfg.get("include_totals", True)

    headers = [c["label"] for c in columns]
    lines = ["# MCP Debug Savings Report", ""]

    for host, data in savings.get("hosts", {}).items():
        lines.append(f"## {host}")
        lines.append("")
        commands = list(data.get("commands", {}).values())
        commands.sort(key=lambda x: x.get(sort_by, 0), reverse=sort_desc)

        table = [headers]
        for cmd in commands:
            row = []
            for col in columns:
                val = cmd.get(col["key"], "")
                if col["key"] in ("savings_pct_chars", "savings_pct") and isinstance(val, (int, float)):
                    val = f"{val:.1f}"
                    if neg_marker and cmd.get(col["key"], 0) < 0:
                        val = f"{val} {neg_marker}".strip()
                row.append(str(val))
            table.append(row)

        if table:
            widths = [max(len(str(r[i])) for r in table) for i in range(len(headers))]
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
            for row in table[1:]:
                lines.append("| " + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(row))) + " |")
            lines.append("")

        if include_totals:
            raw = data.get("raw_chars", 0)
            compact = data.get("compact_chars", 0)
            saved = data.get("saved_chars", 0)
            pct = round(saved / raw * 100, 1) if raw else 0.0
            lines.append(f"**{host} totals**: raw={raw}, compact={compact}, saved={saved} ({pct}%)")
            lines.append("")

    if include_totals:
        total_raw = savings.get("total_raw_chars", 0)
        total_compact = savings.get("total_compact_chars", 0)
        total_saved = savings.get("total_saved_chars", 0)
        total_pct = savings.get("total_savings_pct", 0.0)
        lines.append(f"**Overall totals**: raw={total_raw}, compact={total_compact}, saved={total_saved} ({total_pct}%)")
        lines.append("")

    return "\n".join(lines)


def generate_json_report(savings):
    return json.dumps(savings, indent=2, default=str, sort_keys=False)


def generate_csv_report(savings):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["host", "command", "raw_chars", "compact_chars", "saved_chars", "char_pct", "word_pct"])
    for host, data in savings.get("hosts", {}).items():
        for cmd_name, cmd in data.get("commands", {}).items():
            writer.writerow([
                host,
                cmd_name,
                cmd.get("raw_chars", 0),
                cmd.get("compact_chars", 0),
                cmd.get("saved_chars", 0),
                round(cmd.get("savings_pct_chars", 0), 1),
                round(cmd.get("savings_pct", 0), 1),
            ])
        writer.writerow([
            f"{host} totals",
            "",
            data.get("raw_chars", 0),
            data.get("compact_chars", 0),
            data.get("saved_chars", 0),
            round(data.get("saved_chars", 0) / data.get("raw_chars", 0) * 100, 1) if data.get("raw_chars") else 0.0,
            "",
        ])
    writer.writerow([
        "overall totals",
        "",
        savings.get("total_raw_chars", 0),
        savings.get("total_compact_chars", 0),
        savings.get("total_saved_chars", 0),
        round(savings.get("total_savings_pct", 0.0), 1),
        "",
    ])
    return output.getvalue()


def generate_html_report(savings, report_cfg):
    cfg = report_cfg.get("reports", {}).get("savings_table", {})
    columns = cfg.get("columns", [
        {"key": "command", "label": "Command"},
        {"key": "raw_chars", "label": "Raw chars"},
        {"key": "compact_chars", "label": "Compact chars"},
        {"key": "saved_chars", "label": "Saved chars"},
        {"key": "savings_pct_chars", "label": "Char %"},
        {"key": "savings_pct", "label": "Word %"},
    ])
    sort_by = cfg.get("sort", {}).get("by", "savings_pct_chars")
    sort_desc = cfg.get("sort", {}).get("descending", True)
    include_totals = cfg.get("include_totals", True)

    headers = [c["label"] for c in columns]
    parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\">",
        "<title>MCP Debug Savings Report</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; margin: 2rem; background: #fff; color: #111; }",
        "h1 { font-size: 1.5rem; }",
        "h2 { font-size: 1.2rem; margin-top: 2rem; }",
        "table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.9rem; }",
        "th, td { border: 1px solid #ddd; padding: 0.5rem; text-align: left; }",
        "th { background: #f3f4f6; font-weight: 600; }",
        "tr:nth-child(even) { background: #f9fafb; }",
        ".negative { color: #dc2626; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>MCP Debug Savings Report</h1>",
    ]

    for host, data in savings.get("hosts", {}).items():
        parts.append(f"<h2>{host}</h2>")
        commands = list(data.get("commands", {}).values())
        commands.sort(key=lambda x: x.get(sort_by, 0), reverse=sort_desc)

        parts.append("<table>")
        parts.append("<thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>")
        parts.append("<tbody>")
        for cmd in commands:
            parts.append("<tr>")
            for col in columns:
                val = cmd.get(col["key"], "")
                if col["key"] in ("savings_pct_chars", "savings_pct") and isinstance(val, (int, float)):
                    display = f"{val:.1f}"
                    css = " class=\"negative\"" if val < 0 else ""
                else:
                    display = str(val)
                    css = ""
                display = display.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                parts.append(f"<td{css}>{display}</td>")
            parts.append("</tr>")
        parts.append("</tbody>")
        parts.append("</table>")

        if include_totals:
            raw = data.get("raw_chars", 0)
            compact = data.get("compact_chars", 0)
            saved = data.get("saved_chars", 0)
            pct = round(saved / raw * 100, 1) if raw else 0.0
            parts.append(f"<p><strong>{host} totals</strong>: raw={raw}, compact={compact}, saved={saved} ({pct}%)</p>")

    if include_totals:
        total_raw = savings.get("total_raw_chars", 0)
        total_compact = savings.get("total_compact_chars", 0)
        total_saved = savings.get("total_saved_chars", 0)
        total_pct = savings.get("total_savings_pct", 0.0)
        parts.append(f"<p><strong>Overall totals</strong>: raw={total_raw}, compact={total_compact}, saved={total_saved} ({total_pct}%)</p>")

    parts.extend(["</body>", "</html>"])
    return "\n".join(parts)


def mcp_report(hosts=None, save=False, format="markdown"):
    if hosts is None:
        hosts = []
    savings = mcp_savings(hosts)
    savings["generated"] = datetime.now().isoformat()
    savings["source"] = "mcp_debug"
    report_cfg = load_report_config()
    if format == "json":
        report = generate_json_report(savings)
    elif format == "csv":
        report = generate_csv_report(savings)
    elif format == "html":
        report = generate_html_report(savings, report_cfg)
    else:
        report = generate_savings_report(savings, report_cfg)
    saved_path = None
    if save:
        cfg = (report_cfg.get("reports") or {}).get("savings_table", {})
        template = cfg.get("save_path_template", "reports/mcp-savings-{date}.md")
        filename = template.format(date=datetime.now().strftime("%Y-%m-%d"))
        if format in ("json", "csv", "html") and filename.endswith(".md"):
            filename = f"{filename[:-3]}.{format}"
        path = REPO_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report)
        saved_path = str(path)
    return {
        "ok": savings.get("ok", True),
        "report": report,
        "saved_path": saved_path,
        "format": format,
    }

