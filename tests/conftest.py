"""Shared test setup: no test may reach Yahoo or Screener.in."""
import pytest

from valuescreen import growth_data


@pytest.fixture(autouse=True)
def no_network_fetches(monkeypatch):
    monkeypatch.setattr(growth_data, "collect", lambda entries, *args, **kwargs: {})
