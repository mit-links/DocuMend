"""OpenAI-compatible LLM client for DocuMend.

Connects to any OpenAI-compatible server (LM Studio, Ollama, vLLM, LocalAI, etc.)
with multilingual prompt constraints and sanitization.
"""

import asyncio
import logging
from typing import List, Optional
from openai import AsyncOpenAI

from app.core.sanitizer import sanitize_llm_output
from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert multilingual copyeditor.\n"
    "Correct ONLY spelling, grammar, and punctuation.\n"
    "Preserve the original language of the text (e.g., German, English, French, Spanish) - NEVER translate to another language.\n"
    "Do not alter tone, vocabulary, or sentence structure unless grammatically incorrect.\n"
    "Do not add commentary, notes, introductory phrases, or markdown fences.\n"
    "Return STRICTLY the corrected text and nothing else."
)


class LLMClient:
    """Manages asynchronous requests to any OpenAI-compatible LLM endpoint."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.default_base_url).rstrip("/")
        # Ensure base_url ends with /v1 if missing
        if not self.base_url.endswith("/v1") and not "/v1/" in self.base_url:
            self.base_url = f"{self.base_url}/v1"

        self.api_key = api_key or settings.default_api_key
        self.model = model or settings.default_model
        self.timeout = timeout or settings.request_timeout
        self.temperature = temperature if temperature is not None else settings.temperature

        self._client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )

    async def list_models(self) -> List[str]:
        """Fetch available models from the OpenAI-compatible endpoint."""
        try:
            response = await self._client.models.list()
            model_ids = [m.id for m in response.data if m.id]
            # Filter out non-chat models if obvious (e.g. embedding models)
            chat_models = [m for m in model_ids if not "embed" in m.lower()]
            return chat_models if chat_models else model_ids
        except Exception as e:
            logger.error(f"Error fetching models from {self.base_url}: {e}")
            raise

    async def correct_text(self, text: str, model_override: Optional[str] = None) -> str:
        """Send a single piece of text for spelling & grammar correction."""
        stripped = text.strip()
        if not stripped:
            return text

        active_model = model_override or self.model
        if not active_model:
            # If no model was specified, fetch the first available model
            models = await self.list_models()
            if not models:
                raise ValueError("No models available on the specified LLM server.")
            active_model = models[0]

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Text to correct:\n{stripped}"},
        ]

        # Retry with exponential backoff on transient errors
        max_retries = 2
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=active_model,
                    messages=messages,
                    temperature=self.temperature,
                )
                raw_content = response.choices[0].message.content or ""
                cleaned = sanitize_llm_output(raw_content, original_text=stripped)

                # Preserve leading/trailing whitespace from original text
                leading_ws = text[: len(text) - len(text.lstrip())]
                trailing_ws = text[len(text.rstrip()) :]
                return f"{leading_ws}{cleaned}{trailing_ws}"

            except Exception as e:
                last_error = e
                logger.warning(f"Inference attempt {attempt + 1} failed: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    logger.error(f"Inference failed after {max_retries + 1} attempts: {last_error}")
                    # Return original text on failure to prevent document corruption
                    return text

        return text
