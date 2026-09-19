import pytest

from chesterton.llm.client import (
    EXECUTION_MODEL,
    REASONING_MODEL,
    SYNTHESIS_MODEL,
    NemotronClient,
    TruncatedResponse,
)


class _FakeCompletions:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


class _Reply:
    def __init__(self, content, finish_reason="stop"):
        message = type("M", (), {"content": content})()
        choice = type("C", (), {"message": message, "finish_reason": finish_reason})()
        self.choices = [choice]


def a_client(reply) -> tuple[NemotronClient, _FakeCompletions]:
    client = NemotronClient(api_key="unused")
    completions = _FakeCompletions(reply)
    client._chat = completions  # inject; no network in unit tests
    return client, completions


def test_the_confirmed_model_ids_are_exact():
    # Casing differs between all three and was verified against the live
    # /v1/models listing. Inferring them from a catalogue produced wrong values.
    assert EXECUTION_MODEL == "nvidia/Nemotron-3_5-Lightning"
    assert REASONING_MODEL == "nvidia/nemotron-3-super-120b-a12b"
    assert SYNTHESIS_MODEL == "nvidia/Nemotron-3-Ultra-550b-a55b"


async def test_thinking_is_disabled_by_default():
    # Measured: thinking on costs 64 reasoning tokens for a trivial reply.
    client, completions = a_client(_Reply('{"ok": true}'))

    await client.complete("hi", model=EXECUTION_MODEL)

    kwargs = completions.calls[0]
    assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


async def test_thinking_can_be_enabled_for_judgement_calls():
    client, completions = a_client(_Reply("considered"))

    await client.complete("hi", model=REASONING_MODEL, thinking=True)

    kwargs = completions.calls[0]
    assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


async def test_a_truncated_response_raises_instead_of_returning_thoughts():
    # Measured: a call cut off mid-reasoning returns partial chain-of-thought
    # as content. Parsing that yields neither JSON nor an answer.
    client, _ = a_client(_Reply("The user wants a single", finish_reason="length"))

    with pytest.raises(TruncatedResponse, match="max_tokens"):
        await client.complete("hi", model=EXECUTION_MODEL)


async def test_content_is_returned_stripped():
    # Measured: a complete response can carry leading whitespace before JSON.
    client, _ = a_client(_Reply('\n\n{"ok": true}'))

    assert await client.complete("hi", model=EXECUTION_MODEL) == '{"ok": true}'
