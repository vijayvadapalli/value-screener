"""SEC EDGAR access: the official figures every US company files (free, no account).

The SEC requires each automated request to say who is asking, so set this once in your shell profile:
    export SEC_USER_AGENT="Your Name your.email@example.com"
The address is read from the environment only – it is never written into the project.

    company_tickers()          {ticker: cik} for every SEC filer
    download_bulk(path)        the nightly companyfacts.zip (all filers, ~1–1.5 GB), refreshed when older than a week
    iter_companyfacts(path, ciks)   (cik, facts JSON) for just the companies we want, read straight from the zip
The SEC allows up to 10 requests a second; this module makes a handful per run.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import zipfile
from pathlib import Path

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
MAX_AGE_DAYS = 7


class SecError(RuntimeError):
    pass


def user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in ua:
        raise SecError('Set SEC_USER_AGENT to "Your Name your.email@example.com" first – the SEC requires a contact '
                       "in every request. Add it to ~/.zshrc and open a new terminal.")
    return ua


def _open(url):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(), "Accept-Encoding": "identity"})
    return urllib.request.urlopen(req, timeout=120)


def company_tickers(cache: Path) -> dict:
    """{ticker (upper case, '-' for share classes): cik} from the SEC, cached for a week."""
    if not cache.exists() or time.time() - cache.stat().st_mtime > MAX_AGE_DAYS * 86400:
        with _open(TICKERS_URL) as resp:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(resp.read())
    rows = json.loads(cache.read_text()).values()
    return {r["ticker"].upper(): int(r["cik_str"]) for r in rows}


def download_bulk(path: Path, refresh: bool = False, log=print) -> bool:
    """Downloads companyfacts.zip unless the copy at `path` is less than a week old. Returns True if it downloaded."""
    if path.exists() and not refresh and time.time() - path.stat().st_mtime < MAX_AGE_DAYS * 86400:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    with _open(BULK_URL) as resp, open(part, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done, last = 0, 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total and done - last > total / 10:
                log(f"SEC bulk file: {done / total:.0%} of {total / 1e9:.1f} GB")
                last = done
    part.replace(path)
    return True


def iter_companyfacts(path: Path, ciks):
    """(cik, facts) for each wanted CIK that is in the bulk file (members are named CIK##########.json)."""
    wanted = {f"CIK{int(c):010d}.json": int(c) for c in ciks if c}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name in wanted:
                yield wanted[name], json.loads(z.read(name))
