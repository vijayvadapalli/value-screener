"""One-off: writes data/companies/*.yaml from the inputs used in the Nov 2026 Value vs Price reports.
After this, edit the YAML files directly each quarter – this script is kept only as a record."""
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent.parent / "data" / "companies"
OUT.mkdir(parents=True, exist_ok=True)

MAIN = "Value vs Price – main report (Q3 results), 4 Nov 2026"
COMP = "Value vs Price – companion report (Q2 / feasibility), 4 Nov 2026"
TECH = "Value vs Price – tech, chips & energy report, 4 Nov 2026"
SILV = "Value vs Price – Hecla, First Majestic, Discovery report, 4 Nov 2026"
URNM = "URNM look-through analysis, 4 Nov 2026"


def per(label, end, reported=None, per_year=4, next_report=None):
    d = dict(label=label, end=end, per_year=per_year)
    if reported: d["reported"] = reported
    if next_report: d["next_report"] = next_report
    return d


def px(v, ccy, date, source):
    return dict(value=v, currency=ccy, date=date, source=source)


C = []

# ------------------------------------------------------------------ main report (Q3-2026)
C.append(dict(ticker="AEM", name="Agnico Eagle Mines", sector="gold", model="producer", currency="USD",
              period=per("Q3-2026", "2026-09-30", "2026-10-28"),
              earnings=dict(adj_net_income=1324.349, da=457.447, sustaining_capex=296.173),
              shares_m=505.546481, balance=dict(net_cash=3416.023),
              metals=[dict(metal="gold", units=0.825084, realised=4264, aisc=1648)], tax_rate=0.35,
              price=px(167.21, "USD", "2026-11-03", "Upstox"),
              sources=["AEM Q3-2026 results, SEC Ex 99.1, 28 Oct 2026", MAIN],
              notes=["Barnat pit (Malartic) cuts output 60–80koz H2-26 and up to 150koz/yr in 2027–28"]))
C.append(dict(ticker="NEM", name="Newmont", sector="gold", model="producer", currency="USD",
              period=per("Q3-2026", "2026-09-30", "2026-10-22"),
              earnings=dict(adj_net_income=2309, da=632, sustaining_capex=525), shares_m=1051,
              balance=dict(net_cash=1293.0),
              metals=[dict(metal="gold", units=1.19086, realised=4317),
                      dict(metal="silver", units=6.25, realised=50.50),
                      dict(metal="copper", units=60.126, realised=6.91)], tax_rate=0.33,
              price=px(109.09, "USD", "2026-11-02", "StockTitan"),
              sources=["NEM Q3-2026 results and 2026 guidance sensitivities, 22 Oct 2026", MAIN],
              assumptions=["Gold units = company sensitivity ($505m per $100/oz less royalty effect) ÷ 400, i.e. ounces-equivalent",
                           "Silver and copper from company sensitivities ($25m per $1/oz Ag; $60m per $0.25/lb Cu)",
                           "Net cash after the committed $1,950m Barrick payment"]))
C.append(dict(ticker="AGI", name="Alamos Gold", sector="gold", model="producer", currency="USD",
              period=per("Q3-2026", "2026-09-30", "2026-10-28"),
              earnings=dict(adj_net_income=184.0, da=44.2, sustaining_capex=52.9), shares_m=418.572,
              balance=dict(cash=597.4, debt=200.0),
              metals=[dict(metal="gold", units=0.118361, realised=4258)], tax_rate=0.361,
              price=px(27.76, "USD", "2026-11-02", "ChartRow"),
              sources=["AGI Q3-2026 results, 28 Oct 2026", MAIN]))
C.append(dict(ticker="CCJ", name="Cameco", sector="uranium", model="producer", currency="CAD",
              period=per("9M-2026", "2026-09-30", "2026-10-30", per_year=4 / 3),
              earnings=dict(adj_net_income=279.0), shares_m=435.53, balance=dict(cash=860, debt=1000),
              price=px(72.26, "USD", "2026-11-03", "CoinGlass"),
              sources=["Cameco Q3-2026 results, 30 Oct 2026", MAIN],
              assumptions=["Nine-month adjusted net earnings annualised (× 4/3); cash-flow lines not fully retrievable – earnings proxy",
                           "Westinghouse (49%) counted only through reported earnings"]))
