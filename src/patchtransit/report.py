"""Dependency-free, standalone evidence report renderer."""

from __future__ import annotations

import html
import json
import os
import pathlib
import tempfile
from typing import Any


def atomic_write(path: pathlib.Path, contents: str) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def json_report(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def html_report(result: dict[str, Any]) -> str:
    e = lambda x: html.escape(str(x), quote=True)
    badge = e(result["verdict"]).upper()
    if result["verdict"] == "regression":
        color = "#ff8a8a"
    elif result["verdict"] in ("identical", "improvement"):
        color = "#4cebb7"
    else:
        color = "#fdbe65"
    rows = "\n".join(
        f"<tr><td><code>{e(item['path'])}</code></td>"
        f"<td>{e(item['change'])}</td><td><small>{e((item['before_sha256'] or '-')[:12])}</small></td>"
        f"<td><small>{e((item['after_sha256'] or '-')[:12])}</small></td></tr>"
        for item in result["changes"]
    )
    if not rows:
        rows = '<tr><td colspan="4" class="empty">No effective changes between patches.</td></tr>'
    checks = result.get("checks")
    checks_view = ""
    if checks:
        before, after = checks["old"], checks["new"]
        checks_view = (
            f'<section><h2>Execution evidence</h2><p class="muted">'
            f"Command: <code>{e(' '.join(checks['command']))}</code></p>"
            f'<div class="columns"><div class="metric">OLD<p>Exit {e(before.get("exit_code"))}</p>'
            f"<small>{e(before.get('duration_ms'))} ms</small></div>"
            f'<div class="metric">NEW<p>Exit {e(after.get("exit_code"))}</p>'
            f"<small>{e(after.get('duration_ms'))} ms</small></div></div></section>"
        )
    colored_diff = []
    for line in result["effective_diff"].splitlines():
        cls = ""
        if line.startswith("+") and not line.startswith("+++ "):
            cls = "added"
        elif line.startswith("-") and not line.startswith("--- "):
            cls = "removed"
        elif line.startswith("@@ "):
            cls = "hunk"
        elif line.startswith(("--- ", "+++ ")):
            cls = "file"
        colored_diff.append(f'<span class="{cls}">{e(line)}</span>')
    rendered_diff = "\n".join(colored_diff) if colored_diff else "No changed lines."
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark"><title>PatchTransit · Evidence</title>
<style>
:root{{--bg:#0c111b;--surface:#151d2b;--stroke:#28364a;--ink:#e5edf8;--muted:#93a6bb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 system-ui,-apple-system,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:46px 24px 100px}}header{{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;flex-wrap:wrap}}
h1{{font-size:37px;letter-spacing:-.055em;margin:0}}h2{{font-size:20px;margin:0 0 20px;letter-spacing:-.03em}}p{{margin:9px 0}}.lead{{color:var(--muted);max-width:600px}}.muted,small{{color:var(--muted)}}.brand{{color:#90a9ff}}
.badge{{border:1px solid {color};color:{color};padding:7px 13px;border-radius:100px;font:700 12px ui-monospace,monospace;letter-spacing:.12em}}
section{{margin-top:32px;padding:25px;background:var(--surface);border:1px solid var(--stroke);border-radius:16px}}
.columns{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:15px}}
.metric{{background:#101725;padding:17px 20px;border:1px solid var(--stroke);border-radius:12px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}}
.metric p{{color:var(--ink);font-size:26px;font-weight:700;margin:0}}code,pre{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}}code{{font-size:12px;overflow-wrap:anywhere}}
table{{border-collapse:collapse;width:100%;table-layout:fixed}}th,td{{text-align:left;padding:12px;border-bottom:1px solid var(--stroke);overflow-wrap:anywhere}}th{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.09em}}th:first-child{{width:53%}}.empty{{text-align:center;color:var(--muted);padding:30px}}
pre{{font-size:12px;line-height:1.55;overflow:auto;max-height:640px;background:#0b111b;border:1px solid var(--stroke);padding:19px;border-radius:12px}}
pre span{{display:block;min-height:1.5em;white-space:pre}}pre .added{{color:#91e6b4;background:#15342488}}pre .removed{{color:#ffa19d;background:#3c1b2788}}pre .hunk{{color:#9db8ff}}pre .file{{color:#d4b9ff}}
footer{{padding:28px 0;color:var(--muted);font-size:12px}}@media(max-width:600px){{h1{{font-size:29px}}section{{padding:15px}}main{{padding:28px 14px}}}}
</style></head><body><main><header><div><p class="brand">◈ PATCHTRANSIT / 01</p><h1>Effective change report</h1><p class="lead">What did the new patch actually change compared with the previous one? Two independent candidate trees, one common base.</p></div>
<span class="badge">{badge}</span></header>
<section><h2>Verified facts</h2><div class="columns"><div class="metric">Effective changed files<p>{len(result["changes"])}</p></div>
<div class="metric">Old patch / hunks<p>{e(result["old_patch"]["hunks"])}</p></div>
<div class="metric">New patch / hunks<p>{e(result["new_patch"]["hunks"])}</p></div></div>
<p class="muted">Base Git tree: <code>{e(result["base_tree"])}</code></p>
<p class="muted">Old output: <code>{e(result["old_state_sha256"])}</code></p>
<p class="muted">New output: <code>{e(result["new_state_sha256"])}</code></p></section>
{checks_view}
<section><h2>Changed files</h2><table><thead><tr><th>Path</th><th>Status</th><th>Before</th><th>After</th></tr></thead><tbody>{rows}</tbody></table></section>
<section><h2>Effective diff</h2><p class="muted">Computed from the resulting files, not by subtracting raw patch text.</p>
<pre aria-label="Effective diff">{rendered_diff}</pre></section><footer>Generated locally by PatchTransit. Reproducible evidence ≠ a guarantee of correctness. Review code and execution results independently.</footer></main></body></html>"""
