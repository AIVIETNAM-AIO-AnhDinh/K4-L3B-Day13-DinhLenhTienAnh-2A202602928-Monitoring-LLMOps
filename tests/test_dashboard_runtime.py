from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import dashboard

END = datetime(2026, 9, 30, 3, 0, 30, tzinfo=timezone.utc)


def _rec(minutes_ago: float, event: str, **fields) -> dict:
    ts = END - timedelta(minutes=minutes_ago)
    return {"ts": ts.isoformat().replace("+00:00", "Z"), "event": event, "service": "api", **fields}


def _write(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "logs.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\nnot json\n", encoding="utf-8")
    return path


def _sent(minutes_ago: float, latency: int, cost: float = 0.002, quality: float = 0.9) -> list[dict]:
    return [
        _rec(minutes_ago, "request_received"),
        _rec(
            minutes_ago,
            "response_sent",
            latency_ms=latency,
            ttft_ms=50,
            tokens_in=30,
            tokens_out=100,
            cost_usd=cost,
            quality_score=quality,
            tool_success=True,
        ),
    ]


def test_compute_matches_dashboard_contract(tmp_path: Path) -> None:
    records = []
    for latency in (100, 200, 300, 400):
        records += _sent(1, latency)
    records += [
        _rec(2, "request_received"),
        _rec(2, "request_failed", error_type="RuntimeError", tool_success=False),
    ]
    records += _sent(90, 99_999)  # outside the 60-minute window

    cfg = dashboard.load_config()
    data = dashboard.compute(dashboard.load_records(_write(tmp_path, records)), cfg, END)
    total = data["total"]

    assert total["count"] == 5
    assert total["p50"] == 200 and total["p99"] == 400
    assert total["ttft_p95"] == 50
    assert total["error_rate_pct"] == 20.0
    assert total["count_by_value"] == {"RuntimeError": 1}
    assert total["tool_success_rate_pct"] == 80.0
    assert total["cost_usd"] == 0.008
    assert (total["tokens_in"], total["tokens_out"]) == (120, 400)
    assert total["mean_quality"] == 0.9
    assert len(data["per_minute"]) == cfg["time_range_minutes"]
    assert sum(b["count"] for b in data["per_minute"]) == 5


def test_threshold_status_uses_panel_operator(tmp_path: Path) -> None:
    cfg = dashboard.load_config()
    panels = {p["id"]: p for p in cfg["panels"]}
    records = _sent(1, 4000, quality=0.5)
    data = dashboard.compute(dashboard.load_records(_write(tmp_path, records)), cfg, END)

    assert dashboard.threshold_status(panels["latency"], data["total"]) == ("breach", 4000.0)
    assert dashboard.threshold_status(panels["quality"], data["total"]) == ("breach", 0.5)
    assert dashboard.threshold_status(panels["cost"], data["total"])[0] == "ok"


def test_empty_window_reports_no_data(tmp_path: Path) -> None:
    cfg = dashboard.load_config()
    data = dashboard.compute([], cfg, END)
    panels = {p["id"]: p for p in cfg["panels"]}

    assert dashboard.threshold_status(panels["latency"], data["total"]) == ("no-data", None)


def test_render_has_six_panels_units_thresholds_and_escapes_text(tmp_path: Path) -> None:
    records = _sent(1, 250)
    records.append(_rec(1, "request_failed", error_type="<script>x</script>"))
    page = dashboard.build(_write(tmp_path, records), anchor="latest", refresh=True)

    cfg = dashboard.load_config()
    for panel in cfg["panels"]:
        assert panel["title"] in page
        assert panel["unit"] in page
    assert page.count('class="threshold"') == 3  # latency, errors, quality draw per-minute limits
    assert page.count("threshold ≤") + page.count("threshold ≥") == 6
    assert 'http-equiv="refresh" content="30"' in page
    assert "Last 60 min" in page
    assert "<script>x</script>" not in page
