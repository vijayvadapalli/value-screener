"""update_results.py's Claude and Gemini providers, run against fake clients. No network calls, no API keys."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("update_results", ROOT / "tools" / "update_results.py")
ur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ur)

AEM = ROOT / "tests" / "fixtures" / "nov2026" / "companies" / "aem.yaml"
CURRENT = yaml.safe_load(AEM.read_text(encoding="utf-8"))


def answer(**changes):
    new = copy.deepcopy(CURRENT)
    new["period"].update(label="Q4-2026", end="2026-12-31", reported="2027-02-11")
    new["earnings"]["da"] = 470.0
    new["sources"].append("AEM Q4-2026 results")
    base = {"status": "updated", "summary": "Q4 results found.", "updated_yaml": yaml.safe_dump(new, sort_keys=False),
            "changes": [{"field": "earnings.da", "source_url": "https://example.com/q4", "quote": "D&A 470"}], "unresolved": []}
    return {**base, **changes}


# ---------------------------------------------------------------- shared checks
def test_validate_result_accepts_a_good_answer_and_fills_in_missing_change_fields():
    result = ur.validate_result(answer(changes=[{"field": "earnings.da"}, "junk"]))
    assert result["changes"] == [{"field": "earnings.da", "source_url": "", "quote": ""}]


@pytest.mark.parametrize("bad", [None, [], {}, {"status": "updated"}, answer(status="maybe"), answer(changes="x"),
                                 answer(updated_yaml=None)])
def test_validate_result_rejects_malformed_answers(bad):
    with pytest.raises(ur.UpdateFailed):
        ur.validate_result(bad)


# ---------------------------------------------------------------- Gemini
genai = pytest.importorskip("google.genai")
from google.genai import errors as genai_errors  # noqa: E402


class FakeModels:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def list(self):
        return [NS(name="models/gemini-9-flash"), NS(name="models/gemini-9-pro"), NS(name="models/other")]


def reply(text, queries=("q1", "q2"), pages=(("Investors", "https://x/q4"),), finish="STOP"):
    chunks = [NS(web=NS(title=t, domain="x", uri=u)) for t, u in pages]
    grounding = NS(web_search_queries=list(queries), grounding_chunks=chunks)
    return NS(text=text, usage_metadata=NS(prompt_token_count=100, candidates_token_count=40, thoughts_token_count=10),
              candidates=[NS(finish_reason=finish, grounding_metadata=grounding)], prompt_feedback=None)


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    provider = ur.GeminiProvider()
    provider.client = NS(models=FakeModels([]))
    return provider


def test_gemini_research_searches_with_google_and_lists_the_pages_it_used(gemini):
    gemini.client.models.replies = [reply("Q4 D&A was 470.")]
    usage = {"input": 0, "output": 0, "searches": 0}
    notes = gemini.research("ticker: AEM", usage)
    call = gemini.client.models.calls[0]
    assert call["config"].tools[0].google_search is not None
    assert "ticker: AEM" in call["contents"] and call["config"].system_instruction == ur.CONVENTIONS
    assert notes.startswith("Q4 D&A was 470.") and "- Investors: https://x/q4" in notes
    assert usage == {"input": 100, "output": 50, "searches": 2}  # reasoning tokens count as output


def test_gemini_extract_asks_for_json_without_search_and_parses_it(gemini):
    gemini.client.models.replies = [reply(json.dumps(answer()))]
    result = gemini.extract("ticker: AEM", "notes", {"input": 0, "output": 0, "searches": 0})
    config = gemini.client.models.calls[0]["config"]
    assert config.response_mime_type == "application/json" and config.response_json_schema == ur.RESULT_SCHEMA
    assert not config.tools
    assert result["status"] == "updated"


def test_gemini_default_model_can_be_overridden(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert ur.GeminiProvider().model == ur.GEMINI_MODEL
    monkeypatch.setenv("GEMINI_MODEL", "from-env")
    assert ur.GeminiProvider().model == "from-env"
    assert ur.GeminiProvider("from-flag").model == "from-flag"


def test_gemini_without_a_key_stops_with_instructions(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        ur.GeminiProvider()


@pytest.mark.parametrize("bad", ["not json", ""])
def test_gemini_invalid_json_is_a_failure_not_a_crash(gemini, bad):
    gemini.client.models.replies = [reply(bad or "x")]
    gemini.client.models.replies[0].text = bad
    with pytest.raises(ur.UpdateFailed):
        gemini.extract("c", "n", {"input": 0, "output": 0, "searches": 0})


def test_gemini_empty_or_truncated_answers_are_failures(gemini):
    usage = {"input": 0, "output": 0, "searches": 0}
    blocked = reply("x")
    blocked.text, blocked.candidates = None, []
    gemini.client.models.replies = [blocked, reply("partial", finish="FinishReason.MAX_TOKENS")]
    with pytest.raises(ur.UpdateFailed, match="no text"):
        gemini.research("c", usage)
    with pytest.raises(ur.UpdateFailed, match="cut off"):
        gemini.research("c", usage)


@pytest.mark.parametrize("code, body, expected, exception", [
    (403, "Permission denied", "API key was rejected", ur.AuthFailed),
    (400, "API key not valid. Please pass a valid API key.", "API key was rejected", ur.AuthFailed),
    (429, "Quota exceeded", "free tier", ur.UpdateFailed),
    (500, "Internal error", "API error 500", ur.UpdateFailed),
    (400, "Invalid argument for tool", "API error 400: Invalid argument", ur.UpdateFailed),
])
def test_gemini_api_errors_become_clear_messages(gemini, code, body, expected, exception):
    error = genai_errors.APIError(code, {"error": {"code": code, "message": body, "status": "X"}})
    with pytest.raises(exception, match=expected):
        with gemini.errors():
            raise error


def test_gemini_unknown_model_lists_models_that_exist(gemini):
    error = genai_errors.APIError(404, {"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}})
    with pytest.raises(ur.UpdateFailed) as caught:
        with gemini.errors():
            raise error
    assert "gemini-9-flash" in str(caught.value) and "other" not in str(caught.value) and "--model" in str(caught.value)


def test_gemini_network_errors_are_failures(gemini):
    with pytest.raises(ur.UpdateFailed, match="could not reach"):
        with gemini.errors():
            raise gemini.httpx.ConnectError("down")


# ---------------------------------------------------------------- the whole update, with either provider
class StubProvider:
    name = "Stub"

    def __init__(self, result):
        self.result = result

    def errors(self):
        import contextlib
        return contextlib.nullcontext()

    def research(self, current_text, usage):
        usage["searches"] += 1
        return "notes"

    def extract(self, current_text, notes, usage):
        return self.result


@pytest.fixture
def company_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ur, "BACKUPS", tmp_path / "backups")
    path = tmp_path / "aem.yaml"
    path.write_text(AEM.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_dry_run_shows_the_update_and_saves_nothing(company_file, capsys):
    before = company_file.read_text(encoding="utf-8")
    assert ur.update_company(StubProvider(answer()), company_file, dry_run=True) == "proposed"
    assert company_file.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "with Stub" in out and "+  da: 470.0" in out and "https://example.com/q4" in out


def test_an_approved_update_is_saved_with_a_backup(company_file, monkeypatch):
    monkeypatch.setattr(ur, "approved", lambda ticker: True)
    assert ur.update_company(StubProvider(answer()), company_file, dry_run=False) == "saved"
    assert yaml.safe_load(company_file.read_text(encoding="utf-8"))["earnings"]["da"] == 470.0
    assert len(list(ur.BACKUPS.iterdir())) == 1


def test_a_declined_update_changes_nothing(company_file, monkeypatch):
    monkeypatch.setattr(ur, "approved", lambda ticker: False)
    assert ur.update_company(StubProvider(answer()), company_file, dry_run=False) == "declined"
    assert yaml.safe_load(company_file.read_text(encoding="utf-8"))["earnings"]["da"] == CURRENT["earnings"]["da"]


def test_a_malformed_answer_fails_cleanly(company_file):
    with pytest.raises(ur.UpdateFailed):
        ur.update_company(StubProvider({"status": "updated"}), company_file, dry_run=True)


def test_a_blocked_update_is_not_saved(company_file):
    bad = yaml.safe_load(answer()["updated_yaml"])
    bad["currency"] = "CAD"
    assert ur.update_company(StubProvider(answer(updated_yaml=yaml.safe_dump(bad))), company_file, dry_run=False) == "blocked"


def test_no_new_results_is_reported(company_file):
    assert ur.update_company(StubProvider(answer(status="no_new_results", updated_yaml="")), company_file, True) == "no new results"


# ---------------------------------------------------------------- Claude, through the real SDK against a fake server
def test_claude_provider_resumes_a_paused_search_and_returns_structured_output(company_file):
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx")
    bodies = []

    def sse(blocks, stop):
        events = [("message_start", {"type": "message_start", "message": {
            "id": "m", "type": "message", "role": "assistant", "model": "x", "content": [], "stop_reason": None,
            "stop_sequence": None, "usage": {"input_tokens": 100, "output_tokens": 0}}})]
        for i, block in enumerate(blocks):
            if block["type"] == "text":
                events += [("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": {"type": "text", "text": ""}}),
                           ("content_block_delta", {"type": "content_block_delta", "index": i,
                                                    "delta": {"type": "text_delta", "text": block["text"]}})]
            else:
                events.append(("content_block_start", {"type": "content_block_start", "index": i, "content_block": block}))
            events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
        events += [("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                      "usage": {"output_tokens": 50, "server_tool_use": {"web_search_requests": 2}}}),
                   ("message_stop", {"type": "message_stop"})]
        return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)

    def handler(request):
        bodies.append(json.loads(request.content))
        n = len(bodies)
        if n == 1:
            blocks, stop = [{"type": "text", "text": "part one. "},
                            {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "x"}}], "pause_turn"
        elif n == 2:
            blocks, stop = [{"type": "text", "text": "part two."}], "end_turn"
        else:
            blocks, stop = [{"type": "text", "text": json.dumps(answer())}], "end_turn"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(blocks, stop))

    provider = ur.ClaudeProvider.__new__(ur.ClaudeProvider)
    provider.anthropic, provider.model = anthropic, ur.CLAUDE_MODEL
    provider.client = anthropic.Anthropic(api_key="test", http_client=anthropic.DefaultHttpxClient(
        transport=httpx.MockTransport(handler)))

    assert ur.update_company(provider, company_file, dry_run=True) == "proposed"
    first, second, third = bodies
    assert first["model"] == ur.CLAUDE_MODEL and first["fallbacks"] == "default" and first["stream"] is True
    assert [t["type"] for t in first["tools"]] == ["web_search_20260209", "web_fetch_20260209"]
    assert [m["role"] for m in second["messages"]] == ["user", "assistant"]  # the paused turn was resumed
    assert "tools" not in third and third["output_config"]["format"]["type"] == "json_schema"
    assert "part one. part two." in third["messages"][0]["content"]


def test_claude_errors_become_clear_messages():
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx")
    provider = ur.ClaudeProvider.__new__(ur.ClaudeProvider)
    provider.anthropic = anthropic
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def status_error(cls, code):
        return cls("boom", response=httpx.Response(code, request=request), body=None)

    with pytest.raises(ur.AuthFailed, match="rejected"):
        with provider.errors():
            raise status_error(anthropic.AuthenticationError, 401)
    with pytest.raises(ur.UpdateFailed, match="rate limited"):
        with provider.errors():
            raise status_error(anthropic.RateLimitError, 429)
    with pytest.raises(ur.UpdateFailed, match="API error 500"):
        with provider.errors():
            raise status_error(anthropic.InternalServerError, 500)
    with pytest.raises(ur.AuthFailed, match="No API credentials"):
        with provider.errors():
            raise TypeError("Could not resolve authentication method")
    with pytest.raises(TypeError, match="unrelated"):
        with provider.errors():
            raise TypeError("unrelated")
