"""Trend report: is the number of flaky tests going up or down?

Renders a self-contained HTML page (inline SVG, no JavaScript or CDN) or plain text.
"""

from __future__ import annotations

from html import escape

from .history import HistoryStore, Snapshot, SnapshotDiff

TOP_TESTS = 10


def _direction(delta: int) -> str:
    return "▲ up" if delta > 0 else "▼ down" if delta < 0 else "■ unchanged"


def summary_line(prev: Snapshot | None, cur: Snapshot) -> str:
    if prev is None:
        return f"{cur.flaky_count} flaky test(s) (first snapshot, nothing to compare)."
    delta = cur.flaky_count - prev.flaky_count
    return (f"{cur.flaky_count} flaky test(s), {_direction(delta)} "
            f"({delta:+d}) vs. previous snapshot ({prev.flaky_count}).")


def render_text(store: HistoryStore, source: str | None = None) -> str:
    snaps = store.snapshots(source)
    if not snaps:
        return "No snapshots in history yet. Run `analyze --save-history` first."
    lines = ["Date (UTC)            Tests  Flaky   Rate", "-" * 40]
    for s in snaps:
        lines.append(f"{s.run_at[:19].replace('T', ' ')}  {s.tests_total:5d}  "
                     f"{s.flaky_count:5d}  {s.flaky_rate:5.1%}")
    prev = snaps[-2] if len(snaps) > 1 else None
    lines += ["", summary_line(prev, snaps[-1])]
    if prev:
        d = store.diff(prev.id, snaps[-1].id)
        lines += [f"  new:   {', '.join(d.new) or '-'}",
                  f"  fixed: {', '.join(d.fixed) or '-'}"]
    return "\n".join(lines)


def _line_chart(values: list[float], labels: list[str], width=720, height=220,
                pct: bool = False) -> str:
    """Minimal inline-SVG line chart."""
    pad_l, pad_r, pad_t, pad_b = 44, 16, 14, 28
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    top = max(values) or 1
    top = top * 1.15
    n = len(values)

    def x(i: int) -> float:
        return pad_l + (w / 2 if n == 1 else i * w / (n - 1))

    def y(v: float) -> float:
        return pad_t + h - (v / top) * h

    fmt = (lambda v: f"{v:.0%}") if pct else (lambda v: f"{v:g}")
    grid = "".join(
        f'<line x1="{pad_l}" x2="{pad_l + w}" y1="{y(top * f):.1f}" y2="{y(top * f):.1f}" '
        f'class="grid"/><text x="{pad_l - 6}" y="{y(top * f) + 4:.1f}" class="axis" '
        f'text-anchor="end">{fmt(top * f)}</text>' for f in (0, 0.5, 1))
    points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3.5" class="dot">'
        f'<title>{escape(labels[i])}: {fmt(v)}</title></circle>'
        for i, v in enumerate(values))
    step = max(1, n // 6)
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{height - 8}" class="axis" text-anchor="middle">'
        f'{escape(labels[i])}</text>' for i in range(0, n, step))
    return (f'<svg viewBox="0 0 {width} {height}" role="img">{grid}'
            f'<polyline points="{points}" class="line"/>{dots}{ticks}</svg>')


def _sparkline(values: list[float | None], width=110, height=26) -> str:
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if not pts:
        return ""
    n, top = len(values), max(v for _, v in pts) or 1

    def x(i: int) -> float:
        return 2 + (width - 4) / 2 if n == 1 else 2 + i * (width - 4) / (n - 1)

    coords = " ".join(f"{x(i):.1f},{height - 3 - (v / top) * (height - 6):.1f}"
                      for i, v in pts)
    return f'<svg viewBox="0 0 {width} {height}" class="spark"><polyline points="{coords}"/></svg>'


def _names(items: tuple[str, ...]) -> str:
    return "".join(f"<li><code>{escape(n)}</code></li>" for n in items) or "<li>none</li>"


