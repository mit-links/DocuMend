"""OpenAI-compatible LLM client for DocuMend.

Connects to any OpenAI-compatible server (LM Studio, Ollama, vLLM, LocalAI, etc.)
or remote cloud provider (Gemini, Claude, ChatGPT) with multilingual prompt
constraints, token tracking, and sanitization.
"""

import asyncio
import logging
import re
import time
from typing import Any, Optional

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.core.sanitizer import (
    parse_batched_output,
    preserve_whitespace,
    sanitize_llm_output,
)

logger = logging.getLogger(__name__)


class LLMResponse(str):
    """String subclass containing optional token usage and timing metadata."""

    completion_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    duration: float = 0.0

    def __new__(
        cls,
        text: str,
        completion_tokens: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        duration: float = 0.0,
    ) -> "LLMResponse":
        obj = str.__new__(cls, text)
        obj.completion_tokens = completion_tokens
        obj.prompt_tokens = prompt_tokens
        obj.duration = duration
        return obj


SYSTEM_PROMPT = (
    "You are an expert multilingual copyeditor.\n"
    "Correct ONLY spelling, grammar, and punctuation.\n"
    "Preserve the original language of the text (e.g., German, English, French, Spanish) - NEVER translate to another language.\n"
    "Do not alter tone, vocabulary, or sentence structure unless grammatically incorrect.\n"
    "Do not add commentary, notes, introductory phrases, or markdown fences.\n"
    "Do not generate reasoning, thoughts, or <think> tags. Directly output the corrected text.\n"
    "Return STRICTLY the corrected text and nothing else."
)

BATCH_SYSTEM_PROMPT = (
    "You are an expert multilingual copyeditor.\n"
    "Correct ONLY spelling, grammar, and punctuation for each numbered item below.\n"
    "Preserve the original language of each item (e.g., German, English, French, Spanish) - NEVER translate.\n"
    "Do not alter tone, vocabulary, or sentence structure unless grammatically incorrect.\n"
    "Do not add commentary, notes, introductory phrases, or markdown fences.\n"
    "Do not generate reasoning, thoughts, or <think> tags.\n"
    "Return EXACTLY the same number of items using the format:\n"
    "[1] <corrected text>\n"
    "[2] <corrected text>\n"
    "Return STRICTLY the numbered items and nothing else."
)

FATAL_ERROR_SUBSTRINGS = (
    "unloaded",
    "aborted",
    "not found",
    "does not exist",
    "invalid_request_error",
    "bad request",
    "invalid argument",
    "unauthorized",
    "authentication",
    "permission_denied",
)


def is_fatal_error(err: Exception) -> bool:
    """Determines if an inference error is unrecoverable without retrying.

    Args:
        err: Exception raised during LLM API communication.

    Returns:
        True if the error indicates a missing model, client error, or unrecoverable state.
    """
    err_str = str(err).lower()
    return any(substr in err_str for substr in FATAL_ERROR_SUBSTRINGS)


