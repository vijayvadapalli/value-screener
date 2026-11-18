"""Load and validate company, ETF, list and config files."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

from .settings import ValidationError, fx, tier_of  # noqa: F401 (re-exported: tools and tests use loader.*)

ROOT = Path(__file__).resolve().parent.parent
MODELS = {"producer", "cashflow", "developer", "physical", "growth", "leases", "liquid"}




def _date(x, field, ticker):
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x))
    except Exception as e:  # noqa: BLE001
        raise ValidationError(f"{ticker}: {field} must be a date YYYY-MM-DD, got {x!r}") from e


def load_config(path: Path | None = None) -> dict:
    cfg = yaml.safe_load(open(path or ROOT / "config.yaml"))
    as_of = cfg.get("as_of", "today")
    cfg["as_of"] = dt.date.today() if str(as_of).lower() == "today" else _date(as_of, "as_of", "config")
    return cfg


def validate_company(c: dict, src: str = "") -> dict:
    t = c.get("ticker") or src
    for f in ("ticker", "name", "model", "currency", "period", "price", "sources"):
        if f not in c:
            raise ValidationError(f"{t}: missing required field '{f}'")
    if c["model"] not in MODELS:
        raise ValidationError(f"{t}: model must be one of {sorted(MODELS)}")
    if not c["sources"]:
        raise ValidationError(f"{t}: at least one source is required")
    p = c["period"]
    for f in ("label", "end"):
        if f not in p:
            raise ValidationError(f"{t}: period.{f} is required")
    p["end"] = _date(p["end"], "period.end", t)
    if p.get("reported"):
        p["reported"] = _date(p["reported"], "period.reported", t)
    if p.get("next_report"):
        p["next_report"] = _date(p["next_report"], "period.next_report", t)
    p.setdefault("per_year", 4)
    pr = c["price"]
    for f in ("value", "currency", "date"):
        if f not in pr:
            raise ValidationError(f"{t}: price.{f} is required")
    pr["date"] = _date(pr["date"], "price.date", t)
    from . import kinds  # noqa: PLC0415 - imported here: the models need numpy and matplotlib, most file reads do not
    problem = kinds.of(c["model"]).check(c)   # what this model needs in the file
    if problem:
        raise ValidationError(f"{t}: {problem}")
    if c.get("ltm"):
        apply_ltm(c)
    for x in c.get("metals", []):
        for f in ("metal", "units", "realised"):
            if f not in x:
                raise ValidationError(f"{t}: each metal needs '{f}'")
    c.setdefault("assumptions", [])
    c.setdefault("notes", [])
    c.setdefault("yahoo", c["ticker"])
    return c


def apply_ltm(c: dict) -> dict:
    """Last 12 months instead of the latest quarter × 4 (Valuation Playbook open item 5).

    `ltm:` lists the last four single quarters, oldest first, each with the same earnings fields as `earnings`
    (adj_net_income or net_income, da, sustaining_capex, ...) and optionally `metals` (units sold, realised price).
    They are summed into one 12-month period: units add up, realised prices are weighted by units sold.
    The latest quarter is kept as `earnings_latest_quarter` for the report.
    """
    t = c.get("ticker", "?")
    qs = c["ltm"]
    if len(qs) != 4:
        raise ValidationError(f"{t}: ltm needs exactly 4 quarters, got {len(qs)}")
    money = sorted({k for q in qs for k, v in q.items() if isinstance(v, (int, float))})
    merged = {}
    for k in money:
        missing = [i for i, q in enumerate(qs) if k not in q]
        if missing:
            raise ValidationError(f"{t}: ltm field {k} is missing in quarter(s) {missing}")
        merged[k] = sum(q[k] for q in qs)
    metals = {}
    for q in qs:
        for m in q.get("metals", []):
            d = metals.setdefault(m["metal"], {"metal": m["metal"], "units": 0.0, "value": 0.0})
            d["units"] += m["units"]; d["value"] += m["units"] * m["realised"]
            for extra in ("aisc", "royalty"):
                if extra in m:
                    d[extra] = m[extra]  # latest quarter's figure
    if metals:
        c["metals"] = [{**{k: v for k, v in d.items() if k != "value"}, "realised": d["value"] / d["units"]}
                       for d in metals.values() if d["units"]]
    c["earnings_latest_quarter"] = c.get("earnings")
    c["earnings"] = merged
    c["period"]["per_year"] = 1
    c["period"]["label"] = f"LTM to {c['period']['end'].isoformat()}"
    c.setdefault("assumptions", []).append("Last 12 months: the four latest reported quarters added up (not the latest quarter × 4)")
    return c




def _folder_name(folder: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", folder):
        raise ValidationError(f"folder name must be letters, digits, '-' or '_', got {folder!r}")
    return folder


def companies_folder(folder: str | None = None) -> Path:
    """Where company files live: data/companies, or data/<folder>/companies for a separate universe such as nifty50."""
    return ROOT / "data" / _folder_name(folder) / "companies" if folder else ROOT / "data" / "companies"


def output_folder(folder: str | None = None) -> Path:
    """Where results go: output/, or output/<folder>/."""
    return ROOT / "output" / _folder_name(folder) if folder else ROOT / "output"


def reports_folder() -> Path:
    """reports/ – the latest report for each list under a fixed name. Git tracks it and GitHub Pages publishes it;
    the dated copies stay in output/, which git ignores."""
    return ROOT / "reports"


def publish(dated: Path, list_name: str | None, kind: str) -> Path:
    """Copies a dated report from output/ to reports/<list><kind>, e.g. reports/core.html, replacing the previous one."""
    import shutil  # noqa: PLC0415
    src = Path(dated).resolve()
    private_dirs = [(ROOT / "data" / "private").resolve(), (ROOT / "output" / "private").resolve()]
    if src.parent.name == "private" or any(d == src or d in src.parents for d in private_dirs) or "private" in (list_name or "").lower():
        raise ValidationError(f"refusing to publish a private file: {dated}")   # private research never reaches reports/
    target = reports_folder() / f"{(list_name or 'all').lower()}{kind}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(dated, target)
    return target


def publish_dir(src: Path, name: str) -> Path:
    """Copies a folder of report files (a multi-page report's company pages, or its assets) to reports/<name>/,
    replacing what was there so pages of companies that left a list do not linger."""
    import shutil  # noqa: PLC0415
    src = Path(src).resolve()
    private_dirs = [(ROOT / "data" / "private").resolve(), (ROOT / "output" / "private").resolve()]
    if any(d == src or d in src.parents for d in private_dirs) or "private" in name.lower():
        raise ValidationError(f"refusing to publish a private folder: {src}")
    target = reports_folder() / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target)
    return target


def company_folders() -> dict[str, Path]:
    """Every folder holding company files, keyed by its path relative to the project."""
    found = [ROOT / "data" / "companies"] + sorted((ROOT / "data").glob("*/companies"))
    return {str(p.relative_to(ROOT)): p for p in found if p.is_dir()}


def list_folder(name: str, folder: Path | None = None) -> str | None:
    """The `folder:` a list file asks for, if any."""
    folder = folder or ROOT / "data" / "lists"
    return yaml.safe_load(open(folder / f"{name.lower()}.yaml")).get("folder")


def load_companies(folder: Path | None = None) -> dict[str, dict]:
    folder = folder or ROOT / "data" / "companies"
    out = {}
    for f in sorted(folder.glob("*.yaml")):
        c = validate_company(yaml.safe_load(open(f)), f.stem)
        out[c["ticker"].upper()] = c
    return out


def load_etf(name: str, folder: Path | None = None) -> dict:
    folder = folder or ROOT / "data" / "etfs"
    e = yaml.safe_load(open(folder / f"{name.lower()}.yaml"))
    e["price"]["date"] = _date(e["price"]["date"], "price.date", name)
    return e


def load_list_entries(name: str, folder: Path | None = None) -> list[dict]:
    """Every entry of a list as a dict with at least `ticker` (upper case); other fields – yahoo, name, industry,
    quantity – are kept as written."""
    folder = folder or ROOT / "data" / "lists"
    d = yaml.safe_load(open(folder / f"{name.lower()}.yaml"))
    return [{**x, "ticker": x["ticker"].upper()} if isinstance(x, dict) else {"ticker": str(x).upper()} for x in d["tickers"]]


def with_screen_rules(cfg: dict, list_name: str | None) -> dict:
    """`cfg` with the list's own growth-screen rules (list setting `screen_rules:`, e.g. the Nifty 50's large-cap
    thresholds) laid over `growth_screen` – a copy; without them, `cfg` itself."""
    rules = list_settings(list_name).get("screen_rules") if list_name else None
    return dict(cfg, growth_screen={**cfg["growth_screen"], **rules}) if rules else cfg


def list_settings(name: str, folder: Path | None = None) -> dict:
    """A list's settings – everything in its file except the tickers (name, folder, screen, ...)."""
    folder = folder or ROOT / "data" / "lists"
    d = yaml.safe_load(open(folder / f"{name.lower()}.yaml"))
    return {k: v for k, v in d.items() if k != "tickers"}


def load_list(name: str, folder: Path | None = None) -> list[str]:
    return [x["ticker"] for x in load_list_entries(name, folder)]