C.append(dict(ticker="IVN", yahoo="IVN.TO", name="Ivanhoe Mines", sector="copper", model="producer", currency="USD",
              period=per("Q3-2026", "2026-09-30", "2026-11-03"),
              earnings=dict(adj_net_income=50.641), shares_m=1430,
              price=px(8.88, "CAD", "2026-11-03", "MarketScreener"),
              sources=["Ivanhoe Q3-2026 results, 3 Nov 2026", MAIN],
              assumptions=["Earnings proxy – cash-flow lines not fully retrievable; net cash not included"]))
C.append(dict(ticker="YCA", yahoo="YCA.L", name="Yellow Cake", sector="uranium", model="physical", currency="USD",
              period=per("NAV-Oct-2026", "2026-10-27", "2026-10-27"),
              holdings=dict(metal="uranium", units=24.37), other_net_assets=41.7,
              nav_ref=dict(value=6.65, spot=89.85),
              price=px(5.345, "GBP", "2026-11-04", "Investing.com"),
              sources=["Yellow Cake NAV update, 27 Oct 2026 (£6.65/share at $89.85/lb)", MAIN],
              assumptions=["NAV scaled from the company's published £6.65 at $89.85/lb; GBP/USD held at 26 Oct"]))
C.append(dict(ticker="CVX", name="Chevron", sector="energy", model="cashflow", currency="USD",
              period=per("Q3-2026", "2026-09-30", "2026-10-30"),
              earnings=dict(cfo_ex_wc=16552, capex=4011, shares_m=1951),
              earnings_normalised=dict(cfo_ex_wc=9940, capex=4444, shares_m=1946), rank_on_normalised=True,
              shares_m=1951, balance=dict(net_cash=-20730), multiples=[10, 13], cyclical=True,
              price=px(225.27, "USD", "2026-11-03", "company / market close"),
              sources=["Chevron Q3-2026 earnings, 30 Oct 2026; Q3-2025 for normal-oil basis", MAIN],
              assumptions=["Valued on 'normal oil' (Q3-2025, Brent ~$69) because Q3-2026 includes a war-driven spike",
                           "10x/13x multiples for a depleting, cyclical oil major"]))
C.append(dict(ticker="SLB", name="SLB", sector="energy", model="producer", currency="USD",
              period=per("Q3-2026", "2026-09-30", "2026-10-23"),
              earnings=dict(adj_net_income=958.08, da=698, sustaining_capex=682), shares_m=1497,
              balance=dict(net_cash=-9249),
              price=px(53.31, "USD", "2026-10-23", "latest found"),
              sources=["SLB Q3-2026 results, 23 Oct 2026", MAIN],
              assumptions=["Adjusted EPS $0.64 × 1,497m shares; all capital investment treated as sustaining"]))

# ------------------------------------------------------------------ companion report (Q2-2026)
q2 = lambda nxt=None: per("Q2-2026", "2026-06-30", "2026-08-06", next_report=nxt)  # noqa: E731
C.append(dict(ticker="CDE", name="Coeur Mining", sector="silver", model="producer", currency="USD", period=q2("2026-11-04"),
              earnings=dict(adj_net_income=122.6, addbacks=103.44, da=256.0, sustaining_capex=104.331), shares_m=1028.536,
              balance=dict(cash=1052.3, debt=705.3),
              metals=[dict(metal="gold", units=0.167877, realised=4140), dict(metal="silver", units=4.518263, realised=71.18)],
              tax_rate=round(93.2 / 215.8, 6), price=px(13.41, "USD", "2026-11-03", "FinancialContent"),
              sources=["Coeur Q2-2026 results, SEC Ex 99.1, 5 Aug 2026", COMP],
              assumptions=["Add-back = non-cash Rainy River inventory charge ($0.10/share)", "Sustaining capex = 83% of $125.7m"]))
