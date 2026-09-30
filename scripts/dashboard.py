"""Runtime dashboard for the six panels in config/dashboard.yaml.

Reads data/logs.jsonl on every page load, so it always shows live data:

    python scripts/dashboard.py                    # serve on http://127.0.0.1:8050
    python scripts/dashboard.py --anchor latest    # window ends at the newest log line
    python scripts/dashboard.py --out dash.html    # write a static snapshot and exit

Only the Python standard library + PyYAML are used; charts are inline SVG.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.metrics import percentile  # same percentile as the /metrics endpoint

CONFIG_PATH = REPO_ROOT / "config" / "dashboard.yaml"
LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"


# --------------------------------------------------------------------------- data


def load_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["dashboard"]


def load_records(path: Path = LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            rec["_ts"] = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        records.append(rec)
    return records


def _pct(num: int, den: int) -> float | None:
    return round(num / den * 100, 2) if den else None


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _window_stats(recs: list[dict]) -> dict[str, Any]:
    """Every aggregation named in config/dashboard.yaml, over one slice of records."""
    received = [r for r in recs if r.get("event") == "request_received"]
    sent = [r for r in recs if r.get("event") == "response_sent"]
    failed = [r for r in recs if r.get("event") == "request_failed"]
    tool = [r for r in recs if r.get("tool_success") is not None]
    lat = [r["latency_ms"] for r in sent if r.get("latency_ms") is not None]
    ttft = [r["ttft_ms"] for r in sent if r.get("ttft_ms") is not None]
    quality = [r["quality_score"] for r in sent if r.get("quality_score") is not None]
    return {
        "p50": percentile(lat, 50) if lat else None,
        "p95": percentile(lat, 95) if lat else None,
        "p99": percentile(lat, 99) if lat else None,
        "ttft_p95": percentile(ttft, 95) if ttft else None,
        "count": len(received),
        "error_rate_pct": _pct(len(failed), len(received)),
        "count_by_value": dict(Counter(r.get("error_type") or "unknown" for r in failed)),
        "tool_success_rate_pct": _pct(sum(1 for r in tool if r["tool_success"]), len(tool)),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in sent), 6),
        "tokens_in": sum(r.get("tokens_in") or 0 for r in sent),
        "tokens_out": sum(r.get("tokens_out") or 0 for r in sent),
        "mean_quality": _round(mean(quality), 4) if quality else None,
    }


def compute(records: list[dict], cfg: dict, end: datetime) -> dict[str, Any]:
    minutes = cfg["time_range_minutes"]
    end = end.replace(second=0, microsecond=0) + timedelta(minutes=1)
    start = end - timedelta(minutes=minutes)
    in_window = [r for r in records if start <= r["_ts"] < end]

    buckets: list[list[dict]] = [[] for _ in range(minutes)]
    for r in in_window:
        buckets[int((r["_ts"] - start).total_seconds() // 60)].append(r)

    total = _window_stats(in_window)
    active_minutes = sum(1 for b in buckets if any(r.get("event") == "request_received" for r in b))
    total["rate_per_minute"] = round(total["count"] / active_minutes, 2) if active_minutes else 0.0
    total["total"] = total["cost_usd"]
    total["sum_by_field"] = max(total["tokens_in"], total["tokens_out"])
    total["mean"] = total["mean_quality"]

    return {
        "start": start,
        "end": end,
        "records": len(in_window),
        "total": total,
        "per_minute": [_window_stats(b) for b in buckets],
    }


def threshold_status(panel: dict, total: dict) -> tuple[str, float | None]:
    th = panel["threshold"]
    value = total.get(th["aggregation"])
    if value is None:
        return "no-data", None
    ok = value <= th["value"] if th["operator"] == "lte" else value >= th["value"]
    return ("ok" if ok else "breach"), value


# --------------------------------------------------------------------------- charts

W, H = 560, 190
PAD_L, PAD_R, PAD_T, PAD_B = 48, 64, 12, 26


def _nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * exp:
            return step * exp
    return 10 * exp


def _fmt(value: float | None, unit: str = "") -> str:
    if value is None:
        return "–"
    if unit == "usd":
        return f"${value:,.4f}"
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "score_0_to_1":
        return f"{value:.2f}"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.1f}"
    return f"{int(value):,}"


def _chart(
    kind: str,
    series: list[tuple[str, int, list[float | None]]],
    labels: list[str],
    unit: str,
    threshold: float | None,
    y_max: float | None = None,
) -> str:
    """kind = 'line' | 'bar'. series = [(name, slot, values per bucket)]."""
    n = len(labels)
    values = [v for _, _, vals in series for v in vals if v is not None]
    top = y_max or _nice_max(max(values + [threshold or 0, 0]) * 1.1)
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    x = lambda i: PAD_L + (i + 0.5) * iw / n  # noqa: E731
    y = lambda v: PAD_T + ih - (v / top) * ih  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" class="chart">']

    for k in range(6):  # hairline grid + y ticks
        v = top * k / 5
        out.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        out.append(f'<text class="tick" x="{PAD_L - 6}" y="{y(v) + 3:.1f}" text-anchor="end">{f"{v:.4f}" if unit == "usd" else _fmt(v, unit)}</text>')
    out.append(f'<line class="axis" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    for i in range(0, n, 10):
        out.append(f'<text class="tick" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{labels[i]}</text>')

    if kind == "bar":
        group_w = iw / n
        bar_w = max(2.0, (group_w - 2) / len(series) - 1)
        for s_idx, (name, slot, vals) in enumerate(series):
            for i, v in enumerate(vals):
                if not v:
                    continue
                bx = PAD_L + i * group_w + 1 + s_idx * (bar_w + 1)
                out.append(
                    f'<rect class="s{slot}" x="{bx:.1f}" y="{y(v):.1f}" width="{bar_w:.1f}" '
                    f'height="{y(0) - y(v):.1f}" rx="{min(2, bar_w / 2):.1f}"/>'
                )
    else:
        for name, slot, vals in series:
            path, pen_down = [], False
            for i, v in enumerate(vals):
                if v is None:
                    pen_down = False
                    continue
                path.append(f'{"L" if pen_down else "M"}{x(i):.1f},{y(v):.1f}')
                pen_down = True
            out.append(f'<path class="line s{slot}" d="{" ".join(path)}"/>')
            for i, v in enumerate(vals):
                if v is not None:
                    out.append(f'<circle class="dot s{slot}" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4"/>')

    if threshold is not None:  # dashed = threshold, never a gridline
        out.append(f'<line class="threshold" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(threshold):.1f}" y2="{y(threshold):.1f}"/>')
        out.append(f'<text class="th-label" x="{PAD_L + 4}" y="{y(threshold) - 4:.1f}">limit {_fmt(threshold, unit)}</text>')

    # Direct label at each series' last point (selective, not every point),
    # pushed apart vertically so overlapping series stay readable.
    ends = []
    for name, _, vals in series:
        last = next((i for i in range(n - 1, -1, -1) if vals[i] is not None), None)
        if last is not None and kind == "line":
            ends.append([y(vals[last]) + 3, x(last) + 8, name])
    ends.sort(key=lambda e: e[0], reverse=True)
    for prev, cur in zip(ends, ends[1:]):
        cur[0] = min(cur[0], prev[0] - 11)
    for label_y, label_x, name in ends:
        out.append(f'<text class="direct" x="{label_x:.1f}" y="{label_y:.1f}">{html.escape(name)}</text>')

    # One hover column per minute: crosshair + tooltip listing every series.
    for i in range(n):
        rows = [(name, slot, vals[i]) for name, slot, vals in series]
        if all(v is None for _, _, v in rows) or (kind == "bar" and not any(v for _, _, v in rows)):
            continue
        payload = html.escape(json.dumps({"t": labels[i], "rows": [[nm, sl, _fmt(v, unit)] for nm, sl, v in rows]}))
        out.append(
            f'<rect class="hit" tabindex="0" data-x="{x(i):.1f}" data-tip="{payload}" '
            f'x="{PAD_L + i * iw / n:.1f}" y="{PAD_T}" width="{iw / n:.1f}" height="{ih}"/>'
        )
    out.append(f'<line class="crosshair" x1="0" x2="0" y1="{PAD_T}" y2="{PAD_T + ih}" visibility="hidden"/>')
    out.append("</svg>")
    return "".join(out)


def _legend(series: list[tuple[str, int, Any]], kind: str) -> str:
    if len(series) < 2:
        return ""
    key = "key-line" if kind == "line" else "key-rect"
    return '<div class="legend">' + "".join(
        f'<span><i class="{key} s{slot}"></i>{html.escape(name)}</span>' for name, slot, _ in series
    ) + "</div>"


def _table(series: list[tuple[str, int, list]], labels: list[str], unit: str) -> str:
    head = "".join(f"<th>{html.escape(n)}</th>" for n, _, _ in series)
    rows = [
        "<tr><td>" + labels[i] + "</td>" + "".join(f"<td>{_fmt(v[i], unit)}</td>" for _, _, v in series) + "</tr>"
        for i in range(len(labels))
        if any(v[i] not in (None, 0) for _, _, v in series)
    ]
    return (
        f'<details><summary>Table view</summary><table><thead><tr><th>minute</th>{head}</tr></thead>'
        f'<tbody>{"".join(rows) or "<tr><td colspan=9>no data</td></tr>"}</tbody></table></details>'
    )


# --------------------------------------------------------------------------- page


def render_html(data: dict, cfg: dict, source: Path, refresh: bool) -> str:
    panels = {p["id"]: p for p in cfg["panels"]}
    local = datetime.now().astimezone().tzinfo
    labels = [
        (data["start"] + timedelta(minutes=i)).astimezone(local).strftime("%H:%M")
        for i in range(cfg["time_range_minutes"])
    ]
    pm, total = data["per_minute"], data["total"]
    col = lambda key: [b[key] for b in pm]  # noqa: E731

    specs = {
        "latency": ("line", [("P50", 1, col("p50")), ("P95", 2, col("p95")), ("P99", 3, col("p99")), ("TTFT P95", 4, col("ttft_p95"))], None,
                    [("P50", total["p50"]), ("P95", total["p95"]), ("P99", total["p99"]), ("TTFT P95", total["ttft_p95"])]),
        "traffic": ("bar", [("requests", 1, col("count"))], None,
                    [("requests", total["count"]), ("avg / active min", total["rate_per_minute"])]),
        "errors": ("line", [("error rate", 1, col("error_rate_pct"))], None,
                   [("error rate", total["error_rate_pct"]), ("retrieval success", total["tool_success_rate_pct"])]),
        "cost": ("bar", [("cost / min", 1, col("cost_usd"))], None,
                 [("total", total["cost_usd"]), ("avg / request", (total["cost_usd"] / total["count"]) if total["count"] else None)]),
        "tokens": ("bar", [("input", 1, col("tokens_in")), ("output", 2, col("tokens_out"))], None,
                   [("input total", total["tokens_in"]), ("output total", total["tokens_out"])]),
        "quality": ("line", [("mean quality", 1, col("mean_quality"))], 1.0,
                    [("mean", total["mean_quality"])]),
    }

    cards = []
    for pid in ("latency", "traffic", "errors", "cost", "tokens", "quality"):
        panel = panels[pid]
        kind, series, y_max, stats = specs[pid]
        unit = panel["unit"]
        th = panel["threshold"]
        # Per-minute thresholds are only drawn where the per-minute series is the thresholded quantity.
        th_line = th["value"] if pid in ("latency", "errors", "quality") else None
        status, value = threshold_status(panel, total)
        icon = {"ok": "✓", "breach": "▲", "no-data": "–"}[status]
        op = "≤" if th["operator"] == "lte" else "≥"
        stat_unit = "percent" if pid == "errors" else unit
        stat_html = "".join(
            f'<div class="stat"><b>{_fmt(v, "usd" if pid == "cost" else stat_unit)}</b><span>{html.escape(k)}</span></div>'
            for k, v in stats
        )
        extra = ""
        if pid == "errors":
            breakdown = ", ".join(f"{html.escape(k)}: {v}" for k, v in total["count_by_value"].items()) or "none"
            extra = f'<p class="note">Errors by type: {breakdown}</p>'
        cards.append(
            f'<section class="card"><header><h2>{html.escape(panel["title"])}</h2>'
            f'<span class="unit">{html.escape(unit)}</span></header>'
            f'<div class="stats">{stat_html}</div>'
            f'<p class="status {status}"><span aria-hidden="true">{icon}</span> '
            f'{th["aggregation"]} = {_fmt(value, stat_unit if pid != "cost" else "usd")} '
            f'(threshold {op} {_fmt(th["value"], stat_unit if pid != "cost" else "usd")}) — '
            f'{"within threshold" if status == "ok" else "BREACH" if status == "breach" else "no data"}</p>'
            f'{_legend(series, kind)}{_chart(kind, series, labels, stat_unit, th_line, y_max)}{extra}'
            f'{_table(series, labels, stat_unit)}</section>'
        )

    meta = f'<meta http-equiv="refresh" content="{cfg["refresh_seconds"]}">' if refresh else ""
    fmt = lambda d: d.astimezone(local).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    return PAGE.format(
        meta=meta,
        title=html.escape(cfg["title"]),
        range=f'Last {cfg["time_range_minutes"]} min · {fmt(data["start"])} → {fmt(data["end"])} ({local})',
        refresh=f'auto-refresh {cfg["refresh_seconds"]}s' if refresh else "static snapshot",
        source=html.escape(str(source.relative_to(REPO_ROOT) if source.is_relative_to(REPO_ROOT) else source)),
        records=data["records"],
        generated=datetime.now().astimezone().strftime("%H:%M:%S"),
        cards="".join(cards),
    )


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{meta}
<title>Day 13 Dashboard</title>
<style>
:root{{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;
--good:#0ca30c;--critical:#d03b3b}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500}}}}
:root[data-theme="dark"]{{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;
--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1240px;margin:0 auto;padding:20px 16px}}h1{{font-size:20px;margin:0 0 4px}}
.bar{{display:flex;flex-wrap:wrap;gap:6px 16px;color:var(--ink2);font-size:13px;margin-bottom:16px}}.bar b{{color:var(--ink)}}
.grid6{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:16px}}
.card{{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px 16px;min-width:0}}
.card header{{display:flex;justify-content:space-between;align-items:baseline;gap:8px}}h2{{font-size:15px;margin:0}}
.unit{{color:var(--muted);font-size:12px}}.stats{{display:flex;flex-wrap:wrap;gap:4px 20px;margin:8px 0 4px}}
.stat b{{display:block;font-size:20px;font-weight:600}}.stat span{{color:var(--ink2);font-size:12px}}
.status{{font-size:12px;margin:4px 0 6px;color:var(--ink2)}}.status.ok span{{color:var(--good)}}
.status.breach{{color:var(--critical);font-weight:600}}.legend{{display:flex;gap:14px;font-size:12px;color:var(--ink2)}}
.legend span{{display:inline-flex;align-items:center;gap:6px}}.key-line{{width:14px;height:2px;border-radius:1px}}
.key-rect{{width:10px;height:10px;border-radius:2px}}
.chart{{width:100%;height:auto;display:block;overflow:visible}}.grid{{stroke:var(--grid);stroke-width:1}}.axis{{stroke:var(--axis)}}
.tick,.th-label,.direct{{fill:var(--muted);font-size:10px;font-variant-numeric:tabular-nums}}.direct{{fill:var(--ink2)}}
.th-label{{fill:var(--critical)}}.threshold{{stroke:var(--critical);stroke-width:1.5;stroke-dasharray:5 4}}
.line{{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}}.dot{{stroke:var(--surface);stroke-width:2}}
.s1{{stroke:var(--s1);fill:var(--s1);background:var(--s1)}}.s2{{stroke:var(--s2);fill:var(--s2);background:var(--s2)}}
.s3{{stroke:var(--s3);fill:var(--s3);background:var(--s3)}}.s4{{stroke:var(--s4);fill:var(--s4);background:var(--s4)}}
.line.s1,.line.s2,.line.s3,.line.s4{{fill:none}}rect.s1,rect.s2{{stroke:none}}
.hit{{fill:transparent;cursor:crosshair;outline:none}}.crosshair{{stroke:var(--ink2);stroke-width:1;pointer-events:none}}
.note{{font-size:12px;color:var(--ink2);margin:6px 0 0}}details{{margin-top:6px;font-size:12px;color:var(--ink2)}}
table{{border-collapse:collapse;margin-top:6px;font-variant-numeric:tabular-nums}}td,th{{padding:2px 10px 2px 0;text-align:right}}
td:first-child,th:first-child{{text-align:left}}
#tip{{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--ring);border-radius:8px;
padding:6px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.15);display:none;z-index:9}}
#tip .row{{display:flex;align-items:center;gap:6px}}#tip b{{font-size:13px}}#tip .t{{color:var(--muted)}}
</style></head><body><main>
<h1>{title}</h1>
<div class="bar"><span>🕒 <b>{range}</b></span><span>{refresh}</span><span>source <b>{source}</b> · {records} records in window</span><span>rendered {generated}</span></div>
<div class="grid6">{cards}</div></main>
<div id="tip" role="tooltip"></div>
<script>
const tip=document.getElementById('tip');
function show(e){{const r=e.currentTarget,d=JSON.parse(r.dataset.tip),svg=r.ownerSVGElement,c=svg.querySelector('.crosshair');
c.setAttribute('x1',r.dataset.x);c.setAttribute('x2',r.dataset.x);c.setAttribute('visibility','visible');
tip.replaceChildren();const t=document.createElement('div');t.className='t';t.textContent=d.t;tip.append(t);
for(const [name,slot,val] of d.rows){{const row=document.createElement('div');row.className='row';
const k=document.createElement('i');k.className='key-line s'+slot;const b=document.createElement('b');b.textContent=val;
const n=document.createElement('span');n.textContent=name;row.append(k,b,n);tip.append(row);}}
tip.style.display='block';const bb=(e.clientX!==undefined&&e.type!=='focus')?{{x:e.clientX,y:e.clientY}}:r.getBoundingClientRect();
tip.style.left=Math.min((bb.x??bb.left)+14,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=((bb.y??bb.top)+14)+'px';}}
function hide(e){{tip.style.display='none';e.currentTarget.ownerSVGElement.querySelector('.crosshair').setAttribute('visibility','hidden');}}
for(const h of document.querySelectorAll('.hit')){{h.addEventListener('pointermove',show);h.addEventListener('focus',show);
h.addEventListener('pointerleave',hide);h.addEventListener('blur',hide);}}
</script></body></html>"""


# --------------------------------------------------------------------------- entry


def build(log_path: Path, anchor: str, refresh: bool) -> str:
    cfg = load_config()
    records = load_records(log_path)
    if anchor == "latest" and records:
        end = max(r["_ts"] for r in records)
    else:
        end = datetime.now(timezone.utc)
    return render_html(compute(records, cfg, end), cfg, log_path, refresh)


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 13 runtime dashboard (6 panels)")
    parser.add_argument("--logs", type=Path, default=LOG_PATH)
    parser.add_argument("--anchor", choices=["now", "latest"], default="now",
                        help="window end: current time, or the newest log line (for replaying old logs)")
    parser.add_argument("--out", type=Path, help="write one static HTML snapshot and exit")
    parser.add_argument("--port", type=int, default=8050)
    args = parser.parse_args()

    if args.out:
        args.out.write_text(build(args.logs, args.anchor, refresh=False), encoding="utf-8")
        print(f"wrote {args.out}")
        return 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            body = build(args.logs, args.anchor, refresh=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: Any) -> None:
            pass

    print(f"Dashboard on http://127.0.0.1:{args.port}  (source {args.logs}, Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
