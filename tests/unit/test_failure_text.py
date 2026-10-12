"""Error text that marks a transient failure (`classify_error_text`)."""

from atlas.jobs.pacing import classify_error_text


def test_the_chatgpt_bridge_s_unknown_items_error_is_an_outage_to_retry() -> None:
    text = "litellm.InternalServerError: Unknown items in responses API response: [{'type': 'x'}]"

    assert classify_error_text(text) == "unavailable"


def test_an_ordinary_error_is_not_classified() -> None:
    assert classify_error_text("the answer was not valid JSON") is None