C.append(dict(ticker="FSM", name="Fortuna Mining", sector="gold", model="producer", currency="USD", period=q2("2026-11-04"),
              earnings=dict(adj_net_income=75.5, da=44.0, sustaining_capex=45.5), shares_m=round(123.7 / 0.41, 3),
              balance=dict(net_cash=434.2),
              metals=[dict(metal="gold", units=0.062081, realised=4447), dict(metal="silver", units=0.281433, realised=75.33)],
              tax_rate=0.46, price=px(9.31, "USD", "2026-10-29", "Upstox"),
              sources=["Fortuna Q2-2026 results, SEC Ex 99.5, 5 Aug 2026", COMP]))
C.append(dict(ticker="IAG", name="IAMGOLD", sector="gold", model="producer", currency="USD", period=q2("2026-11-05"),
              earnings=dict(adj_net_income=241.6, da=117.15, sustaining_capex=96.3), shares_m=578.0,
              balance=dict(net_cash=52.2),
              metals=[dict(metal="gold", units=0.1802, realised=4384, royalty=0.13, aisc=2271)], tax_rate=0.30,
              price=px(15.85, "USD", "2026-11-03", "StockAnalysis"),
              sources=["IAMGOLD Q2-2026 results, SEC Ex 99.1, 6 Aug 2026", COMP],
              assumptions=["Tax rate 30% ASSUMED (Q2 tax $109.3m broadly supports it)", "D&A = H1 $234.3m ÷ 2",
                           "Burkina Faso royalty falls ~$13/oz per $100 gold move (company table)"],
              notes=["Essakane (Burkina Faso) ~47% of output; $100–200m cash held in-country"]))
C.append(dict(ticker="PAAS", name="Pan American Silver", sector="silver", model="producer", currency="USD", period=q2("2026-11-04"),
              earnings=dict(adj_net_income=308, da=120, sustaining_capex=74), shares_m=417.074,
              balance=dict(cash=1705.0, debt=717.0),
              metals=[dict(metal="gold", units=0.1656, realised=4402), dict(metal="silver", units=5.33, realised=70.97)],
              tax_rate=round(179 / 484, 6), price=px(37.99, "USD", "2026-10-30", "Benzinga"),
              sources=["Pan American Q2-2026 results, Aug 2026", COMP]))
C.append(dict(ticker="RGLD", name="Royal Gold", sector="royalty", model="producer", currency="USD", period=q2("2026-11-04"),
              earnings=dict(adj_net_income=218.2), shares_m=85.052, balance=dict(cash=182.5, debt=400.0),
              metals=[dict(metal="gold", units=0.1, realised=4506)], tax_rate=0.197,
              price=px(234.11, "USD", "2026-10-26", "StockAnalysis"),
              sources=["Royal Gold Q2-2026 results, Aug 2026", COMP],
              assumptions=["400k GEOs a year re-priced with gold only – silver/copper exposure ignored (slightly generous)"]))
C.append(dict(ticker="WPM", name="Wheaton Precious Metals", sector="royalty", model="producer", currency="USD", period=q2("2026-11-05"),
              earnings=dict(adj_net_income=542.542), shares_m=454.991, balance=dict(cash=100.192, debt=1969.282),
              metals=[dict(metal="gold", units=0.10375, realised=4452), dict(metal="silver", units=7.0, realised=73.41)],
              tax_rate=0.0, price=px(122.37, "USD", "2026-10-26", "StockAnalysis"),
              sources=["Wheaton Q2-2026 results and 2026 guidance midpoints, Aug 2026", COMP],
              assumptions=["Tax ~0% ASSUMED (low-tax structure)", "Volumes = 2026 guidance midpoints (415koz Au, 28Moz Ag a year)"],
              notes=["CHECK on refresh: balance carried as $1,969m debt vs $100m cash from the companion report – Wheaton is usually debt-free"]))
