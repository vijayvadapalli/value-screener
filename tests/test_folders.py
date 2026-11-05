"""A list can keep its company files and results in their own folders, apart from data/companies and output/."""
import shutil
from pathlib import Path

import pytest
import yaml

from valuescreen import cli, loader

FIXTURE = Path(__file__).parent / "fixtures" / "nov2026"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A tiny project: AEM in data/companies, MSFT and NEM in data/nifty50/companies, a list pointing at nifty50."""
    monkeypatch.setattr(loader, "ROOT", tmp_path)
    shutil.copy(FIXTURE / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "data" / "companies").mkdir(parents=True)
    (tmp_path / "data" / "nifty50" / "companies").mkdir(parents=True)
    (tmp_path / "data" / "lists").mkdir()
    shutil.copy(FIXTURE / "companies" / "aem.yaml", tmp_path / "data" / "companies")
    for name in ("msft", "nem"):
        shutil.copy(FIXTURE / "companies" / f"{name}.yaml", tmp_path / "data" / "nifty50" / "companies")
    (tmp_path / "data" / "lists" / "nifty50.yaml").write_text(yaml.safe_dump(
        {"name": "n", "folder": "nifty50", "tickers": [{"ticker": "MSFT", "yahoo": "MSFT"}, {"ticker": "NEM", "yahoo": "NEM"},
                                                       {"ticker": "TCS", "yahoo": "TCS.NS"}]}))
    (tmp_path / "data" / "lists" / "plain.yaml").write_text(yaml.safe_dump({"name": "p", "tickers": ["AEM"]}))
    return tmp_path


def test_folder_paths(project):
    assert loader.companies_folder() == project / "data" / "companies"
    assert loader.companies_folder("nifty50") == project / "data" / "nifty50" / "companies"
    assert loader.output_folder() == project / "output"
    assert loader.output_folder("nifty50") == project / "output" / "nifty50"


@pytest.mark.parametrize("bad", ["../etc", "a/b", "nifty 50", "..", "x/../y"])
def test_folder_names_cannot_leave_the_project(bad):
    with pytest.raises(loader.ValidationError):
        loader.companies_folder(bad)
    with pytest.raises(loader.ValidationError):
        loader.output_folder(bad)


def test_a_list_names_its_folder(project):
    assert loader.list_folder("nifty50") == "nifty50"
    assert loader.list_folder("plain") is None


def test_company_folders_finds_every_folder(project):
    assert list(loader.company_folders()) == ["data/companies", "data/nifty50/companies"]


def test_list_run_uses_the_lists_folder_for_companies_and_results(project, capsys):
    assert cli.main(["run", "--list", "nifty50"]) == 0
    text = capsys.readouterr().out
    assert "MSFT" in text and "NEM" in text and "AEM" not in text
    assert "no company file for: TCS" in text and "data/nifty50/companies/<ticker>.yaml" in text
    assert (project / "output" / "nifty50" / "ranked.csv").exists()
    assert (project / "output" / "nifty50" / "signals_log.csv").exists()
    assert not (project / "output" / "ranked.csv").exists()


def test_a_plain_list_still_uses_the_main_folders(project, capsys):
    assert cli.main(["run", "--list", "plain"]) == 0
    assert "AEM" in capsys.readouterr().out
    assert (project / "output" / "ranked.csv").exists()
    assert not (project / "output" / "nifty50").exists()


def test_folder_option_without_a_list(project, capsys):
    assert cli.main(["run", "--folder", "nifty50", "--all"]) == 0
    text = capsys.readouterr().out
    assert "MSFT" in text and "AEM" not in text
    assert (project / "output" / "nifty50" / "ranked.csv").exists()


def test_out_still_overrides_the_folder(project, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    assert cli.main(["run", "--list", "nifty50", "--out", str(elsewhere)]) == 0
    assert (elsewhere / "ranked.csv").exists() and not (project / "output" / "nifty50").exists()


def test_validate_checks_every_folder(project, capsys):
    assert cli.main(["validate"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("1 company files valid in data/companies: AEM")
    assert lines[1].startswith("2 company files valid in data/nifty50/companies: MSFT, NEM")


def test_validate_reports_an_invalid_file_in_any_folder(project):
    (project / "data" / "nifty50" / "companies" / "bad.yaml").write_text("ticker: BAD\n")
    with pytest.raises(loader.ValidationError, match="BAD: missing required field"):
        cli.main(["validate"])
