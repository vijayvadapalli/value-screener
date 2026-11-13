# Value Screener

Value vs price, the Rick Rule way: each company is valued only from its latest filing, re-priced to today's metal
prices, and compared with what the market charges. Every run writes one HTML report per list that combines the value
view (green / blue / red signals, buy levels) with a profit-growth-vs-price-growth grade, with a sortable summary table
and a linked section per company – plus two PDFs of the same for printing. A flag shows whenever the data is out of date.

## Latest reports

| List | Report (read this) | Value PDF | Profit vs price PDF |
|---|---|---|---|
| Portfolio | [portfolio.html](https://vijayvadapalli.github.io/value-screener/reports/portfolio.html) | [portfolio.pdf](https://vijayvadapalli.github.io/value-screener/reports/portfolio.pdf) | [portfolio-profit-vs-price.pdf](https://vijayvadapalli.github.io/value-screener/reports/portfolio-profit-vs-price.pdf) |
| Tech | [tech.html](https://vijayvadapalli.github.io/value-screener/reports/tech.html) | [tech.pdf](https://vijayvadapalli.github.io/value-screener/reports/tech.pdf) | [tech-profit-vs-price.pdf](https://vijayvadapalli.github.io/value-screener/reports/tech-profit-vs-price.pdf) |
| Oil & gas | [oil.html](https://vijayvadapalli.github.io/value-screener/reports/oil.html) | [oil.pdf](https://vijayvadapalli.github.io/value-screener/reports/oil.pdf) | [oil-profit-vs-price.pdf](https://vijayvadapalli.github.io/value-screener/reports/oil-profit-vs-price.pdf) |
| Miners screen (~270) | [miners-screen.html](https://vijayvadapalli.github.io/value-screener/reports/miners-screen.html) | – | – |
| Nifty 50 | [nifty50.html](https://vijayvadapalli.github.io/value-screener/reports/nifty50.html) | [nifty50.pdf](https://vijayvadapalli.github.io/value-screener/reports/nifty50.pdf) | [nifty50-profit-vs-price.pdf](https://vijayvadapalli.github.io/value-screener/reports/nifty50-profit-vs-price.pdf) |

Each run replaces these with the newest version, so the links never change; the date is inside each report.

The rules follow the Valuation Playbook (Nov 2026); `PROJECT_INSTRUCTIONS.md` has them in full, ready to paste into a
Claude Project. `docs/Value_Screener_Design.pdf` has the original requirements and formulas.

## Quick start

```bash
cd value-screener
python3 -m venv .venv                     # first time only
source .venv/bin/activate                 # every new terminal (Windows: .venv\Scripts\activate)
pip install -r requirements.txt           # first time only
pip install yfinance beautifulsoup4 lxml  # first time only: prices, profit-vs-price figures, Nifty data
python -m valuescreen validate            # checks every company file
```

## Every time

Share prices update after each market closes – for US listings that is about 9 pm UK time; before that you get the
previous day's close.

```bash
source .venv/bin/activate

# 1. share prices into the company files
python tools/update_prices.py                    # portfolio, watchlist, tech (data/companies)
python tools/update_prices.py --folder nifty50   # Nifty 50

# 2. reports: one HTML + two PDFs per list (dated copies in output/, the latest in reports/)
python -m valuescreen run --list portfolio --live   # --live also fetches today's gold, silver and copper
python -m valuescreen run --list tech
python -m valuescreen run --list watchlist
python -m valuescreen run --list nifty50            # first run each day ≈ 4–5 min (Screener.in), then cached

# 3. read them
open reports/portfolio.html                         # Windows: start reports\portfolio.html
open reports/tech.html
open reports/nifty50.html
```

Uranium has no free price feed: set `spot.uranium` in `config.yaml` when it moves. `as_of: today` in `config.yaml`
dates the report and the stale-data checks; set a fixed date there, or pass `--asof 2026-11-04`, to rerun a past day.

Once a quarter, after Indian results: `python tools/fetch_screener.py nifty50` refreshes the Nifty v2 data.

Your prompt shows `(.venv)` while the environment is active. All `python` and `pip` commands in this README assume it
is active. In VS Code, also pick `.venv/bin/python` under **Python: Select Interpreter** so the editor and Run button
use it.

Other runs:

```bash
python -m valuescreen run --list watchlist             # data/lists/watchlist.yaml
python -m valuescreen run --list portfolio --live      # your holdings, live prices (yfinance)
python -m valuescreen run --list portfolio --technicals   # adds price vs 200-day average, RSI and MACD (yfinance)
python -m valuescreen run --tickers AEM,NEM,HL --spot gold=4200,silver=55
python -m valuescreen run --list tech
python -m valuescreen run --all --etf URNM --no-pdf     # every company, ETF look-through, skip the PDFs
python -m valuescreen run --list tech --no-profit      # skip the profit-vs-price figures (no Yahoo calls)
python tools/profit_vs_price.py --list tech            # the profit-vs-price PDF on its own
python -m pytest -q                                    # 215 tests, incl. reproducing the Nov 2026 reports
```

The tests read a frozen copy of the 4 Nov 2026 data in `tests/fixtures/nov2026/`, so updating the live files in
`data/` never breaks them.

Every run writes dated reports and working files to `output/` (`output/nifty50/` for the Nifty), which git ignores, so
your history stays on your computer. It also copies the latest reports to `reports/` under fixed names
(`portfolio.html`, `portfolio.pdf`, `portfolio-profit-vs-price.pdf`, and the same for each list) – the only reports git
tracks and the site publishes.

Reports:

- `<List>_Value_vs_Price_<date>.html` – **the report to read.** One page with both views: a summary table (click a column
  to sort; filter by signal or grade; search by name) where every ticker links to its company section. Each section has
  the headline, the "how to read" cards, the valuation band, charts, key figures, the calculation, the profit-vs-price
  comparison, notes and linked sources, with links back to the summary and to the previous and next company. One file
  with the charts inside, so it opens offline and can be shared as it is.
- `<List>_Profit_vs_Price_<date>.pdf` – the profit-vs-price table for printing (see below).
- `<List>_Value_vs_Price_<date>.pdf` – the value report for printing. Page 1 is the summary table (portfolio columns for producers,
  royalties, developers; a reverse-DCF table for growth stocks), alphabetical, rows tinted by signal and by tier or
  market value. Each company then gets a headline, its "how to read" cards (price, value, margin of safety, buy level),
  the valuation band, the metal-price or growth curve, a heatmap, the calculation with a worked example, key figures,
  assumptions and sources. Bookmarked; footer on every page.

Working files (in `output/`):

- `ranked.csv`, `heatmap_metals.png`, `heatmap_growth.png`, the profit-vs-price cache.
- `signals_log.csv` – appended every run; use it after 4–6 quarters to see whether the BUY zone beat GDX/SIL.
- `runs.json` – each run's key figures, so the next report shows the previous run's figure in (brackets).

## Screening a big list first (NIFTY 50 and other NSE indexes)

Most companies in a big list are not worth a full valuation. Screen them all from free Yahoo data, then do the careful
work only on the shortlist.

```bash
python tools/make_nse_list.py nifty50          # download the constituents into data/lists/nifty50.yaml (also nifty500, niftynext50, ...)
python tools/screen_universe.py nifty50        # rank all of them (about 20 seconds for 50)
python tools/screen_universe.py nifty50 --promote        # also write draft company files for the BUY / WATCH ones
python tools/screen_universe.py nifty50 --promote-all    # ... or for every valued company, flagged ones included
python tools/fetch_screener.py nifty50        # Nifty v2 data from Screener.in for every company (about 4 minutes)
python -m valuescreen validate                 # checks every company folder
python -m valuescreen run --list nifty50       # values the companies that have files
```

**A list keeps its own folders.** The `folder: nifty50` line in `data/lists/nifty50.yaml` means its company files live
in `data/nifty50/companies/` and everything it produces in `output/nifty50/`, apart from your metals and tech
companies in `data/companies/` and `output/`:

| | Metals / tech (default) | NIFTY 50 |
|---|---|---|
| Company files | `data/companies/` | `data/nifty50/companies/` |
| Latest reports (tracked by git, published) | `reports/<list>.html` etc. | `reports/nifty50.html` etc. |
| Dated reports (local history) | `output/` | `output/nifty50/` |
| Working files (`ranked.csv`, `signals_log.csv`, `runs.json`, heatmaps, caches) | `output/` | `output/nifty50/` |
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
  the HTML report); your stale-data rule shows it as STALE until `update_results.py` replaces it with a reported quarter. Expect a
  "moved -75%" warning there, because a quarter is about a quarter of a year.

### Nifty v2 – the full valuation

`tools/fetch_screener.py` reads each company's consolidated page on Screener.in (the playbook's source for India) and
writes a `v2:` block into its file: the last 8 quarterly EPS, up to 10 yearly EPS, 5 years of net profit and cash from
operations, book value per share and 5-year ROE. It also updates the price and share count and keeps everything else
(net cash, notes, sources). It waits ~4 seconds between pages and backs off when Screener rate-limits it; re-run
failed tickers with `--tickers`. A new file starts with net cash 0 and a note to add it from StockAnalysis.

The valuation then applies the v2 rules (`valuescreen/v2.py`):

- Per share, 12 months: the last four quarters, after replacing a one-off quarter (more than 2× the median of the other
  seven and 1.6× its neighbours) with its neighbours' average.
- Cyclicals (oil & gas, metals, cement, power, autos, airlines – lists in `config.yaml`): average of the 12-month EPS and
  the 5-year average. Shown blue at most.
- Financials: average of the 12-month EPS and book value × 5-year ROE, no net cash, and price-to-book against the fair
  multiple (5-yr ROE × the no-growth multiple).
- Discounted at 12% (no-growth multiple ≈ 12.1x instead of 13.1x for the US).
- Cash conversion (cash from operations ÷ net profit over 5 years) below 70% caps the signal at blue.
- Conglomerates and finance arms (L&T, M&M, Bajaj Auto, Grasim) and insurers are flagged.

The AI updater (`update_results.py`) also works on these files, but `fetch_screener.py` is the quicker way to refresh
them each quarter. NSE / BSE results filings remain the authority – check the key figures before acting.

## Screening all the miners (ETF holdings)

A quick first pass over every miner in seven ETFs – which ones deserve a full company file. Kept separate from your
portfolio: its own list (`data/lists/miners.yaml`), company folder (`data/miners/companies`) and output (`output/miners`).

```bash
python tools/make_etf_list.py miners GDX GDXJ SIL SILJ COPX URNM URNJ   # the universe (~270 companies); re-run to refresh
python tools/screen_miners.py                  # screen them all (~5 minutes the first time each day, then cached)
open reports/miners-screen.html                # the report
python tools/screen_miners.py --promote        # draft company files for the shortlist, in data/miners/companies
python tools/update_results.py --folder miners --tickers BTG,KGC --force --dry-run   # fill in the reported quarter
python -m valuescreen run --list miners        # full valuations of the companies that have files
```

- **Funds:** GDX and GDXJ (VanEck), SIL and COPX (Global X), SILJ (Amplify), URNM and URNJ (Sprott), read from the fund
  companies' own daily holdings files. One entry per company; its US listing when an ETF holds it.
- **Figures:** Yahoo's latest twelve months (or latest year, flagged). Value = net profit per share × 12 / 15 + net cash;
  owner earnings taken as net profit (sustaining capex assumed equal to depreciation) and metals **not** re-priced to spot.
  Also price ÷ operating cash flow, free-cash-flow yield, EV / EBITDA, price ÷ book, net cash ÷ price, the profit-vs-price
  grade and the 1-year price change. Money in the price currency (statements converted where needed, flagged).
- **Signals:** Cheap = at least 20% below the 12x value · Fair = at or below 15x · Watch = 15–25x · Expensive = 25x or
  more, or no positive earnings · Not valued = developers and explorers (revenue under 2% of market value) and physical
  holders. **Shortlist** = Cheap producers with positive free cash flow and a grade other than D.
- **Your holdings** from `data/lists/portfolio.yaml` are shown too, tagged "held" (a "My holdings" filter shows only
  them); `--holdings none` leaves them out. Nothing is written to your portfolio files.
- **Yahoo rate limits:** on a list this long Yahoo sometimes blocks for a while. The run then stops fetching, says so,
  and keeps what it has; run it again later and only the missing companies are fetched.

This is a filter, not a verdict – a shortlisted company gets a full company file (metal sold, realised prices, AISC)
and the proper producer valuation before any decision.

## Adding companies by hand (oil and gas)

```bash
python tools/add_companies.py oil XOM COP EOG TPL SU.TO CNQ.TO CVE.TO IMO.TO TOU.TO WCP.TO PEY.TO PSK.TO
python -m valuescreen run --list oil
```

Writes a draft `cashflow`-model company file (10x / 13x) from Yahoo's reported statements for each symbol that has no
file yet, and the list `data/lists/oil.yaml`. Owner earnings = operating cash flow excluding working-capital moves − all
capex. The value is ranked on the average of the last four financial years ("normal" prices, like Chevron's file),
because 2026 cash flows include a price spike; the latest twelve months are kept in `earnings` for reference. Canadian
companies use their Toronto listing, so price and results are both in C$. Files are marked DRAFT – check them, or let
`tools/update_results.py` replace them with the latest reported quarter.

## Keeping the data current

| What | How often | Command |
|---|---|---|
| Share prices | before each scan | `python tools/update_prices.py` (add `--dry-run` to preview) |
| Metal prices | before each scan | gold, silver, copper: add `--live` to a run. Uranium, zinc, lead: edit `spot` in `config.yaml` |
| Company results | when a company reports | `python tools/update_results.py --all --check`, then see below |

**Share prices.** `tools/update_prices.py` saves Yahoo's latest close into each company file's `price` block (value, date
and source only). It skips a company if Yahoo has no price, quotes another currency, or the price moved more than 50%,
so check those by hand. It converts London pence to pounds.

**Metal prices.** `--live` fetches gold, silver and copper for that run only and does not save them. Uranium has no free
feed: look up the U3O8 spot price weekly and set `spot.uranium` in `config.yaml`. `as_of: today` there means the
stale-data check counts from today; a fixed date (or `--asof`) reruns a past day.

## Refreshing a company when it reports (about 10 minutes by hand)

`python tools/update_results.py --all --check` lists which companies should have new results out. It costs nothing and
uses the `next_report` date in each file, Yahoo's earnings calendar (needs `lxml`), and the time since the period ended.
Developers and physical trusts never show as due; use `--force` for those after a new study or NAV.

To have an AI draft the update for the due companies, pick a provider:

| | Claude (default) | Gemini |
|---|---|---|
| Install | `pip install anthropic` | `pip install google-genai` |
| Key | `ANTHROPIC_API_KEY` (billed separately) | `GEMINI_API_KEY`, a free key from Google AI Studio |
| Run | `python tools/update_results.py ...` | `python tools/update_results.py --provider gemini ...` |
| Searches with | Claude's web search and page fetch | Google Search (it works from search results and may not open the whole filing) |

```bash
python tools/update_results.py --tickers CDE --dry-run   # the AI searches the web and shows the proposed changes
python tools/update_results.py --tickers CDE             # same, then type y to save (old file goes to output/backups/)
python tools/update_results.py --provider gemini --tickers CDE --dry-run   # the same with Gemini
```

Neither provider is told which sites to use. The prompt asks for the company's own results release or filing, never
analyst estimates, and every changed number must come with a source URL and a quote, shown in the diff. Gemini's free
tier has request limits (check them in AI Studio); if it is rate limited the company is skipped, so retry later. Model
names change: if the default is not found, the error lists the ones that exist, and `--model` or `GEMINI_MODEL` sets one.

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
AISC ≤ 60% of spot, developer BUY ≤ 0.8 × NAV), DCF settings (10%, 12% for INR, 15x exit, 5 years), the portfolio
tiers, market-value shades, the gold stress-test prices, the Nifty v2 industry lists, and how old results (100 days)
and prices (7 days) can be before they are flagged. A STALE company never shows as BUY.

## Models

| `model:` | For | Value |
|---|---|---|
| `producer` | miners, royalty and streaming companies | owner earnings (adj. net income + D&A − sustaining capex; royalties: adj. net income) re-priced to today's metals, × 12 / 15 / 25 + net cash. A company without `metals` (Cameco) keeps its own realised prices. Optional `ltm:` (four quarters) values the last 12 months instead of the latest quarter × 4; optional `cfo` and `capex_total` add free cash flow after all capex. |
| `cashflow` | oil & gas | the same at 10x / 13x |
| `developer` | ABRA, NXE | study NPV at today's metal price × ownership + cash − debt, per share |
| `physical` | Yellow Cake, Sprott | holdings × spot + other net assets |
| `growth` | tech, Nifty 50 | reverse DCF: the growth the price needs; Nifty v2 rules when the file has a `v2:` block |
| `leases` | Hut 8 | each lease's cash after project bonds and tax, discounted, + site value at lease end; cautious / base / fair |
| `liquid` | UEC, UUUU | not valued: liquid assets as a share of market value |

## Profit growth vs price growth

Did the share price run ahead of the company's profits over about three years? For each company: yearly growth in
sales, profit and the share price over the same years, and what that did to the P/E –
`P/E change = ((1 + price growth) ÷ (1 + profit growth)) ^ years − 1`.

| Grade | P/E change | Means |
|---|---|---|
| A | fell 25% or more | profits clearly outran the price |
| B | fell up to 25% | profits a little ahead |
| C | rose up to a third | roughly in line |
| D | rose more than a third | the price ran ahead of profits |
| n/m | – | a loss at either end, missing figures, or valued on assets (developers, physical holders, leases) |

Indian companies use Screener.in's 3-year compounded growth (net profit). Everything else uses Yahoo Finance statements
from the financial year about three years back to the latest twelve months (diluted EPS, so buybacks count); if that year
was a loss it starts from the next profitable year (about two years). Prices are in the exchange's currency, sales and
profits as the company reports them – growth rates and the P/E change do not depend on the currency. Figures are cached
per list and day in `output/<folder>/profit_vs_price_cache/`. Profits include one-offs: check big jumps in the filing.

To see your position values, add the number of shares to `data/lists/portfolio.yaml`, e.g. `{ticker: FNV, quantity: 35}`;
the profit-vs-price report then shows each position's value in the share's own currency.

## Signals and zones

Green = buy / start a position, blue = watch / hold, red = expensive or no valid value.

| Zone | Producers / royalty | Developers, leases | Physical trusts | Growth (implied growth) |
|---|---|---|---|---|
| BUY | tier A: price ≤ 15x value (start), ≤ 12x (add). Tiers B, C: margin of safety ≥ 20% at 12x. AISC ≤ 60% spot | ≤ 0.8 × NAV (cautious value) | ≤ 0.85 × NAV | ≤ 5%/yr (≤ 10% tier A) |
| WATCH | 0–20% | 0.8–1.0 × | 0.85–1.0 × NAV | 5–10% |
| HOLD | between | 1.0–1.5 × | 1.0–1.1 × NAV | 10–25% |
| SELL / write calls | price ≥ 25x owner earnings | ≥ 1.5 × | ≥ 1.1 × NAV | ≥ 25% |

A cheap cyclical, or cash conversion below 70%, is capped at blue. Comments carry [flags] for stale results, old or
undated prices, high costs, one-off quarters, cyclicals, conglomerates and insurers.

## Optional packages

`requirements.txt` has the core packages, including `reportlab` for the PDF report. The report uses the Inter
typeface, included in `valuescreen/fonts/` (SIL Open Font License). Install these only if you use the feature:

| Package | Needed for |
|---|---|
| `yfinance` | `--live` prices, `--technicals` and `tools/update_prices.py` |
| `beautifulsoup4`, `lxml` | `tools/fetch_screener.py` (Nifty v2 data from Screener.in) |
| `lxml` | Yahoo's earnings calendar in `tools/update_results.py` |
| `anthropic` | Claude drafting updates in `tools/update_results.py` |
| `google-genai` | Gemini drafting updates in `tools/update_results.py --provider gemini` |

## Publishing the reports

`reports/` holds only the latest report for each list, so committing it publishes just those:

```bash
git add reports/
git commit -m "Reports 13 Nov 2026" && git push
```

GitHub Pages (Settings → Pages → Deploy from a branch → main, / root) serves them at the links under "Latest reports"
about a minute after the push. Each push replaces the previous version on the site; older versions stay only in the git
history and in your local `output/` folder. Each commit of all lists adds about 30 MB to the repository (the Nifty HTML
and PDF are ~10 MB each), so commit when something has changed rather than after every run. The repository is public,
so the published reports – including the portfolio list – can be seen by anyone. (Do not move the HTML reports to Git
LFS: GitHub Pages cannot serve LFS files.)

## Code map

```
valuescreen/loader.py      read and check company, list and config files (also last-12-month earnings, tiers)
valuescreen/models.py      the valuation models; leases.py (Hut 8) and v2.py (Nifty v2 rules) beside it
valuescreen/rules.py       zones, signals, buy levels, flags, stale checks
valuescreen/engine.py      runs models + rules over a set of companies
valuescreen/wording.py     what the report says: headlines, steps, worked examples, key figures, cards
valuescreen/charts.py      the charts; style.py holds the fonts and colours
valuescreen/html_report.py the combined HTML report;  pdf.py the value PDF;  profit_vs_price.py the profit-vs-price method + PDF
valuescreen/growth_data.py profit-vs-price figures from Yahoo / Screener.in (screener.py reads Screener pages)
valuescreen/report.py      ranked CSV, signal log, cross-company heatmaps
valuescreen/technicals.py  200-day average, RSI, MACD;  history.py  previous-run figures
valuescreen/miner_screen.py, etf_holdings.py   the miners quick screen and the ETF holdings it starts from
tools/                     update_prices, update_results (AI), fetch_screener, profit_vs_price, make_etf_list, screen_miners,
                           screen_universe, make_nse_list
```

Educational framework, not investment advice.