C.append(dict(ticker="FNV", name="Franco-Nevada", sector="royalty", model="producer", currency="USD", period=q2("2026-11-11"),
              earnings=dict(adj_net_income=349.2), shares_m=193.3, balance=dict(net_cash=1014.2),
              metals=[dict(metal="gold", units=0.091224, realised=round(403.0e6 / 91224, 4)),
                      dict(metal="silver", units=round(83.5 / 73.15, 6), realised=73.15)],
              tax_rate=round(104.9 / 458.9, 6), price=px(229.27, "USD", "2026-11-02", "ChartRow"),
              sources=["Franco-Nevada Q2-2026 results, Aug 2026", COMP],
              assumptions=["Silver realised price = Q2 average from Royal Gold's release ($73.15); FNV did not publish it",
                           "Energy, PGM and iron-ore revenue held at Q2 levels"]))
C.append(dict(ticker="MTA", name="Metalla Royalty", sector="royalty", model="producer", currency="USD", period=q2(),
              earnings=dict(adj_net_income=1.223), shares_m=93.496, balance=dict(cash=10.7, debt=13.1),
              metals=[dict(metal="gold", units=0.001173, realised=4504)], tax_rate=0.0,
              price=px(7.29, "USD", "2026-10-23", "Robinhood"),
              sources=["Metalla Q2-2026 results, Aug 2026", COMP],
              assumptions=["Net income used – no adjusted figure published"]))
C.append(dict(ticker="ABRA", yahoo="ABRA.V", name="AbraSilver Resource", sector="silver", model="developer", currency="USD",
              period=per("DFS-2026", "2026-06-30", "2026-06-22", per_year=1),
              npv_curve=dict(metal="silver", currency="USD", ownership=1.0, points=[[40, 1359], [50, 2223], [60, 3083], [70.69, 3623]]),
              shares_m=165.49, balance=[dict(label="cash and equivalents", amount=8.088 + 15.435 + 49.99 + 2.05, currency="CAD")],
              price=px(11.77, "CAD", "2026-10-23", "StockAnalysis"),
              sources=["Diablillos Definitive Feasibility Study, 22 Jun 2026 (after-tax NPV 8%)", COMP],
              assumptions=["Gold moves with silver as in the study's price cases", "Study NPV before construction, financing and country risk"]))
C.append(dict(ticker="NXE", name="NexGen Energy", sector="uranium", model="developer", currency="CAD",
              period=per("FS-2024 / Q2-2026 balance", "2026-06-30", "2026-08-01", per_year=1),
              npv_curve=dict(metal="uranium", currency="CAD", ownership=1.0,
                             points=[[50, 2100], [80, 4890], [95, 6320], [100, 6790], [150, 11520]]),
              shares_m=670.506, balance=[dict(label="cash", amount=756.173, currency="CAD"), dict(label="investments", amount=214.080, currency="CAD"),
                                         dict(label="convertible debentures", amount=-360, currency="USD")],
              price=px(7.96, "USD", "2026-11-03", "ChartRow"),
              sources=["Rook I updated FS economics, 1 Aug 2024 (2023 dollars, after-tax NPV 8%)", COMP]))

# ------------------------------------------------------------------ tech, chips & energy
def tech(t, name, label, end, rep, ni=None, eps=None, shares=None, cash=0.0, debt=0.0, price=None, pdate=None, ccy="USD",
         per_year=4, adj=None, nxt=None, extra=None, sources=None, assumptions=None, notes=None, eps_ccy=None, adr=None, sh_bal=None, pccy="USD", **kw):
    e = {}
    if ni is not None: e["net_income"] = ni
    if eps is not None: e["eps_per_period"] = eps
    if eps_ccy: e["eps_currency"] = eps_ccy
    if adr: e["adr_ratio"] = adr
    if adj: e["adjustments"] = adj
    d = dict(ticker=t, name=name, sector="tech", model="growth", currency=ccy, period=per(label, end, rep, per_year, nxt),
             earnings=e, shares_m=shares, balance=dict(cash=cash, debt=debt), price=px(price, pccy, pdate, "see report"),
             sources=(sources or []) + [TECH], assumptions=assumptions or [], notes=notes or [])
    if sh_bal: d["shares_m_balance"] = sh_bal
    d.update(kw)
    return d

