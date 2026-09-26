"""OpenAI-compatible LLM client for DocuMend.

Connects to any OpenAI-compatible server (LM Studio, Ollama, vLLM, LocalAI, etc.)
with multilingual prompt constraints and sanitization.
"""

import asyncio
import logging
import time
from typing import List, Optional
from openai import AsyncOpenAI

from app.core.sanitizer import sanitize_llm_output
from app.config import settings

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
    ):
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

    async def eject_inactive_models(self, active_model: Optional[str] = None) -> List[str]:
        """Attempt to unload/eject any inactive models from the local server to free VRAM.

        This is a best-effort operation and will silently continue if unsupported.
        Returns a list of unloaded model IDs.
        """
        import httpx

        target_model = active_model or self.model
        origin = self.base_url.split("/v1")[0].rstrip("/")
        headers = {}
        if self.api_key and self.api_key != "not-needed":
            headers["Authorization"] = f"Bearer {self.api_key}"

        unloaded: List[str] = []

        # 1. Strategy for LM Studio (check loaded models via /api/v0/models and unload via /api/v1/models/unload)
        try:
            async with httpx.AsyncClient(timeout=4.0) as http_client:
                v0_resp = await http_client.get(f"{origin}/api/v0/models", headers=headers)
                if v0_resp.status_code == 200:
                    data = v0_resp.json().get("data", [])
                    for item in data:
                        m_id = item.get("id")
                        state = item.get("state")
                        if state == "loaded" and m_id and (not target_model or m_id != target_model):
                            logger.info(f"Attempting to unload inactive model '{m_id}' from LM Studio to free VRAM...")
                            unload_resp = await http_client.post(
                                f"{origin}/api/v1/models/unload",
                                json={"instance_id": m_id},
                                headers=headers,
                            )
                            if unload_resp.status_code == 200:
                                unloaded.append(m_id)
                                logger.info(f"Successfully ejected model '{m_id}' from LM Studio.")
                            else:
                                logger.debug(f"LM Studio unload response {unload_resp.status_code} for {m_id}")
        except Exception as e:
            logger.debug(f"LM Studio model eject attempt skipped/failed: {e}")

        # 2. Strategy for Ollama (/api/ps and /api/generate with keep_alive=0)
        try:
            async with httpx.AsyncClient(timeout=4.0) as http_client:
                ps_resp = await http_client.get(f"{origin}/api/ps", headers=headers)
                if ps_resp.status_code == 200:
                    running_models = ps_resp.json().get("models", [])
                    for m in running_models:
                        m_name = m.get("name") or m.get("model")
                        if m_name and (not target_model or (m_name != target_model and not target_model.startswith(m_name))):
                            logger.info(f"Attempting to unload inactive model '{m_name}' from Ollama to free VRAM...")
                            unload_resp = await http_client.post(
                                f"{origin}/api/generate",
                                json={"model": m_name, "keep_alive": 0},
                                headers=headers,
                            )
                            if unload_resp.status_code == 200:
                                unloaded.append(m_name)
                                logger.info(f"Successfully ejected model '{m_name}' from Ollama.")
        except Exception as e:
            logger.debug(f"Ollama model eject attempt skipped/failed: {e}")

        return unloaded

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
            start_call = time.time()
            try:
                response = await self._client.chat.completions.create(
                    model=active_model,
                    messages=messages,
                    temperature=self.temperature,
                )
                call_duration = time.time() - start_call
                raw_content = response.choices[0].message.content or ""
                cleaned = sanitize_llm_output(raw_content, original_text=stripped)

                # Preserve leading/trailing whitespace from original text
                leading_ws = text[: len(text) - len(text.lstrip())]
                trailing_ws = text[len(text.rstrip()) :]
                final_text = f"{leading_ws}{cleaned}{trailing_ws}"

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
                logger.warning(f"Inference attempt {attempt + 1} failed: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    logger.error(f"Inference failed after {max_retries + 1} attempts: {last_error}")
                    # Return original text on failure to prevent document corruption
                    return text

        return text