_CSS = """
:root{--bg:#fff;--fg:#1f2430;--muted:#6b7280;--card:#f6f7fb;--line:#4f46e5;
--up:#c0392b;--down:#1e8e5a;--grid:#d9dce6}
@media(prefers-color-scheme:dark){:root{--bg:#14161d;--fg:#e6e8ef;--muted:#9aa1b2;
--card:#1e222c;--line:#8b9cff;--up:#ff7b6b;--down:#4cd59a;--grid:#343a48}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);
max-width:860px;margin:0 auto;padding:24px 16px}
h1{font-size:1.4rem;margin:0 0 4px}h2{font-size:1.05rem;margin:28px 0 8px}
.muted{color:var(--muted)}.card{background:var(--card);border-radius:10px;padding:14px 16px}
.verdict{font-size:1.15rem;font-weight:600}.up{color:var(--up)}.down{color:var(--down)}
svg{width:100%;height:auto}.grid{stroke:var(--grid);stroke-width:1}
.axis{fill:var(--muted);font-size:11px}.line{fill:none;stroke:var(--line);stroke-width:2}
.dot{fill:var(--line)}.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:600px){.cols{grid-template-columns:1fr}}
ul{margin:4px 0 0;padding-left:18px}table{width:100%;border-collapse:collapse}
td,th{padding:6px 8px;text-align:left;border-bottom:1px solid var(--grid)}
.spark{width:110px;height:26px}.spark polyline{fill:none;stroke:var(--line);stroke-width:1.5}
code{font-size:.85em;word-break:break-all}
"""


def render_html(store: HistoryStore, source: str | None = None) -> str:
    snaps = store.snapshots(source)
    if not snaps:
        body = "<p>No snapshots in history yet. Run <code>analyze --save-history</code>.</p>"
        return _page(body)

    cur, prev = snaps[-1], (snaps[-2] if len(snaps) > 1 else None)
    labels = [s.run_at[:10] for s in snaps]
    delta = cur.flaky_count - prev.flaky_count if prev else 0
    css_class = "up" if delta > 0 else "down" if delta < 0 else "muted"
    diff = store.diff(prev.id, cur.id) if prev else SnapshotDiff((), ())

    worst = sorted(store.flaky_names(cur.id))
    ids = [s.id for s in snaps]
    hist = store.test_history(ids, worst)
    worst.sort(key=lambda n: -(hist[n][-1] or 0))
    rows = "".join(
        f"<tr><td><code>{escape(n)}</code></td><td>{(hist[n][-1] or 0):.0%}</td>"
        f"<td>{_sparkline(hist[n])}</td></tr>" for n in worst[:TOP_TESTS])

    body = f"""
<h1>Flaky tests trend</h1>
<p class="muted">{len(snaps)} snapshot(s) · last: {escape(cur.run_at[:19].replace('T', ' '))} UTC
{f' · source: {escape(source)}' if source else ''}</p>
<div class="card"><span class="verdict {css_class}">{escape(summary_line(prev, cur))}</span>
<div class="muted">Flaky rate now: {cur.flaky_rate:.1%} of {cur.tests_total} analyzed tests
(threshold {cur.threshold:g}, min commits {cur.min_commits}).</div></div>
<h2>Flaky tests over time</h2>{_line_chart([float(s.flaky_count) for s in snaps], labels)}
<h2>Flaky rate over time</h2>{_line_chart([s.flaky_rate for s in snaps], labels, pct=True)}
<div class="cols"><div class="card"><strong>New since last snapshot</strong>
<ul>{_names(diff.new)}</ul></div><div class="card"><strong>Fixed since last snapshot</strong>
<ul>{_names(diff.fixed)}</ul></div></div>
<h2>Worst tests now (score history)</h2>
<table><tr><th>Test</th><th>Score</th><th>Trend</th></tr>{rows or
'<tr><td colspan="3">No flaky tests 🎉</td></tr>'}</table>"""
    return _page(body)


def _page(body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Flaky tests trend</title><style>{_CSS}</style></head>'
            f'<body>{body}</body></html>')
