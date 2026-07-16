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
        # max_retries=0: we own the retry/backoff logic below (no nested SDK retries)
        _client = Groq(api_key=config.GROQ_API_KEY, max_retries=0)
    return _client


def _retry_after(exc: RateLimitError) -> float:
    """Seconds Groq asks us to wait, from the Retry-After header. Falls back to
    a full TPM window when the header is missing — short waits just thrash."""
    try:
        hdr = exc.response.headers.get("retry-after")
        if hdr is not None:
            return min(float(hdr) + 2, config.LLM_MAX_RATE_WAIT)
    except Exception:
        pass
    return config.LLM_MAX_RATE_WAIT


def complete(
    system: str,
    user: str,
    json_mode: bool = True,
    temperature: float = config.LLM_TEMPERATURE,
    max_tokens: int = 4096,
    model: str | None = None,
) -> str:
    """Single completion. Tries `model` first (default: the big model), then the
    others as fallback. On rate limits, waits the server-suggested time."""
    models = [model] + [m for m in config.LLM_MODELS if m != model] if model \
        else list(config.LLM_MODELS)
    last_exc: Exception | None = None
    for m in models:
        # gpt-oss are reasoning models: their hidden chain-of-thought counts
        # against max_tokens. At the default effort it can eat ~3500 of the
        # 4096 budget and truncate the JSON mid-string. Low effort is plenty
        # for these tasks (the pipeline ran on non-reasoning llamas before),
        # and max_tokens can't be raised — Groq charges prompt+max_tokens
        # against the TPM limit up front, so a bigger cap 429s every request.
        extra = {"reasoning_effort": "low"} if "gpt-oss" in m else {}
        for attempt in range(3):
            try:
                resp = _get_client().chat.completions.create(
                    model=m,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"} if json_mode else None,
                    **extra,
                )
                if resp.choices[0].finish_reason == "length":
                    log.warning("Output truncated at max_tokens on %s "
                                "(reasoning consumed the budget?)", m)
                return resp.choices[0].message.content
            except RateLimitError as exc:
                last_exc = exc
                wait = _retry_after(exc)
                log.warning("Rate limited on %s, waiting %.0fs", m, wait)
                time.sleep(wait)
            except APIError as exc:
                last_exc = exc
                log.warning("API error on %s: %s", m, exc)
                break  # try next model
    raise RuntimeError(f"All LLM attempts failed: {last_exc}")


def complete_json(
    system: str,
    user: str,
    temperature: float = config.LLM_TEMPERATURE,
    max_tokens: int = 4096,
    model: str | None = None,
) -> dict:
    """Completion parsed as JSON, with one reparse-retry on malformed output."""
    for attempt in range(2):
        raw = complete(system, user, json_mode=True, temperature=temperature,
                       max_tokens=max_tokens, model=model)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Malformed JSON from LLM (attempt %d), retrying", attempt + 1)
    raise RuntimeError("LLM returned malformed JSON twice")
