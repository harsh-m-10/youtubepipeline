"""Groq client wrapper: JSON mode, retries with backoff, model fallback.
Provider-abstracted so Gemini Flash can be swapped in if Groq's free tier changes."""

import json
import logging
import time

from groq import Groq, RateLimitError, APIError

from src import config

log = logging.getLogger(__name__)

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def complete(
    system: str,
    user: str,
    json_mode: bool = True,
    temperature: float = config.LLM_TEMPERATURE,
    max_tokens: int = 4096,
) -> str:
    """Single completion with retry across models. Returns raw text."""
    last_exc: Exception | None = None
    for model in config.LLM_MODELS:
        for attempt in range(3):
            try:
                resp = _get_client().chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"} if json_mode else None,
                )
                return resp.choices[0].message.content
            except RateLimitError as exc:
                last_exc = exc
                wait = 15 * (attempt + 1)
                log.warning("Rate limited on %s, waiting %ss", model, wait)
                time.sleep(wait)
            except APIError as exc:
                last_exc = exc
                log.warning("API error on %s: %s", model, exc)
                break  # try next model
    raise RuntimeError(f"All LLM attempts failed: {last_exc}")


def complete_json(
    system: str,
    user: str,
    temperature: float = config.LLM_TEMPERATURE,
    max_tokens: int = 4096,
) -> dict:
    """Completion parsed as JSON, with one reparse-retry on malformed output."""
    for attempt in range(2):
        raw = complete(system, user, json_mode=True, temperature=temperature, max_tokens=max_tokens)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Malformed JSON from LLM (attempt %d), retrying", attempt + 1)
    raise RuntimeError("LLM returned malformed JSON twice")