class LLMClient:
    """Manages asynchronous requests to any OpenAI-compatible LLM endpoint."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: Optional[float] = None,
    ) -> None:
        """Initializes the LLMClient.

        Args:
            base_url: LLM base URL endpoint.
            api_key: Optional API key for authenticated providers.
            model: Default model identifier to use.
            timeout: Request timeout in seconds.
            temperature: Sampling temperature for generation.
        """
        self.base_url = (base_url or settings.default_base_url).rstrip("/")
        # Ensure base_url ends with /v1 if missing (unless already an OpenAI-compatible path)
        if not (
            self.base_url.endswith("/v1")
            or "/v1/" in self.base_url
            or self.base_url.endswith("/openai")
        ):
            self.base_url = f"{self.base_url}/v1"

        self.api_key = api_key or settings.default_api_key
        self.model = model or settings.default_model
        self.timeout = timeout or settings.request_timeout
        self.temperature = temperature if temperature is not None else settings.temperature

        default_headers = {}
        if "anthropic.com" in self.base_url:
            default_headers["anthropic-version"] = "2023-06-01"
            if self.api_key:
                default_headers["x-api-key"] = self.api_key

        self._client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            default_headers=default_headers or None,
        )

    async def close(self) -> None:
        """Closes the underlying HTTP client and connection pool."""
        if hasattr(self, "_client") and self._client:
            await self._client.close()

    async def list_models(self) -> list[str]:
        """Fetches available models from the OpenAI-compatible endpoint.

        Returns:
            Sorted list of chat-compatible model identifiers.
        """
        try:
            response = await self._client.models.list()
            model_ids = [m.id for m in response.data if m.id]

            excluded_keywords = (
                "embed",
                "live",
                "imagen",
                "image",
                "dall-e",
                "tts",
                "whisper",
                "audio",
                "transcribe",
                "aqa",
                "realtime",
            )
            chat_models = []
            for mid in model_ids:
                clean_id = mid.removeprefix("models/") if mid.startswith("models/") else mid
                mid_lower = clean_id.lower()
                if not any(kw in mid_lower for kw in excluded_keywords):
                    chat_models.append(clean_id)

            if not chat_models:
                chat_models = [
                    m.removeprefix("models/") if m.startswith("models/") else m for m in model_ids
                ]

            def model_priority(name: str) -> tuple[int, int, str]:
                n = name.lower()
                is_fast = 0 if (re.search(r"\b(flash|mini|haiku)\b", n) and "preview" not in n and "exp" not in n) else 1
                is_standard = 0 if ("preview" not in n and "exp" not in n and "custom" not in n) else 1
                return (is_fast, is_standard, n)

            chat_models.sort(key=model_priority)
            return chat_models
        except Exception as e:
            logger.error(f"Failed to fetch models from {self.base_url}: {e}")
            raise

    async def eject_inactive_models(self) -> list[str]:
        """Eject or unload models from GPU memory in LM Studio or Ollama.

        Returns:
            List of successfully unloaded model identifiers.
        """
        unloaded = []
        host_base = self.base_url.split("/v1")[0].split("/openai")[0]

        # 1. Strategy for LM Studio
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                lm_res = await client.get(f"{host_base}/api/v0/models")
                if lm_res.status_code == 200:
                    data = lm_res.json()
                    models_list = data if isinstance(data, list) else data.get("data", [])
                    for m in models_list:
                        m_id = m.get("id") or m.get("key")
                        if m_id and m.get("loaded", False):
                            eject_res = await client.post(
                                f"{host_base}/api/v0/models/unload",
                                json={"model": m_id},
                            )
                            if eject_res.status_code in (200, 204):
                                logger.info(f"Unloaded LM Studio model from memory: {m_id}")
                                unloaded.append(m_id)
        except Exception as e:
            logger.debug(f"LM Studio model eject attempt skipped/failed: {e}")

        # 2. Strategy for Ollama
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                ollama_res = await client.get(f"{host_base}/api/ps")
                if ollama_res.status_code == 200:
                    data = ollama_res.json()
                    for m in data.get("models", []):
                        m_name = m.get("name") or m.get("model")
                        if m_name:
                            unload_res = await client.post(
                                f"{host_base}/api/generate",
                                json={"model": m_name, "keep_alive": 0},
                            )
                            if unload_res.status_code in (200, 204):
                                logger.info(f"Unloaded Ollama model from memory: {m_name}")
                                unloaded.append(m_name)
        except Exception as e:
            logger.debug(f"Ollama model eject attempt skipped/failed: {e}")

        return unloaded

    async def _resolve_active_model(self, model_override: Optional[str] = None) -> str:
        """Resolves and caches the active model to avoid redundant network queries."""
        if model_override:
            return model_override
        if self.model:
            return self.model
        models = await self.list_models()
        if not models:
            raise ValueError("No models available on the specified LLM server.")
        self.model = models[0]
        return self.model

    async def _call_chat_completions(
        self,
        messages: list[dict[str, str]],
        active_model: str,
    ) -> Any:
        """Calls chat completions with reasoning suppression prefill where applicable.

        Args:
            messages: List of message dictionaries.
            active_model: Target model identifier.

        Returns:
            Chat completion API response object.
        """
        is_cloud_model = any(
            k in active_model.lower() for k in ("gemini", "gpt", "claude", "o1", "o3")
        )
        messages_to_send = list(messages)
        if not is_cloud_model:
            messages_to_send.append({"role": "assistant", "content": "<think>\n</think>"})

        try:
            return await self._client.chat.completions.create(
                model=active_model,
                messages=messages_to_send,
                temperature=self.temperature,
            )
        except Exception as e:
            if not is_cloud_model and not is_fatal_error(e):
                logger.debug(
                    f"API rejected assistant prefill ({e}); retrying with standard messages."
                )
                return await self._client.chat.completions.create(
                    model=active_model,
                    messages=messages,
                    temperature=self.temperature,
                )
            raise

    async def correct_text(self, text: str, model_override: Optional[str] = None) -> LLMResponse:
        """Sends a single piece of text for spelling and grammar correction.

        Args:
            text: Text to correct.
            model_override: Optional model identifier overriding the client default.

        Returns:
            LLMResponse containing corrected text with metadata.

        Raises:
            ValueError: If no models are available.
            RuntimeError: If server returns fatal error or retries are exhausted.
        """
        stripped = text.strip()
        if not stripped:
            return LLMResponse(text, completion_tokens=0, prompt_tokens=0, duration=0.0)

        active_model = await self._resolve_active_model(model_override)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Text to correct:\n{stripped}"},
        ]

        max_retries = 2
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                start_call = time.time()
                response = await self._call_chat_completions(messages, active_model)
                call_duration = time.time() - start_call

                raw_content = response.choices[0].message.content or ""
                cleaned = sanitize_llm_output(raw_content, original_text=stripped)
                final_text = preserve_whitespace(text, cleaned)

                completion_tokens = None
                prompt_tokens = None
                if getattr(response, "usage", None):
                    completion_tokens = response.usage.completion_tokens
                    prompt_tokens = response.usage.prompt_tokens

                return LLMResponse(
                    final_text,
                    completion_tokens=completion_tokens,
                    prompt_tokens=prompt_tokens,
                    duration=call_duration,
                )
            except Exception as e:
                last_error = e
                fatal = is_fatal_error(e)
                if fatal or attempt >= max_retries:
                    logger.error(f"Inference failed (fatal={fatal}, attempt {attempt + 1}): {e}")
                    raise RuntimeError(f"LLM Server Error: {last_error}") from last_error

                logger.warning(f"Inference attempt {attempt + 1} failed: {e}. Retrying...")
                await asyncio.sleep(1.0 * (attempt + 1))

        raise RuntimeError(f"LLM Server Error: {last_error}") from last_error

    async def correct_batch(
        self,
        texts: list[str],
        model_override: Optional[str] = None,
    ) -> tuple[Optional[list[str]], Optional[int], float]:
        """Sends a batch of texts for spelling and grammar correction in a single request.

        Args:
            texts: List of text strings to correct.
            model_override: Optional model identifier.

        Returns:
            Tuple of (list_of_corrected_texts, completion_tokens, duration).
            If parsing fails, returns (None, tokens, duration).

        Raises:
            RuntimeError: If server fails with unrecoverable error.
        """
        if not texts:
            return [], 0, 0.0

        if len(texts) == 1:
            res = await self.correct_text(texts[0], model_override=model_override)
            tokens = getattr(res, "completion_tokens", None)
            dur = getattr(res, "duration", 0.0)
            return [str(res)], tokens, dur

        active_model = await self._resolve_active_model(model_override)
        items_str = "\n".join(f"[{i+1}] {t.strip()}" for i, t in enumerate(texts))
        user_content = f"Items to correct:\n{items_str}"

        messages = [
            {"role": "system", "content": BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        start_call = time.time()
        response = await self._call_chat_completions(messages, active_model)
        call_duration = time.time() - start_call
        raw_content = response.choices[0].message.content or ""

        completion_tokens = None
        if getattr(response, "usage", None):
            completion_tokens = response.usage.completion_tokens

        parsed = parse_batched_output(raw_content, expected_count=len(texts))
        if parsed is None:
            logger.warning(
                f"Could not cleanly parse batched LLM output of {len(texts)} items; "
                "falling back to individual processing."
            )
            return None, completion_tokens, call_duration

        final_items = []
        for orig, corr in zip(texts, parsed):
            cleaned = sanitize_llm_output(corr, original_text=orig.strip())
            final_items.append(preserve_whitespace(orig, cleaned))

        return final_items, completion_tokens, call_duration
