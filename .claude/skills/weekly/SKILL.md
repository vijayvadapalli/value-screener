---
name: weekly
description: Run the Value Screener weekly routine – read new results into company files, check news and risks, capture the user's weekly research report (private), run every report, screen and model portfolio via tools/weekly.py, and summarise the brief. Use when the user types /weekly or asks to "do the weekly", "weekly update" or "run the weekly routine".
---

# Weekly routine

Work through these steps in order. Stop and ask only when a figure is unclear or a judgement is the user's to make.
Never commit or push – the user does that. Never put anything from the private research into a public file.

## 1. See what needs attention
Run `python tools/weekly.py --brief-only` and read the brief (also saved to `output/private/weekly-brief.md`):
companies whose results are out or due, signal changes, names at or near our buy levels, research rules near or
triggered.

## 2. Read new results into the company files
For every company the brief lists under "Results to read" whose results are now published (and any with
`next_report` in the past):
- Find the release / filing (company site, SEC 6-K / 10-Q, HKEX, BMV). Prefer primary sources; quote them in `sources`.
- Update `period` (label, end, per_year, reported, next_report), `earnings`, `shares_m`, `balance`, and for producers
  `metals` (units sold, realised price, AISC) and `tax_rate` – in the same shape as the existing file.
- Anything not stated in the source goes in `assumptions`, marked ASSUMED or "derived"; never invent a number.
- Dual listings (A + H shares, ADRs): use the company's total share count, not the one line Yahoo quotes.
- Set `next_report`: the confirmed date, or an estimate from last year's date (say so in `assumptions`).
- `python -m valuescreen validate` must pass.

## 3. News and risk check
For the names that matter this week – green signals, names near buy levels, the core list's tier A, and anything
held in the model portfolios – search for material news since the last run: guidance cuts, mine or plant problems,
share issues (dilution), takeovers, royalty / tax / ownership changes by governments, debt or covenant changes.
Record what matters in the company file's `notes` (with the date and source); if it changes the valuation, update
the file. Report the headlines to the user.

## 4. Capture the weekly research report (PRIVATE)
If the user has a newer report than the latest `data/private/research/<date>.yaml` (they usually save it as
`~/Downloads/Weekend-Report.pdf`):
- Extract the text (PyMuPDF from the scratchpad, or WebFetch for a link) and read the chart images for levels.
- Write `data/private/research/<report date>.yaml` in the same shape as the previous capture: `themes`, `macro`,
  `if_then` rules (`asset`, `when` above/below, `level` price or [low, high], `then`), and per asset `name`,
  `symbol` (Yahoo), `kind`, `stance`, `support`, `resistance`, `targets`, `notes`. Leave moving-average levels out.
- Flag anything ambiguous to the user (e.g. a rule whose asset is unclear).
- Keep it private: `data/private/` and `output/` are git-ignored; never copy its content elsewhere.

## 5. Run everything
`python tools/weekly.py` (add `--quick` to skip Nifty 50 and the two big screens). It updates prices and price
history, runs every report with live metal prices, the screens, the model portfolios, the private research report and
the tests, then rewrites the brief. Fix any failed step (it is listed at the end of the brief).

## 6. Tell the user
A short summary: signals that changed, results read, news that matters, green names and names near buy levels,
research rules near or triggered, and anything that needs their decision. Point to `reports/` (public) and
`output/private/research.html` and `output/private/weekly-brief.md` (private). If code or docs changed, update
README.md and docs/ARCHITECTURE.md, and suggest a one-line commit message.
