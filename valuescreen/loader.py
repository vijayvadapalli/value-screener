"""Load and validate company, ETF, list and config files."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MODELS = {"producer", "cashflow", "developer", "physical", "growth"}


class ValidationError(ValueError):
    pass


def _date(x, field, ticker):
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x))
    except Exception as e:  # noqa: BLE001
        raise ValidationError(f"{ticker}: {field} must be a date YYYY-MM-DD, got {x!r}") from e


def load_config(path: Path | None = None) -> dict:
    cfg = yaml.safe_load(open(path or ROOT / "config.yaml"))
    cfg["as_of"] = _date(cfg["as_of"], "as_of", "config")
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
    m = c["model"]
    if m in ("producer", "cashflow", "growth") and "shares_m" not in c and "eps_per_period" not in c.get("earnings", {}):
        raise ValidationError(f"{t}: shares_m is required for model {m}")
    if m == "developer" and "npv_curve" not in c:
        raise ValidationError(f"{t}: developer model needs npv_curve")
    if m == "physical" and "holdings" not in c:
        raise ValidationError(f"{t}: physical model needs holdings")
    for x in c.get("metals", []):
        for f in ("metal", "units", "realised"):
            if f not in x:
                raise ValidationError(f"{t}: each metal needs '{f}'")
    c.setdefault("assumptions", [])
    c.setdefault("notes", [])
    c.setdefault("yahoo", c["ticker"])
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


def load_list(name: str, folder: Path | None = None) -> list[str]:
    folder = folder or ROOT / "data" / "lists"
    d = yaml.safe_load(open(folder / f"{name.lower()}.yaml"))
    return [x["ticker"].upper() if isinstance(x, dict) else str(x).upper() for x in d["tickers"]]


def fx(cfg: dict, frm: str, to: str) -> float:
    """Multiplier converting an amount in `frm` currency into `to` currency."""
    if frm == to:
        return 1.0
    table = cfg["fx_usd_per_unit"]
    if frm not in table or to not in table:
        raise ValidationError(f"FX rate needed for {frm}->{to}; add it to config.yaml fx_usd_per_unit")
    return table[frm] / table[to]