C += [
    tech("AAPL", "Apple", "FY26 (Sep)", "2026-09-26", "2026-10-30", ni=132175, shares=14720.306, sh_bal=14630.318,
         cash=36305 + 20417 + 80213, debt=1997 + 9906 + 68208, price=331.90, pdate="2026-11-03", per_year=1,
         sources=["Apple FY26 Q4 consolidated financial statements"], assumptions=["Full fiscal year used – December quarter is seasonally largest"]),
    tech("MSFT", "Microsoft", "FQ1-27 (Sep)", "2026-09-30", "2026-10-28", ni=36629, shares=7446, cash=64509, debt=35481,
         price=520.99, pdate="2026-11-03", sources=["Microsoft FY27 Q1 release"], assumptions=["Debt excludes finance leases"]),
    tech("GOOGL", "Alphabet", "Q3-26", "2026-09-30", "2026-10-28", ni=26468, shares=12368, cash=265098, debt=125102,
         adj=[dict(label="loss on equity securities added back", amount=8664, tax_rate=0.21)], price=278.99, pdate="2026-11-02",
         sources=["Alphabet Q3-2026 release"], assumptions=["Equity-securities loss stripped at an ASSUMED 21% tax"]),
    tech("AMZN", "Amazon", "Q3-26", "2026-09-30", "2026-10-29", ni=20690, shares=round(20690 / 1.89, 2), cash=114200, debt=180300,
         price=245.63, pdate="2026-11-02", sources=["Amazon Q3-2026 release; 10-Q analysis (sec-api)"],
         assumptions=["Diluted shares derived as net income ÷ EPS $1.89"]),
    tech("NVDA", "Nvidia", "Q2-FY27 (Jul)", "2026-07-26", "2026-08-26", ni=59688, shares=24285, cash=22443 + 34143, debt=1000 + 32366,
         adj=[dict(label="gains on equity securities removed", amount=-7771, tax_rate=0.21)], price=206.69, pdate="2026-11-03",
         nxt="2026-11-19", sources=["Nvidia Q2 FY2027 release"],
         assumptions=["Equity gains stripped at an ASSUMED 21% tax", "$42.8bn of marketable equity stakes not counted as cash"]),
    tech("QCOM", "Qualcomm", "FQ3-26 (Jun)", "2026-06-28", "2026-07-29", ni=2002, shares=1069, cash=8304, debt=15270,
         price=162.08, pdate="2026-11-02", nxt="2026-11-04", sources=["Qualcomm FQ3-2026 release"]),
    tech("AVGO", "Broadcom", "FQ3-26 (Aug)", "2026-08-02", "2026-09-04", ni=13088, shares=4887, cash=23975, debt=59419,
         price=322.23, pdate="2026-11-02", sources=["Broadcom FQ3-2026 release"],
         assumptions=["GAAP keeps $2.0bn/qtr VMware amortisation as a cost (cautious)"]),
    tech("ORCL", "Oracle", "FQ1-27 (Aug)", "2026-08-31", "2026-09-09", eps=1.56, shares=3000, cash=37080, debt=125340,
         price=119.22, pdate="2026-11-02", sources=["Oracle FQ1-2027 release"],
         assumptions=["Excludes the $20bn stock + notes raise priced 3 Nov 2026"]),
    tech("TSM", "TSMC (ADR)", "Q3-26", "2026-09-30", "2026-10-16", eps=29.43, eps_ccy="TWD", adr=5, ccy="TWD",
         shares=25932 / 5, cash=4016.98e3, debt=1031.58e3, price=398.63, pdate="2026-11-02",
         sources=["TSMC 3Q26 Management Report"], assumptions=["1 ADR = 5 shares; NT$31.98/US$ (TSMC's Q3 average)",
                                                             "shares_m expressed in ADR equivalents"]),
    tech("MU", "Micron", "FQ4-26 (Aug)", "2026-08-27", "2026-09-23", ni=37700, shares=1147, cash=73480, debt=5180,
         price=833.59, pdate="2026-11-02", sources=["Micron FQ4-2026 release"], cyclical=True,
         notes=["Memory is highly cyclical: 87% gross margin is near-peak; Goldman 'normalised' EPS ~$70"]),
    tech("AMD", "AMD", "Q3-26", "2026-09-26", "2026-11-03", eps=1.46, shares=1661, cash=15776, debt=7079,
         price=466.84, pdate="2026-11-02", sources=["AMD Q3-2026 release"], assumptions=["GAAP EPS keeps Xilinx amortisation as a cost"]),
    tech("ASML", "ASML (ADR)", "Q3-26", "2026-09-28", "2026-10-14", eps=12.93, eps_ccy="EUR", ccy="EUR", shares=383.5,
         cash=8030.9 + 4704.2, debt=1963.0, price=1565.90, pdate="2026-10-30", sources=["ASML Q3-2026 financial statements"],
         assumptions=["EUR at $1.117 (27 Oct)"]),
]

