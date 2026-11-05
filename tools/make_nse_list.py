"""Download an NSE index's constituents and write them as a list in data/lists/.

    python tools/make_nse_list.py nifty50                  # data/lists/nifty50.yaml
    python tools/make_nse_list.py nifty500                 # a bigger universe for tools/screen_universe.py
    python tools/make_nse_list.py niftynext50 --name next50

Any index with a file at https://www.niftyindices.com/IndexConstituent/ind_<index>list.csv works, for example
nifty50, niftynext50, nifty100, nifty200, nifty500, niftymidcap150, niftysmallcap250. Each entry carries the Yahoo
symbol (SYMBOL.NS), so the list can be screened straight away. The list names its own folder, so its company files
live in data/<name>/companies and its results in output/<name>, apart from your other companies. It does not create
company files; see screen_universe.py.
"""
import argparse
import csv
import io
import re
import sys
import urllib.request
from pathlib import Path

import yaml

LISTS = Path(__file__).resolve().parent.parent / "data" / "lists"
URL = "https://www.niftyindices.com/IndexConstituent/ind_{index}list.csv"


def main():
    ap = argparse.ArgumentParser(description="Write an NSE index's constituents to data/lists/")
    ap.add_argument("index", help="index name as in the niftyindices.com file, e.g. nifty50")
    ap.add_argument("--name", help="list name (default: the index name)")
    args = ap.parse_args()

    index = args.index.lower().replace("_", "")
    request = urllib.request.Request(URL.format(index=index), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8-sig")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not download the {index} list ({e.__class__.__name__}: {e}). Check the index name.")

    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "Symbol" not in rows[0]:
        sys.exit("The downloaded file is not an index constituent list.")
    entries = [{"ticker": r["Symbol"].strip().upper(), "yahoo": f"{r['Symbol'].strip()}.NS",
                "name": r["Company Name"].strip(), "industry": r["Industry"].strip()} for r in rows]

    name = args.name or index
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        sys.exit("The list name may only use letters, digits, '-' and '_'.")
    path = LISTS / f"{name}.yaml"
    path.write_text("# Written by tools/make_nse_list.py from niftyindices.com. Re-run it to refresh the constituents.\n"
                    + yaml.safe_dump({"name": f"{index.upper()} constituents", "folder": name, "tickers": entries},
                                     sort_keys=False, allow_unicode=True, width=140), encoding="utf-8")
    print(f"{len(entries)} companies written to {path}")
    print(f"Company files for this list go in data/{name}/companies and results in output/{name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
