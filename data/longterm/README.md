# Long-term monthly prices

Used for the long-term (monthly, *Max*) charts before Yahoo's daily futures history starts (August 2000).

| File | Series | Source |
|---|---|---|
| `gold_silver_monthly.csv` | Gold and silver, US$ per troy ounce, monthly averages from 1960 | World Bank Commodity Price Data ("Pink Sheet"), `CMO-Historical-Data-Monthly.xlsx`, sheet *Monthly Prices* (CC BY 4.0) |
| `uranium_monthly.csv` | Uranium, US$ per lb, monthly from 1992 | IMF Primary Commodity Prices via FRED, series `PURANUSDM` |
| `uranium_spot_monthly.csv` | Uranium spot, US$ per lb, month-end from 1988 | Cameco, [uranium price page](https://www.cameco.com/invest/markets/uranium-price) (UxC / TradeTech average). Refresh: `python -m valuescreen.longterm` |

The IMF uranium series is not the spot price – it runs below spot (e.g. ~$80 in Jan 2024 when spot reached ~$106) – so
spot-based levels are not drawn on it. Refresh by downloading the two files again and re-running the conversion in
`valuescreen/longterm.py`.
