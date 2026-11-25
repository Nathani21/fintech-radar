import io
import json
import urllib.error
from datetime import datetime, timezone

import pytest

import radar.ai as ai
from radar.ai import (
    AIError,
    build_prompt,
    build_request,
    call_gemini,
    extract_text,
    parse_ranking,
    rank_news,
)

NOW = datetime(2026, 11, 22, 11, 0, tzinfo=timezone.utc)


def make_item(title, source="TechCabal", companies=("Paystack",)):
    """A news item like collect_news returns."""
    return {
        "title": title,
        "link": "https://example.com/" + title.replace(" ", "-"),
        "source": source,
        "published": NOW,
        "companies": list(companies),
    }


ITEMS = [make_item("Story A"), make_item("Story B", source=""), make_item("Story C")]


def reply(one_thing="Big day.", picks=({"id": 0, "why": "Matters."},)):
    """A model reply as JSON text."""
    return json.dumps({"one_thing": one_thing, "picks": list(picks)})


def gemini_response(text, **extra):
    """A generateContent response wrapping `text`."""
    return {"candidates": [{"content": {"parts": [{"text": text}]}, **extra}]}


# --- build_prompt / build_request


def test_build_prompt_numbers_headlines_from_zero():
    prompt = build_prompt(ITEMS, 2)
    assert "0. Story A (TechCabal; found via Paystack)" in prompt
    assert "1. Story B (unknown source; found via Paystack)" in prompt
    assert "Choose up to 2 headlines" in prompt
    assert '{"one_thing": "...", "picks": [{"id": 3, "why": "..."}]}' in prompt


def test_prompt_prefers_startups_and_limits_government_news():
    prompt = build_prompt(ITEMS, 5)
    assert "Prefer startup and product news" in prompt
    assert "at most one government or regulation story" in prompt
    assert "Skip government support schemes" in prompt


def test_build_request_asks_for_json():
    body = build_request("hello")
    assert body["contents"][0]["parts"][0]["text"] == "hello"
    assert body["generationConfig"]["responseMimeType"] == "application/json"


# --- extract_text


def test_extract_text_joins_parts_and_skips_thoughts():
    parts = [{"text": "thinking", "thought": True}, {"text": '{"a"'}, {"text": ": 1}"}]
    response = {"candidates": [{"content": {"parts": parts}}]}
    assert extract_text(response) == '{"a": 1}'


def test_extract_text_blocked_prompt():
    with pytest.raises(AIError, match="blocked .SAFETY."):
        extract_text({"promptFeedback": {"blockReason": "SAFETY"}})


@pytest.mark.parametrize("response", [{}, {"candidates": []}])
def test_extract_text_no_candidates(response):
    with pytest.raises(AIError, match="no candidates"):
        extract_text(response)


def test_extract_text_empty_reply_reports_finish_reason():
    with pytest.raises(AIError, match="MAX_TOKENS"):
        extract_text(gemini_response("  ", finishReason="MAX_TOKENS"))


# --- parse_ranking


def test_parse_ranking_valid():
    text = reply("CBN moved.", [{"id": 2, "why": "  Rules   change. "}, {"id": 0, "why": "Funding."}])
    one_thing, picks = parse_ranking(text, 3, 5)
    assert one_thing == "CBN moved."
    assert picks == [(2, "Rules change."), (0, "Funding.")]


def test_parse_ranking_strips_code_fence():
    one_thing, picks = parse_ranking("```json\n" + reply() + "\n```", 3, 5)
    assert picks == [(0, "Matters.")]


@pytest.mark.parametrize("text", ["not json", "```", "[]", '{"picks": "nope"}', "{}"])
def test_parse_ranking_rejects_wrong_shape(text):
    with pytest.raises(AIError):
        parse_ranking(text, 3, 5)


def test_parse_ranking_skips_bad_picks():
    picks = [
        {"id": 7, "why": "out of range"},
        {"id": -1, "why": "negative"},
        {"id": True, "why": "bool"},
        {"id": "1", "why": "string id"},
        {"id": 1, "why": ""},
        {"id": 1},
        "not a dict",
        {"id": 1, "why": "good"},
        {"id": 1, "why": "duplicate"},
    ]
    _, kept = parse_ranking(reply(picks=picks), 3, 5)
    assert kept == [(1, "good")]


def test_parse_ranking_respects_limit():
    picks = [{"id": i, "why": "x"} for i in range(3)]
    _, kept = parse_ranking(reply(picks=picks), 3, 2)
    assert [index for index, _ in kept] == [0, 1]


def test_parse_ranking_no_usable_picks():
    with pytest.raises(AIError, match="no usable picks"):
        parse_ranking(reply(picks=[]), 3, 5)


def test_parse_ranking_shortens_long_text():
    one_thing, kept = parse_ranking(reply("w " * 300, [{"id": 0, "why": "x" * 500}]), 3, 5)
    assert len(kept[0][1]) == ai.MAX_WHY_LENGTH and kept[0][1].endswith("…")
    assert len(one_thing) <= ai.MAX_ONE_THING_LENGTH


def test_parse_ranking_missing_one_thing_is_fine():
    one_thing, _ = parse_ranking(json.dumps({"picks": [{"id": 0, "why": "x"}]}), 3, 5)
    assert one_thing == ""


# --- rank_news


