"""CSV, HTML and heatmap outputs, plus the signal log."""
from __future__ import annotations

import base64
import csv
import datetime as dt
import html
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

CMAP = LinearSegmentedColormap.from_list("div", ["#eb6834", "#f6f5f1", "#2a78d6"])
plt.rcParams.update({"text.parse_math": False, "font.size": 9})

CSV_COLS = ["group", "rank", "ticker", "name", "model", "sector", "period", "price", "price_ccy", "price_date", "oe_rep", "oe", "nc",
            "v_low", "v_high", "nav", "coverage_lo", "coverage_hi", "margin_of_safety", "pe", "primary_metal", "implied_metal_hi",
            "implied_growth", "cost_ratio", "zone", "put_level", "call_level", "stale", "stale_reason"]


def _fmt(x, nd=2):
    if x is None or x == "":
        return ""
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def write_csv(vals, grow, path: Path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for grp, rows in (("metals_energy", vals), ("growth", grow)):
            for r in rows:
                w.writerow([grp] + [_fmt(r.get(k), 4) for k in CSV_COLS[1:]])


def append_signals(vals, grow, path: Path, run_at: dt.date):
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["run_date", "ticker", "price", "price_date", "value_low", "value_high", "zone", "put_level", "call_level", "stale"])
        for r in vals + grow:
            w.writerow([run_at.isoformat(), r["ticker"], _fmt(r["price"], 4), r["price_date"], _fmt(r["v_low"], 4), _fmt(r["v_high"], 4),
                        r["zone"], _fmt(r.get("put_level"), 4), _fmt(r.get("call_level"), 4), r["stale"]])


def heatmap(rows, cols, path: Path, title=""):
    """rows: (label, price, [(lo, hi) per column])"""
    if not rows:
        return None
    n = len(rows)
    rows = [(l, p, [(max(lo, 0), max(hi, 0)) for lo, hi in v]) for l, p, v in rows]
    data = np.array([[((lo + hi) / 2) / p - 1 for lo, hi in v] for _, p, v in rows])
    fig, ax = plt.subplots(figsize=(8.2, 0.42 * n + 1.3), dpi=160)
    ax.imshow(np.clip(data, -0.6, 0.6), cmap=CMAP, vmin=-0.6, vmax=0.6, aspect="auto")
    for i, (_, p, v) in enumerate(rows):
        for j, (lo, hi) in enumerate(v):
            d = data[i, j]
            txt = f"{lo:,.2f}" if abs(hi - lo) < 1e-9 else f"{lo:,.2f}–{hi:,.2f}"
            col = "white" if abs(d) > 0.38 else "#0b0b0b"
            ax.text(j, i - 0.13, txt, ha="center", va="center", fontsize=6.8, color=col, fontweight="bold")
            ax.text(j, i + 0.23, f"{d*100:+.0f}%", ha="center", va="center", fontsize=6.2, color="white" if abs(d) > 0.38 else "#52514e")
    ax.set_yticks(range(n)); ax.set_yticklabels([f"{l}  ·  now {p:,.2f}" for l, p, _ in rows], fontsize=7.4)
    ax.set_xticks(range(len(cols))); ax.set_xticklabels(cols, fontsize=7); ax.xaxis.tick_top()
    ax.tick_params(length=0); ax.grid(False)
    for sp in ax.spines.values(): sp.set_visible(False)
    ax.set_xticks(np.arange(-0.5, len(cols)), minor=True); ax.set_yticks(np.arange(-0.5, n), minor=True)
    ax.grid(which="minor", color="white", lw=2); ax.tick_params(which="minor", length=0)
    if title: ax.set_title(title, fontsize=9, loc="left", pad=28)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
    return path


def make_heatmaps(vals, grow, cfg, out: Path):
    sp = cfg["spot"]
    mcols = [(f"{'+' if s > 0 else '−'}{abs(s)*100:.0f}%" if s else "Spot") + f"\nAu {sp['gold']*(1+s):,.0f} · Ag {sp['silver']*(1+s):.1f}\nU {sp['uranium']*(1+s):.0f}"
             for s in cfg["metal_scenarios"]]
    gcols = [f"{g*100:+.0f}%/yr" if g else "No growth" for g in cfg["growth_scenarios"]]
    m = heatmap([(f"{r['rank']}. {r['ticker']}", r["price"], r["scenarios"]) for r in vals], mcols, out / "heatmap_metals.png")
    g = heatmap([(f"{r['rank']}. {r['ticker']}", r["price"], r["scenarios"]) for r in grow], gcols, out / "heatmap_growth.png")
    return m, g


