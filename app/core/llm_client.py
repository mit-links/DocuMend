"""OpenAI-compatible LLM client for DocuMend.

Connects to any OpenAI-compatible server (LM Studio, Ollama, vLLM, LocalAI, etc.)
with multilingual prompt constraints and sanitization.
"""

import asyncio
import logging
import time
from typing import List, Optional, Tuple
from openai import AsyncOpenAI

from app.core.sanitizer import sanitize_llm_output, parse_batched_output
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
        # Ensure base_url ends with /v1 if missing (unless already an OpenAI-compatible path like /openai)
        if not (self.base_url.endswith("/v1") or "/v1/" in self.base_url or self.base_url.endswith("/openai")):
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

            # Filter out non-chat / non-completion models (embedding, live websocket, audio, image, etc.)
            excluded_keywords = (
                "embed", "live", "imagen", "image", "dall-e",
                "tts", "whisper", "audio", "transcribe", "aqa", "realtime",
            )
            chat_models = []
            for mid in model_ids:
                clean_id = mid.removeprefix("models/") if mid.startswith("models/") else mid
                mid_lower = clean_id.lower()
                if not any(kw in mid_lower for kw in excluded_keywords):
                    chat_models.append(clean_id)

            if not chat_models:
                chat_models = [m.removeprefix("models/") if m.startswith("models/") else m for m in model_ids]

            # Sort intelligently: prioritize standard fast models (flash, instruct, chat) over experimental/preview
            def model_priority(name: str) -> tuple:
                n = name.lower()
                is_flash = 0 if ("flash" in n and "preview" not in n and "exp" not in n) else 1
                is_standard = 0 if ("preview" not in n and "exp" not in n and "custom" not in n) else 1
                return (is_flash, is_standard, n)

            chat_models.sort(key=model_priority)
            return chat_models
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

    async def _call_chat_completions(
        self,
        messages: List[dict],
        active_model: str,
    ):
        """Call chat completions with assistant think-prefill for reasoning suppression, falling back if rejected."""
        # Pre-emptively terminate reasoning only on local CoT models (Qwen, DeepSeek, etc.)
        # Cloud models (Gemini, GPT, Claude) do not use <think> tags and reject assistant-turn suffixes
        is_cloud_model = any(k in active_model.lower() for k in ("gemini", "gpt-", "claude-"))
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
            err_str = str(e).lower()
            # If server rejected the assistant prefill (e.g. role ordering, alternating turns), retry without prefill
            if not is_cloud_model:
                is_unrecoverable = (
                    "unloaded" in err_str
                    or "aborted" in err_str
                    or "not found" in err_str
                    or "does not exist" in err_str
                )
                if not is_unrecoverable:
                    logger.debug(f"API rejected assistant prefill ({e}); retrying with standard messages.")
                    return await self._client.chat.completions.create(
                        model=active_model,
                        messages=messages,
                        temperature=self.temperature,
                    )
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

        # Retry transient network issues with backoff
        max_retries = 2
        last_error = None

        for attempt in range(max_retries + 1):
            start_call = time.time()
            try:
                response = await self._call_chat_completions(messages, active_model)
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
                # Check for unrecoverable client or server errors (model unloaded, aborted, invalid model)
                err_str = str(e).lower()
                is_fatal = (
                    "unloaded" in err_str
                    or "aborted" in err_str
                    or "not found" in err_str
                    or "does not exist" in err_str
                    or "invalid_request_error" in err_str
                    or "bad request" in err_str
                )

                if is_fatal or attempt >= max_retries:
                    logger.error(f"Inference failed (fatal={is_fatal}, attempt {attempt + 1}): {e}")
                    raise RuntimeError(f"LLM Server Error: {last_error}") from last_error

                logger.warning(f"Inference attempt {attempt + 1} failed: {e}. Retrying...")
                await asyncio.sleep(1.0 * (attempt + 1))

        raise RuntimeError(f"LLM Server Error: {last_error}")

    async def correct_batch(
        self,
        texts: List[str],
        model_override: Optional[str] = None,
    ) -> Tuple[Optional[List[str]], Optional[int], float]:
        """Send a batch of texts for spelling & grammar correction in a single request.

        Returns (list_of_corrected_texts, completion_tokens, duration).
        If the batch cannot be cleanly parsed or items count mismatch, returns (None, tokens, duration).
        Raises on server/API errors so the caller can abort immediately.
        """
        if not texts:
            return [], 0, 0.0

        if len(texts) == 1:
            res = await self.correct_text(texts[0], model_override=model_override)
            tokens = getattr(res, "completion_tokens", None)
            dur = getattr(res, "duration", 0.0)
            return [str(res)], tokens, dur

        active_model = model_override or self.model
        if not active_model:
            models = await self.list_models()
            if not models:
                raise ValueError("No models available on the specified LLM server.")
            active_model = models[0]

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
                f"Could not cleanly parse batched LLM output of {len(texts)} items. "
                f"Raw response: {raw_content[:200]}"
            )
            return None, completion_tokens, call_duration

        # Reapply original leading and trailing whitespace to each item
        final_items = []
        for orig, corr in zip(texts, parsed):
            cleaned = sanitize_llm_output(corr, original_text=orig.strip())
            leading_ws = orig[: len(orig) - len(orig.lstrip())]
            trailing_ws = orig[len(orig.rstrip()) :]
            final_items.append(f"{leading_ws}{cleaned}{trailing_ws}")

        return final_items, completion_tokens, call_duration
