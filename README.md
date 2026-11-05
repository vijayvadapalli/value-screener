# Value Screener

Value vs price, the Rick Rule way: each company is valued only from its latest filing, re-priced to today's metal
prices, and compared with what the market charges. Output is a ranked list with buy / watch / hold / sell zones,
put and call levels, and a warning whenever the data is out of date.

See `docs/Value_Screener_Design.pdf` for requirements, formulas and the roadmap.

## Quick start

```bash
cd value-screener
python3 -m venv .venv                     # first time only
source .venv/bin/activate                 # every new terminal (Windows: .venv\Scripts\activate)
pip install -r requirements.txt           # first time only; for live prices also: pip install yfinance
python -m valuescreen validate            # checks every company file
python -m valuescreen run --all --etf URNM
open output/report.html                   # (Windows: start output\report.html)
```

Your prompt shows `(.venv)` while the environment is active. All `python` and `pip` commands in this README assume it
is active. In VS Code, also pick `.venv/bin/python` under **Python: Select Interpreter** so the editor and Run button
use it.

Other runs:

```bash
python -m valuescreen run --list watchlist             # data/lists/watchlist.yaml
python -m valuescreen run --list portfolio --live      # your holdings, live prices (yfinance)
python -m valuescreen run --tickers AEM,NEM,HL --spot gold=4200,silver=55
python -m valuescreen run --list tech
python -m pytest -q                                    # 108 tests, incl. reproducing the Nov 2026 reports
```

The tests read a frozen copy of the 4 Nov 2026 data in `tests/fixtures/nov2026/`, so updating the live files in
`data/` never breaks them.

Outputs (in `output/`): `report.html` (ranked tables, heatmaps, every company's assumptions and sources),
`ranked.csv`, `heatmap_metals.png`, `heatmap_growth.png`, and `signals_log.csv` (appended every run – use it after
4–6 quarters to see whether the BUY zone actually beat GDX/SIL).

## Keeping the data current

| What | How often | Command |
|---|---|---|
| Share prices | before each scan | `python tools/update_prices.py` (add `--dry-run` to preview) |
| Metal prices | before each scan | gold, silver, copper: add `--live` to a run. Uranium, zinc, lead and `as_of`: edit `spot` in `config.yaml` |
| Company results | when a company reports | `python tools/update_results.py --all --check`, then see below |

**Share prices.** `tools/update_prices.py` saves Yahoo's latest close into each company file's `price` block (value, date
and source only). It skips a company if Yahoo has no price, quotes another currency, or the price moved more than 50%,
so check those by hand. It converts London pence to pounds.

**Metal prices.** `--live` fetches gold, silver and copper for that run only and does not save them. Uranium has no free
feed: look up the U3O8 spot price weekly and set `spot.uranium` in `config.yaml`. Update `as_of` there too, since it is
the date the stale-data check counts from.

> Known issue: `--live` reads the YCA share price in pence as pounds (about 100 times too high). Use
> `tools/update_prices.py` for YCA, which converts it correctly.

## Refreshing a company when it reports (about 10 minutes by hand)

`python tools/update_results.py --all --check` lists which companies should have new results out. It costs nothing and
uses the `next_report` date in each file, Yahoo's earnings calendar (needs `lxml`), and the time since the period ended.
Developers and physical trusts never show as due; use `--force` for those after a new study or NAV.

To have Claude draft the update for the due companies (needs `pip install anthropic` and `ANTHROPIC_API_KEY`; API use
is billed separately):

```bash
python tools/update_results.py --tickers CDE --dry-run   # Claude searches the web and shows the proposed changes
python tools/update_results.py --tickers CDE             # same, then type y to save (old file goes to output/backups/)
```

It never changes the share price or the ticker, name, sector, model or currency, and it flags numbers that changed
by more than 50% or have no source. Numbers from the web can still be wrong, so check the key figures against the
release before saving.

To do it by hand instead:

1. Open `data/companies/<ticker>.yaml`.
2. From the new results release, update `period` (label, end, reported, next_report), `earnings`, `shares_m`,
   `balance`, `metals` (units sold this period in Moz / Mlb, realised price, AISC), `tax_rate`, `sources`.
3. `python -m valuescreen validate`, then run.

Units: money in millions of the file's `currency` for the period; ounces in Moz and pounds in Mlb per period;
metal prices in USD per oz / lb. `per_year` is 4 for a quarter, 2 for a half, 1 for a year.

## Adding a company

Copy the closest existing file (a producer like `aem.yaml`, a developer like `nxe.yaml`, a physical trust like
`sput.yaml`, a tech stock like `msft.yaml`) and change the numbers. `yahoo:` is the symbol used for live prices
(e.g. `IVN.TO`, `KAP.L`, `PDN.AX`). The price currency can differ from the reporting currency – add the FX rate
to `config.yaml` if it is not there.

## Judgement calls (all in config.yaml)

Spot prices, FX, multiples (12x / 15x cautious and fair, 25x sell), zone thresholds (20% margin of safety for BUY,
AISC ≤ 60% of spot, developer BUY ≤ 0.8 × NAV), DCF settings for tech (10%, 15x exit, 5 years) and how old
results can be before they are STALE (100 days; a STALE company never shows as BUY).

## Zones

| Zone | Producers / royalty | Developers | Physical trusts | Tech (implied growth) |
|---|---|---|---|---|
| BUY | margin of safety ≥ 20% at 12x and AISC ≤ 60% spot | price ≤ 0.8 × NAV | ≤ 0.85 × NAV | ≤ 5%/yr |
| WATCH | 0–20% | 0.8–1.0 × NAV | 0.85–1.0 × NAV | 5–10% |
| HOLD | between | 1.0–1.5 × NAV | 1.0–1.1 × NAV | 10–25% |
| SELL / write calls | price ≥ 25x owner earnings | ≥ 1.5 × NAV | ≥ 1.1 × NAV | ≥ 25% |

## Optional packages

`requirements.txt` has the core packages, plus `reportlab` for rebuilding the design PDF
(`python docs/build_design_doc.py`). Install these only if you use the feature:

| Package | Needed for |
|---|---|
| `yfinance` | `--live` prices and `tools/update_prices.py` |
| `lxml` | Yahoo's earnings calendar in `tools/update_results.py` |
| `anthropic` | Claude drafting updates in `tools/update_results.py` |

Educational framework, not investment advice. Next stage (see design doc): RSI / MACD / 200-day triggers.