def _img(path):
    if not path:
        return ""
    return f'<img src="data:image/png;base64,{base64.b64encode(Path(path).read_bytes()).decode()}" alt="heatmap">'


ZONE_CLASS = {"BUY": "buy", "WATCH": "watch", "HOLD": "hold", "SELL": "sell", "STALE": "stale", "NO EARNINGS": "sell"}


def _zclass(z):
    for k, v in ZONE_CLASS.items():
        if z.startswith(k):
            return v
    return "hold"


def _pct(x):
    if x is None:
        return ""
    return "below −200%" if x < -2 else f"{x*100:+.0f}%"


def write_html(vals, grow, etfs, cfg, heat, path: Path, log_lines):
    sp = cfg["spot"]
    e = html.escape

    def row_vals(r):
        val = f"{r['v_low']:,.2f}" + (f"–{r['v_high']:,.2f}" if abs(r['v_high'] - r['v_low']) > 1e-9 else "")
        impl = ""
        if r.get("implied_metal_hi") is not None:
            impl = f"{r['primary_metal']} {r['implied_metal_hi']:,.1f}"
        cost = "" if r.get("cost_ratio") is None else f"{r['cost_ratio']*100:.0f}%"
        basis = "NAV" if r["model"] in ("developer", "physical") else f"{r.get('mult_lo','')}–{r.get('mult_hi','')}x"
        return (f"<tr><td>{r['rank']}</td><td><b>{e(r['ticker'])}</b><br><span class=m>{e(r['name'])}</span></td><td>{e(r['period'])}</td>"
                f"<td>{r['price']:,.2f} {r['price_ccy']}<br><span class=m>{r['price_date']}</span></td><td>{basis}</td><td>{val}</td>"
                f"<td>{r['coverage_lo']*100:.0f}%</td><td>{_pct(r.get('margin_of_safety'))}</td><td>{impl}</td>"
                f"<td>{cost}</td>"
                f"<td>{_fmt(r.get('put_level'))}</td><td>{_fmt(r.get('call_level'))}</td>"
                f"<td class='z {_zclass(r['zone'])}'>{e(r['zone'])}</td></tr>")

    def row_grow(r):
        g = r["implied_growth"]
        pe = "" if r["pe"] is None else f"{r['pe']:.1f}x"
        gs = "" if g is None else f"{g*100:+.1f}%/yr"
        return (f"<tr><td>{r['rank']}</td><td><b>{e(r['ticker'])}</b><br><span class=m>{e(r['name'])}</span></td><td>{e(r['period'])}</td>"
                f"<td>{r['price']:,.2f} {r['price_ccy']}<br><span class=m>{r['price_date']}</span></td><td>{r['oe']:.2f}</td>"
                f"<td>{pe}</td><td>{r['v0']:,.2f}</td><td>{_pct(r.get('margin_of_safety'))}</td>"
                f"<td><b>{gs}</b></td><td>{_fmt(r.get('put_level'))}</td><td>{_fmt(r.get('call_level'))}</td>"
                f"<td class='z {_zclass(r['zone'])}'>{e(r['zone'])}</td></tr>")

    details = []
    for r in vals + grow:
        items = "".join(f"<li>{e(str(x))}</li>" for x in r["assumptions"]) or "<li>none</li>"
        notes = "".join(f"<li>{e(str(x))}</li>" for x in r["notes"])
        srcs = "".join(f"<li>{e(str(x))}</li>" for x in r["sources"])
        stale = f"<p class=warn>Stale: {e(r['stale_reason'])}</p>" if r["stale"] else ""
        proj = "".join(f"<li>{e(p['name'])}: about {p['value_ps']:.2f} {r['price_ccy']}/share, not in the headline value</li>" for p in r.get("projects", []))
        proj_html = f"<p><b>Projects</b></p><ul>{proj}</ul>" if proj else ""
        notes_html = f"<p><b>Notes</b></p><ul>{notes}</ul>" if notes else ""
        details.append(f"<details><summary><b>{e(r['ticker'])}</b> – {e(r['name'])} · {e(r['zone'])}</summary>{stale}"
                       f"<p><b>Assumptions</b></p><ul>{items}</ul>{proj_html}"
                       f"{notes_html}<p><b>Sources</b></p><ul>{srcs}</ul></details>")

    etf_html = ""
    for name, lt, etf in etfs:
        rows = "".join(f"<tr><td>{e(h['ticker'])}</td><td>{e(h.get('name',''))}</td><td>{h['weight']:.2f}%</td>"
                       + (f"<td>{h['coverage_lo']*100:.0f}–{h['coverage_hi']*100:.0f}%</td></tr>" if h["valued"] else "<td class=m>not valued</td></tr>")
                       for h in lt["rows"])
        head = (f"<p>Valued holdings cover <b>{lt['coverage_weight']:.1f}%</b> of the fund. Look-through value ≈ "
                f"<b>{lt['ratio_lo']*100:.0f}–{lt['ratio_hi']*100:.0f}%</b> of price → {lt['value_lo']:.2f}–{lt['value_hi']:.2f} vs "
                f"{etf['price']['value']:.2f} ({etf['price']['date']}).</p>") if lt.get("ratio_lo") else "<p>No holdings valued.</p>"
        etf_html += f"<h2>ETF look-through – {e(name)}</h2>{head}<table><tr><th>Holding</th><th>Name</th><th>Weight</th><th>Value ÷ price</th></tr>{rows}</table>"

    vals_rows = "".join(row_vals(r) for r in vals)
    grow_rows = "".join(row_grow(r) for r in grow)
    details_html = "".join(details)
    log_html = "".join(f"<li>{e(x)}</li>" for x in log_lines) or "<li>offline run – stored prices</li>"
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Value Screener</title><style>
:root{{--bg:#fff;--ink:#0b0b0b;--ink2:#52514e;--line:#dddcd6;--alt:#f4f3ef;--buy:#1baf7a;--watch:#2a78d6;--hold:#8a8984;--sell:#eb6834;--stale:#b58a00}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--ink:#f1f0ec;--ink2:#b3b2ad;--line:#33332f;--alt:#1e1e1c}}}}
body{{font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--ink);margin:0;padding:16px;max-width:1200px}}
h1{{margin:.2em 0}} .m{{color:var(--ink2);font-size:.85em}} table{{border-collapse:collapse;width:100%;font-size:.85em;margin:.6em 0 1.2em}}
th{{text-align:left;background:var(--ink);color:var(--bg);padding:6px}} td{{padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
tr:nth-child(even) td{{background:var(--alt)}} .z{{font-weight:600}} .buy{{color:var(--buy)}} .watch{{color:var(--watch)}} .hold{{color:var(--hold)}}
.sell{{color:var(--sell)}} .stale{{color:var(--stale)}} .warn{{color:var(--stale)}} img{{max-width:100%;height:auto}} .wrap{{overflow-x:auto}}
details{{border-top:1px solid var(--line);padding:6px 0}} code{{background:var(--alt);padding:1px 4px}}</style></head><body>
<h1>Value Screener</h1><p class=m>Run {cfg['as_of']} · spot gold {sp['gold']:,.0f}, silver {sp['silver']:.2f}, uranium {sp['uranium']:.2f}, copper {sp['copper']:.2f} ·
value = owner earnings at today's metals × multiple + net cash (or NAV / growth DCF). Educational framework, not investment advice.</p>
<h2>Metals, royalty, developers & energy – ranked by value ÷ price at the cautious multiple</h2><div class=wrap><table>
<tr><th>#</th><th>Company</th><th>Results</th><th>Price</th><th>Basis</th><th>Value</th><th>Value ÷ price</th><th>Margin of safety</th>
<th>Metal price needed (fair multiple)</th><th>AISC ÷ spot</th><th>Put level</th><th>Call level</th><th>Zone</th></tr>
{vals_rows}</table></div>{_img(heat[0])}
<h2>Growth companies – ranked by the growth the price needs</h2><div class=wrap><table>
<tr><th>#</th><th>Company</th><th>Results</th><th>Price</th><th>Owner earnings/sh</th><th>Price ÷ earnings</th><th>No-growth value</th>
<th>Margin of safety</th><th>Growth price needs</th><th>Price at 5% growth</th><th>Price at 25% growth</th><th>Zone</th></tr>
{grow_rows}</table></div>{_img(heat[1])}
{etf_html}<h2>Company details</h2>{details_html}
<h2>Run log</h2><ul>{log_html}</ul></body></html>"""
    path.write_text(page, encoding="utf-8")
