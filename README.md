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
python -m pytest -q                                    # 151 tests, incl. reproducing the Nov 2026 reports
```

The tests read a frozen copy of the 4 Nov 2026 data in `tests/fixtures/nov2026/`, so updating the live files in
`data/` never breaks them.

Outputs (in `output/`): `report.html` (ranked tables, heatmaps, every company's assumptions and sources),
`ranked.csv`, `heatmap_metals.png`, `heatmap_growth.png`, and `signals_log.csv` (appended every run – use it after
4–6 quarters to see whether the BUY zone actually beat GDX/SIL).

## Screening a big list first (NIFTY 50 and other NSE indexes)

Most companies in a big list are not worth a full valuation. Screen them all from free Yahoo data, then do the careful
work only on the shortlist.

```bash
python tools/make_nse_list.py nifty50          # download the constituents into data/lists/nifty50.yaml (also nifty500, niftynext50, ...)
python tools/screen_universe.py nifty50        # rank all of them (about 20 seconds for 50)
python tools/screen_universe.py nifty50 --promote        # also write draft company files for the BUY / WATCH ones
python tools/screen_universe.py nifty50 --promote-all    # ... or for every valued company, flagged ones included
python -m valuescreen validate                 # checks every company folder
python tools/update_results.py --folder nifty50 --tickers ITC,TCS --force --dry-run   # Claude replaces each draft with the latest quarter
python tools/update_prices.py --folder nifty50 # fresh share prices for that folder
python -m valuescreen run --list nifty50       # values the companies that have files
```

**A list keeps its own folders.** The `folder: nifty50` line in `data/lists/nifty50.yaml` means its company files live
in `data/nifty50/companies/` and everything it produces in `output/nifty50/`, apart from your metals and tech
companies in `data/companies/` and `output/`:

| | Metals / tech (default) | NIFTY 50 |
|---|---|---|
| Company files | `data/companies/` | `data/nifty50/companies/` |
| Run results (`report.html`, `ranked.csv`, `signals_log.csv`, heatmaps) | `output/` | `output/nifty50/` |
| Screen table and cached Yahoo data | | `output/nifty50/screen_nifty50.csv`, `output/nifty50/screen_cache/` |
| Backups from `update_results.py` | `output/backups/` | `output/nifty50/backups/` |

Commands that take company files also take `--folder nifty50` (`valuescreen run`, `update_prices.py`,
`update_results.py`). A new index list made with `make_nse_list.py` gets its own folder the same way, named after the list.

The screen uses the same growth model as the tech stocks: the no-growth value from the last full year's net income and
net cash, and the growth the share price already assumes. It is deliberately rough:

- **Annual and unadjusted:** Yahoo's last full fiscal year (FY26 to March 2026), not the latest quarter, and total capex
  rather than sustaining capex. Check the FCF yield column: a negative one means capex is eating the earnings.
- **Banks and other financials are skipped.** Owner earnings and net cash don't mean the same thing there, so compare
  P/E and P/B by hand.
- **Suspicious figures are flagged, not shortlisted.** If the year's EPS is far from Yahoo's trailing EPS (a demerger or
  a one-off, like TMPV), the company is listed under "Flagged" for you to check against the filing.
- **Yahoo mislabels some currencies.** Infosys reports in US dollars and is converted; HCLTECH is labelled USD but is
  really rupees and is left alone. The check compares EPS with Yahoo's trailing EPS.
- **Drafts are placeholders.** `--promote` never overwrites a file you already have, marks each draft as unverified, and
  a flagged company's draft starts with a CHECK note (the run table does not show the flag, so read the file or
  `report.html`); your stale-data rule shows it as STALE until `update_results.py` replaces it with a reported quarter. Expect a
  "moved -75%" warning there, because a quarter is about a quarter of a year.

Yahoo is the only source used because it is free and needs no account. For checking the shortlist by hand, Screener.in
has 10 years of financials per company, and the NSE / BSE results filings are the authority.

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
