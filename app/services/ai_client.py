import asyncio
import logging
from typing import Optional, Tuple

from google import genai
from google.genai import errors, types

from app.config import settings

logger = logging.getLogger(__name__)

RETRY_DELAY = 2.0  # seconds before retrying a model that reported temporary overload

_client: Optional[genai.Client] = None


class AIUnavailableError(Exception):
    """Raised when no configured model could produce a usable answer.

    The message is safe to show to users; provider details are only logged.
    """


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


async def generate_with_fallback(
    contents,
    config: types.GenerateContentConfig,
    timeout: float,
    purpose: str,
) -> Tuple[types.GenerateContentResponse, str]:
    """Tries each configured generation model in order and returns (response, model_id).

    A model that answers 429 or 503 (temporary overload) gets one retry after a short pause.
    All attempts together stay within settings.AI_CALL_BUDGET seconds.

    Raises AIUnavailableError when every model fails or returns no text. It never
    invents a placeholder answer.
    """
    client = get_client()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.AI_CALL_BUDGET
    for model in settings.GENERATION_MODELS:
        for attempt in range(2):
            remaining = deadline - loop.time()
            if remaining <= 1:
                raise AIUnavailableError(f"AI {purpose} is temporarily unavailable.")
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(model=model, contents=contents, config=config),
                    timeout=min(timeout, remaining),
                )
                if response.text:
                    return response, model
                logger.warning("model returned empty text", extra={"purpose": purpose, "model": model})
                break
            except asyncio.TimeoutError:
                logger.warning("model call timed out", extra={"purpose": purpose, "model": model})
                break
            except Exception as e:
                logger.warning(
                    "model call failed",
                    extra={"purpose": purpose, "model": model, "error": type(e).__name__, "detail": str(e)[:300]},
                )
                if attempt == 0 and _is_temporary(e) and deadline - loop.time() > RETRY_DELAY + 1:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                break
    raise AIUnavailableError(f"AI {purpose} is temporarily unavailable.")


def _is_temporary(error: Exception) -> bool:
    return isinstance(error, errors.APIError) and error.code in (429, 503)


def hit_output_limit(response: types.GenerateContentResponse) -> bool:
    """True when the model stopped because it ran out of output tokens."""
    try:
        return response.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS
    except (AttributeError, IndexError, TypeError):
        return False
