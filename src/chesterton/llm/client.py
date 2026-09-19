"""Nemotron on Nebius Token Factory.

Every behaviour encoded here was measured against the live service on
2026-09-18 rather than read from a catalogue:

- Thinking is ON by default and costs real tokens — 64 for a reply as trivial
  as `{"ok": true}`. `enable_thinking: false` brings that to zero.
- On a COMPLETE response, reasoning does not appear in `content`; the content
  is clean, sometimes with leading whitespace.
- On a response truncated by `max_tokens` mid-reasoning, the partial thought
  IS the content. Nothing flags it except `finish_reason`, so parsing such a
  response yields neither JSON nor an answer. We raise instead.
"""

from __future__ import annotations

import os

#: Verified against GET /v1/models?verbose=true. Casing differs between all
#: three; do not infer these from a third-party catalogue.
EXECUTION_MODEL = "nvidia/Nemotron-3_5-Lightning"
REASONING_MODEL = "nvidia/nemotron-3-super-120b-a12b"
SYNTHESIS_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


class TruncatedResponse(RuntimeError):
    """The model ran out of budget before finishing."""


class NemotronClient:
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL) -> None:
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY", "")
        self.base_url = base_url
        self._chat = None

    def _completions(self):
        if self._chat is None:
            from openai import AsyncOpenAI

            self._chat = AsyncOpenAI(
                api_key=self.api_key, base_url=self.base_url
            ).chat.completions
        return self._chat

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int = 2048,
        thinking: bool = False,
    ) -> str:
        reply = await self._completions().create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
        )
        choice = reply.choices[0]
        if choice.finish_reason == "length":
            raise TruncatedResponse(
                f"{model} hit max_tokens ({max_tokens}) before finishing. Its "
                "content is partial reasoning, not an answer — raise max_tokens "
                "or disable thinking rather than parsing this."
            )
        return (choice.message.content or "").strip()