def test_rank_news_returns_items_in_ai_order_with_why():
    asked = []

    def fake_ask(prompt, api_key, model):
        asked.append((api_key, model))
        return reply("Top.", [{"id": 2, "why": "C first."}, {"id": 0, "why": "Then A."}])

    shown, one_thing = rank_news(ITEMS, 5, "key", "model-x", 40, ask=fake_ask)
    assert [item["title"] for item in shown] == ["Story C", "Story A"]
    assert shown[0]["why"] == "C first."
    assert one_thing == "Top."
    assert asked == [("key", "model-x")]
    assert "why" not in ITEMS[2]  # the input items are not changed


def test_rank_news_only_sends_max_candidates():
    prompts = []

    def fake_ask(prompt, api_key, model):
        prompts.append(prompt)
        return reply()

    rank_news(ITEMS, 5, "key", "m", 2, ask=fake_ask)
    assert "Story B" in prompts[0] and "Story C" not in prompts[0]


def test_rank_news_rejects_id_beyond_candidates():
    def fake_ask(prompt, api_key, model):
        return reply(picks=[{"id": 2, "why": "only 2 candidates were sent"}])

    with pytest.raises(AIError, match="no usable picks"):
        rank_news(ITEMS, 5, "key", "m", 2, ask=fake_ask)


@pytest.mark.parametrize("items, limit", [([], 5), (ITEMS, 0)])
def test_rank_news_skips_the_call_when_nothing_to_do(items, limit):
    def exploding_ask(prompt, api_key, model):
        raise AssertionError("should not call the AI")

    assert rank_news(items, limit, "key", "m", 40, ask=exploding_ask) == ([], "")


# --- call_gemini (urlopen replaced, so nothing leaves the machine)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_call_gemini_sends_key_in_header_not_url(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["key"] = request.get_header("X-goog-api-key")
        seen["body"] = json.loads(request.data)
        return FakeResponse(json.dumps(gemini_response("hello")).encode())

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
    assert call_gemini("prompt", "SECRET-KEY", "gemini-3.1-flash-lite") == "hello"
    assert seen["url"].endswith("/models/gemini-3.1-flash-lite:generateContent")
    assert "SECRET-KEY" not in seen["url"]
    assert seen["key"] == "SECRET-KEY"
    assert seen["body"]["contents"][0]["parts"][0]["text"] == "prompt"


def test_call_gemini_http_error_gives_google_message(monkeypatch):
    def fake_urlopen(request, timeout):
        body = io.BytesIO(json.dumps({"error": {"message": "models/x is not found"}}).encode())
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, body)

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(AIError, match="HTTP 404: models/x is not found") as error:
        call_gemini("prompt", "SECRET-KEY", "x")
    assert "SECRET-KEY" not in str(error.value)


def test_call_gemini_network_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(AIError, match="could not reach Gemini .TimeoutError."):
        call_gemini("prompt", "key", "m", sleep=lambda seconds: None)


def test_call_gemini_bad_json_response(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(b"<html>")

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(AIError, match="not the expected JSON"):
        call_gemini("prompt", "key", "m")



# --- retries


def http_error(code, message="busy"):
    """A urllib HTTPError like Google sends, with a JSON error body."""
    body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())
    return urllib.error.HTTPError("https://example.test", code, "error", {}, body)


def scripted_urlopen(monkeypatch, outcomes):
    """Make urlopen return or raise each outcome in turn; returns the list of calls."""
    calls = []

    def fake_urlopen(request, timeout):
        outcome = outcomes[len(calls)]
        calls.append(request)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(json.dumps(gemini_response(outcome)).encode())

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_busy_then_ok_retries_once(monkeypatch):
    calls = scripted_urlopen(monkeypatch, [http_error(503), "hello"])
    waits = []
    assert call_gemini("prompt", "key", "m", sleep=waits.append) == "hello"
    assert len(calls) == 2
    assert waits == [10]


def test_network_drop_then_ok(monkeypatch):
    scripted_urlopen(monkeypatch, [TimeoutError("timed out"), "hello"])
    assert call_gemini("prompt", "key", "m", sleep=lambda seconds: None) == "hello"


def test_still_busy_gives_up_after_three_tries(monkeypatch):
    calls = scripted_urlopen(
        monkeypatch, [http_error(503), http_error(429), http_error(503, "high demand")]
    )
    waits = []
    with pytest.raises(AIError, match="HTTP 503: high demand .gave up after 3 tries.") as error:
        call_gemini("prompt", "SECRET-KEY", "m", sleep=waits.append)
    assert len(calls) == 3
    assert waits == [10, 30]
    assert "SECRET-KEY" not in str(error.value)


@pytest.mark.parametrize("code", [400, 403, 404])
def test_errors_that_waiting_cannot_fix_are_not_retried(monkeypatch, code):
    calls = scripted_urlopen(monkeypatch, [http_error(code, "nope"), "hello"])
    waits = []
    with pytest.raises(AIError, match=f"HTTP {code}: nope$"):
        call_gemini("prompt", "key", "m", sleep=waits.append)
    assert len(calls) == 1
    assert waits == []


def test_bad_reply_is_not_retried(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(b"<html>")

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(AIError, match="not the expected JSON"):
        call_gemini("prompt", "key", "m", sleep=lambda seconds: None)
    assert len(calls) == 1


def test_no_waits_means_one_try(monkeypatch):
    calls = scripted_urlopen(monkeypatch, [http_error(503)])
    with pytest.raises(AIError, match="gave up after 1 try"):
        call_gemini("prompt", "key", "m", waits=())
    assert len(calls) == 1