# ------------------------------------------------------------------ Hecla, First Majestic, Discovery
C.append(dict(ticker="HL", name="Hecla Mining", sector="silver", model="producer", currency="USD",
              period=per("Q3-2026", "2026-09-30", "2026-11-03"),
              earnings=dict(adj_net_income=149.5, da=39.2, sustaining_capex=36.875,
                            adjustments=[dict(label="fair-value gains on investments removed (pre-tax, cautious)", amount=-26.7, tax_rate=0.0)]),
              shares_m=676.9, balance=dict(net_cash=692.0),
              metals=[dict(metal="silver", units=4.094203, realised=63.62, aisc=14.34), dict(metal="gold", units=0.012706, realised=4279)],
              tax_rate=round(40.5 / 190.1, 6), price=px(13.98, "USD", "2026-10-26", "StockAnalysis"),
              sources=["Hecla Q3-2026 results, 3 Nov 2026", SILV],
              assumptions=["Sustaining capex = ¼ of FY guidance midpoint ($142–153m); Q3 split not published", "Lead and zinc not re-priced"]))
C.append(dict(ticker="AG", name="First Majestic Silver", sector="silver", model="producer", currency="USD",
              period=per("Q2-2026", "2026-06-30", "2026-07-30", next_report="2026-11-05"),
              earnings=dict(adj_net_income=101.6), shares_m=493.335, balance=dict(cash=1093.3, debt=302.754),
              metals=[dict(metal="silver", units=3.799823, realised=63.98, aisc=25.68), dict(metal="gold", units=0.03466, realised=4347)],
              tax_rate=round(68.067 / 193.960, 6), price=px(14.85, "USD", "2026-10-26", "StockAnalysis"),
              sources=["First Majestic Q2-2026 release and interim statements (SEC 6-K)", SILV],
              assumptions=["Owner earnings = adjusted net earnings (sustaining capex not split out; assumed ≈ D&A $48.4m)",
                           "Restricted cash $159m excluded"],
              notes=["Q3 output 3.44 Moz Ag (San Dimas 12-day labour dispute)"]))
C.append(dict(ticker="DSV", yahoo="DSV.TO", name="Discovery Mining", sector="gold", model="producer", currency="USD",
              period=per("Q2-2026", "2026-06-30", "2026-08-13"),
              earnings=dict(adj_net_income=92.3, da=40.6, sustaining_capex=36.5), shares_m=818.1,
              balance=[dict(label="cash", amount=364.3), dict(label="Newmont deferred payments ($37.5m/yr from Dec 2027)", amount=-150.0)],
              metals=[dict(metal="gold", units=round(289.4 / 4474, 6), realised=4474, aisc=2154)],
              tax_rate=round((60.6 - 19.7) / (52.1 + 60.6), 6), price=px(10.10, "CAD", "2026-10-26", "StockAnalysis"),
              projects=[dict(name="Cordero silver project (after-tax study NPV)", npv=1200, currency="USD")],
              sources=["Discovery Q2-2026 results, 13 Aug 2026", "Newmont Porcupine sale terms, 25 Jan 2025", SILV],
              assumptions=["Tax excludes $19.7m one-off deferred tax", "Cash ounces exclude 2,813 oz delivered in kind to Franco-Nevada",
                           ]))

# ------------------------------------------------------------------ URNM top holdings (look-through)
C.append(dict(ticker="KAP", yahoo="KAP.L", name="Kazatomprom", sector="uranium", model="producer", currency="KZT",
              period=per("1H-2026", "2026-06-30", "2026-08-21", per_year=1),
              earnings=dict(owner_earnings=round(156555 * 2150000 / 717834, 1)), shares_m=259.356608,
              balance=dict(net_cash=157121), price=px(61.90, "USD", "2026-11-02", "TipRanks"),
              sources=["Kazatomprom 1H2026 financial results, 21 Aug 2026", URNM],
              assumptions=["Full-year attributable profit ≈ H1 × (2026 revenue guidance midpoint ÷ H1 revenue) – sales are H2-weighted",
                           "KZT 490/USD (company guidance rate)"]))
C.append(dict(ticker="SPUT", yahoo="U-U.TO", name="Sprott Physical Uranium Trust", sector="uranium", model="physical", currency="USD",
              period=per("NAV 3 Nov 2026", "2026-11-03", "2026-11-03"),
              holdings=dict(metal="uranium", units=81.7), other_net_assets=0.0, nav_ref=dict(value=22.22, spot=93.6),
              price=px(18.91, "USD", "2026-11-03", "Yellowcake Analytics"),
              sources=["Sprott Physical Uranium Trust NAV via yellowcakeanalytics.com, 3 Nov 2026", URNM]))
C.append(dict(ticker="CGN", yahoo="1164.HK", name="CGN Mining", sector="uranium", model="producer", currency="HKD",
              period=per("FY-2025", "2025-12-31", "2026-03-26", per_year=1),
              earnings=dict(owner_earnings=round(0.0596 * 7600.6826, 2)), shares_m=7600.6826,
              price=px(2.07, "HKD", "2026-10-30", "TipRanks"),
              sources=["CGN Mining FY2025 results, 26 Mar 2026", URNM],
              assumptions=["FY2025 EPS used; 1H-2026 was a small loss", "Net cash not included (not retrieved)"]))
C.append(dict(ticker="PDN", yahoo="PDN.AX", name="Paladin Energy", sector="uranium", model="producer", currency="USD",
              period=per("FY27 guidance / Q1-FY27", "2026-09-30", "2026-10-13", per_year=1),
              earnings=dict(owner_earnings=round(((79.4 - 46) * 5.35 - 6.9 * 4) * 0.75 * (1 - 0.375), 2)),
              shares_m=round(3790 / 12.57, 2),
              balance=[dict(label="cash", amount=209), dict(label="term loan", amount=-28), dict(label="400k lb product loan at $92", amount=-36.8)],
              price=px(12.57, "AUD", "2026-10-13", "TipRanks"),
              sources=["Paladin September 2026 quarterly; FY2026 results", URNM],
              assumptions=["Owner earnings estimated from FY27 guidance: (Q1 realised $79.4 − cost midpoint $46) × 5.35 Mlb − sustaining capex, × 75% LHM, × (1 − 37.5% Namibian tax)",
                           "Corporate costs and Patterson Lake South not included", "Shares derived from market cap ÷ price"],
              notes=["Lost $9.1m in FY2026"]))
C.append(dict(ticker="DNN", name="Denison Mines", sector="uranium", model="developer", currency="CAD",
              period=per("Phoenix capex update / Q2-2026", "2026-06-30", "2026-08-12", per_year=1),
              npv_curve=dict(metal="uranium", currency="CAD", ownership=0.90, points=[[73.625, 1570], [86, 1940]]),
              holdings=dict(metal="uranium", units=1.1),
              shares_m=round(1910 / 2.105, 1),
              balance=[dict(label="cash", amount=465, currency="CAD"), dict(label="4.25% convertible notes 2031", amount=-345, currency="USD")],
              price=px(2.105, "USD", "2026-11-03", "MarketBeat"),
              sources=["Denison Phoenix construction & capex update, 2 Jan 2026 (NPV 8%)", "Denison Q2-2026 results", URNM],
              assumptions=["NPV extrapolated from the company's two price cases to spot", "90% Phoenix JV share",
                           "Gryphon, McClean Lake and other assets excluded"]))

for c in C:
    path = OUT / f"{c['ticker'].lower()}.yaml"
    with open(path, "w") as f:
        yaml.safe_dump(c, f, sort_keys=False, allow_unicode=True, width=140)
print(f"wrote {len(C)} files to {OUT}")
