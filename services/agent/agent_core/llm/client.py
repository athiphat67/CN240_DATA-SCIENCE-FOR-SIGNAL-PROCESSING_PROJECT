from __future__ import annotations

# [v2.5]
# - ClaudeClient.DEFAULT_MODEL: claude-opus-4-1 → claude-sonnet-4-5
# - เพิ่ม @with_retry(max_attempts=3) ให้ ClaudeClient, OpenAIClient,
#   GroqClient, DeepSeekClient, OpenRouterClient (เดิมมีแค่ GeminiClient)

import os
import re
import json
import requests
from typing import Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from agent_core.core.prompt import PromptPackage
import time
from functools import wraps
from logs.logger_setup import llm_logger, sys_logger, log_method

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:9b")
 
# Regex สำหรับ strip Qwen3 thinking blocks
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────
# LLMResponse — structured response จาก LLM (replaces bare str)
# ─────────────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    """
    Structured response จาก LLM ทุก provider

    Fields:
        text         — raw text response (JSON string expected)
        prompt_text  — full prompt ที่ส่งไป (system + user concatenated)
        token_input  — จำนวน input tokens (0 ถ้า provider ไม่รองรับ)
        token_output — จำนวน output tokens
        token_total  — รวม input + output
        model        — model name ที่ใช้จริง
        provider     — provider name ("gemini", "openai", "claude", ...)
    """
    text:         str
    prompt_text:  str
    token_input:  int = 0
    token_output: int = 0
    token_total:  int = 0
    model:        str = ""
    provider:     str = ""


# ─────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────
 
def _strip_think(text: str) -> str:
    """
    ลบ <think>...</think> ออกจาก response Qwen3.5
    และ clean whitespace ที่เหลือ
    """
    cleaned = _THINK_RE.sub("", text)
    return cleaned.strip()
 
 
def _extract_json_block(text: str) -> str:
    """
    พยายาม extract JSON จาก response ที่อาจมี markdown fence
    ลำดับ: json block → bare { } → return as-is
    """
    # ```json ... ```
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
 
    # bare { ... } (first occurrence)
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        return brace.group(0)
 
    return text  # ส่งคืนตามเดิม ให้ caller จัดการ


# ---------------------------------------------------------------------------
# Retry Utility
# ---------------------------------------------------------------------------

def with_retry(max_attempts=3, delay=2.0):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except LLMProviderError as e:
                    if attempt == max_attempts - 1:
                        raise
                    print(f"⚠️ API call failed (attempt {attempt + 1}/{max_attempts}). Retrying in {delay}s...")
                    time.sleep(delay * (attempt + 1))  # Exponential-ish backoff
        return wrapper
    return decorator

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMException(Exception):
    """Base exception สำหรับ LLM errors ทุกชนิด"""
    pass


class LLMProviderError(LLMException):
    """เกิดจาก API error ของ provider"""
    pass


class LLMUnavailableError(LLMException):
    """Provider ไม่พร้อมใช้งาน (missing key, no connection)"""
    pass


# ---------------------------------------------------------------------------
# Abstract Base Class
# ---------------------------------------------------------------------------


class LLMClient(ABC):
    """
    Abstract base class สำหรับ LLM provider ทุกตัว

    Contract:
    - call()         → รับ PromptPackage, คืน LLMResponse (text + tokens + meta)
    - is_available() → ตรวจสอบว่า client พร้อมใช้งาน
    """

    PROVIDER_NAME: str = "unknown"

    @abstractmethod
    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        """
        ส่ง prompt ไปยัง LLM และรับ LLMResponse กลับมา

        Args:
            prompt_package: PromptPackage ที่มี system, user, step_label

        Returns:
            LLMResponse: text + prompt_text + token counts + model/provider info

        Raises:
            LLMProviderError: เมื่อ API call ล้มเหลว
            LLMUnavailableError: เมื่อ client ไม่พร้อม
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """
        ตรวจสอบว่า LLM client พร้อมใช้งานหรือไม่

        Returns:
            bool: True ถ้าพร้อม, False ถ้าไม่พร้อม
        """
        ...

    @staticmethod
    def _build_prompt_text(prompt_package: PromptPackage) -> str:
        """Helper: สร้าง full prompt string สำหรับ logging"""
        return f"SYSTEM:\n{prompt_package.system}\n\nUSER:\n{prompt_package.user}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} available={self.is_available()}>"


# ---------------------------------------------------------------------------
# Default mock responses
# ---------------------------------------------------------------------------

DEFAULT_MOCK_RESPONSES: dict[str, str] = {
    "THOUGHT_1": '{"action": "CALL_TOOL", "tool": "get_news", "params": {}}',
    "THOUGHT_2": '{"action": "CALL_TOOL", "tool": "run_calculator", "params": {"expression": "close / open"}}',
    "THOUGHT_3": '{"action": "FINAL_DECISION", "signal": "HOLD", "confidence": 0.6, "rationale": "Insufficient signal"}',
    "THOUGHT_FINAL": '{"action": "FINAL_DECISION", "signal": "HOLD", "confidence": 0.5, "rationale": "Mock final decision"}',
}

# ---------------------------------------------------------------------------
# Mock LLM Client
# ---------------------------------------------------------------------------


class MockClient(LLMClient):
    """
    LLM Client สำหรับ testing — ไม่เรียก API จริง

    ใช้ response_map เพื่อ map step_label → mock JSON response
    ถ้าไม่มี key ที่ตรง จะ fallback เป็น HOLD decision
    """

    PROVIDER_NAME = "mock"

    def __init__(self, response_map: Optional[dict[str, str]] = None):
        self.response_map = (
            response_map if response_map is not None else DEFAULT_MOCK_RESPONSES
        )

    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        text = self.response_map.get(
            prompt_package.step_label,
            '{"action": "FINAL_DECISION", "signal": "HOLD", "confidence": 0.5, "rationale": "Mock fallback"}',
        )
        return LLMResponse(
            text=text,
            prompt_text=self._build_prompt_text(prompt_package),
            token_input=0,
            token_output=0,
            token_total=0,
            model="mock",
            provider=self.PROVIDER_NAME,
        )

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Concrete Implementations
# ---------------------------------------------------------------------------


class GeminiClient(LLMClient):
    """
    LLM Client สำหรับ Google Gemini API
    รองรับ mock mode สำหรับ testing
    """

    PROVIDER_NAME = "gemini-3.1-flash-lite-preview"
    DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
        use_mock: bool = False,
    ):
        self.model = model
        self.temperature = temperature
        self.use_mock = use_mock
        self._client = None

        if not use_mock:
            try:
                from google import genai  # type: ignore

                self._client = genai.Client(
                    api_key=api_key or os.environ["GEMINI_API_KEY"]
                )
            except KeyError:
                raise LLMUnavailableError(
                    "GEMINI_API_KEY not found. Set env var or pass api_key."
                )
            except ImportError:
                raise LLMUnavailableError(
                    "google-genai package not installed. Run: pip install google-genai"
                )

    @with_retry(max_attempts=3)
    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        if self.use_mock:
            return self._mock_response(prompt_package)

        if not self._client:
            raise LLMUnavailableError("GeminiClient is not initialized.")

        full_prompt = self._build_prompt_text(prompt_package)

        try:
            # llm_logger.info(f"--- LLM REQUEST [{prompt_package.step_label}] ---")
            llm_logger.debug(f"PROMPT:\n{full_prompt}")

            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt_package.user,
                config={"system_instruction": prompt_package.system, "temperature": self.temperature},
            )

            text = response.text or ""

            # Extract token usage from Gemini response
            usage = getattr(response, "usage_metadata", None)
            token_input  = getattr(usage, "prompt_token_count",     0) if usage else 0
            token_output = getattr(usage, "candidates_token_count", 0) if usage else 0
            token_total  = getattr(usage, "total_token_count", token_input + token_output) if usage else token_input + token_output

            # llm_logger.info(f"--- LLM RESPONSE [{prompt_package.step_label}] ---")
            llm_logger.info(f"🪙 Gemini Token Usage → Input: {token_input} | Output: {token_output} | Total: {token_total}")
            llm_logger.debug(f"OUTPUT:\n{text}")

            return LLMResponse(
                text=text,
                prompt_text=full_prompt,
                token_input=token_input,
                token_output=token_output,
                token_total=token_total,
                model=self.model,
                provider=self.PROVIDER_NAME,
            )

        except Exception as e:
            raise LLMProviderError(
                f"Gemini API error at {prompt_package.step_label}: {e}"
            ) from e

    def is_available(self) -> bool:
        if self.use_mock:
            return True
        return self._client is not None

    def _mock_response(self, prompt_package: PromptPackage) -> LLMResponse:
        text = DEFAULT_MOCK_RESPONSES.get(
            prompt_package.step_label,
            '{"action": "FINAL_DECISION", "signal": "HOLD", "confidence": 0.5, "rationale": "Mock fallback"}',
        )
        return LLMResponse(
            text=text,
            prompt_text=self._build_prompt_text(prompt_package),
            token_input=0, token_output=0, token_total=0,
            model=self.model, provider=self.PROVIDER_NAME,
        )


class OpenAIClient(LLMClient):
    """LLM Client สำหรับ OpenAI API (GPT series)"""

    PROVIDER_NAME = "openai"
    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.7,
    ):
        self.model = model
        self.temperature = temperature

        try:
            from openai import OpenAI  # type: ignore

            self._client = OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        except KeyError:
            raise LLMUnavailableError(
                "OPENAI_API_KEY not found. Set env var or pass api_key."
            )
        except ImportError:
            raise LLMUnavailableError(
                "openai package not installed. Run: pip install openai"
            )

    @with_retry(max_attempts=3)
    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        full_prompt = self._build_prompt_text(prompt_package)
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": prompt_package.system},
                    {"role": "user",   "content": prompt_package.user},
                ],
            )
            text = response.choices[0].message.content or ""

            usage = response.usage
            token_input  = getattr(usage, "prompt_tokens",     0) if usage else 0
            token_output = getattr(usage, "completion_tokens", 0) if usage else 0
            token_total  = getattr(usage, "total_tokens", token_input + token_output) if usage else token_input + token_output

            llm_logger.info(f"🪙 OpenAI Token Usage → Input: {token_input} | Output: {token_output} | Total: {token_total}")

            return LLMResponse(
                text=text,
                prompt_text=full_prompt,
                token_input=token_input,
                token_output=token_output,
                token_total=token_total,
                model=self.model,
                provider=self.PROVIDER_NAME,
            )
        except Exception as e:
            raise LLMProviderError(
                f"OpenAI API error at {prompt_package.step_label}: {e}"
            ) from e

    def is_available(self) -> bool:
        return self._client is not None


class ClaudeClient(LLMClient):
    """LLM Client สำหรับ Anthropic Claude API"""

    PROVIDER_NAME = "claude"
    DEFAULT_MODEL = "claude-sonnet-4-5"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 2048,
    ):
        self.model = model
        self.max_tokens = max_tokens

        try:
            from anthropic import Anthropic  # type: ignore

            self._client = Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        except KeyError:
            raise LLMUnavailableError(
                "ANTHROPIC_API_KEY not found. Set env var or pass api_key."
            )
        except ImportError:
            raise LLMUnavailableError(
                "anthropic package not installed. Run: pip install anthropic"
            )

    @with_retry(max_attempts=3)
    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        full_prompt = self._build_prompt_text(prompt_package)
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=prompt_package.system,
                messages=[
                    {"role": "user", "content": prompt_package.user},
                ],
            )
            text = response.content[0].text if response.content else ""

            usage = getattr(response, "usage", None)
            token_input  = getattr(usage, "input_tokens",  0) if usage else 0
            token_output = getattr(usage, "output_tokens", 0) if usage else 0
            token_total  = token_input + token_output

            llm_logger.info(f"🪙 Claude Token Usage → Input: {token_input} | Output: {token_output} | Total: {token_total}")

            return LLMResponse(
                text=text,
                prompt_text=full_prompt,
                token_input=token_input,
                token_output=token_output,
                token_total=token_total,
                model=self.model,
                provider=self.PROVIDER_NAME,
            )
        except Exception as e:
            raise LLMProviderError(
                f"Claude API error at {prompt_package.step_label}: {e}"
            ) from e

    def is_available(self) -> bool:
        return self._client is not None


class GroqClient(LLMClient):
    """LLM Client สำหรับ Groq (LPU Inference Engine) - เน้นความเร็วสูง"""

    PROVIDER_NAME = "groq"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
        **kwargs,
    ):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")

        try:
            from groq import Groq
            if not self.api_key:
                raise LLMUnavailableError("GROQ_API_KEY not found. Please set it in your .env file.")
            self._client = Groq(api_key=self.api_key)
        except ImportError:
            raise LLMUnavailableError("groq package not installed. Run: pip install groq")

    @with_retry(max_attempts=3)
    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        full_prompt = self._build_prompt_text(prompt_package)
        try:
            chat_completion = self._client.chat.completions.create(
                messages=[
                    {"role": "system", "content": prompt_package.system},
                    {"role": "user",   "content": prompt_package.user},
                ],
                model=self.model,
                temperature=self.temperature,
            )

            usage = chat_completion.usage
            token_input  = getattr(usage, "prompt_tokens",     0) if usage else 0
            token_output = getattr(usage, "completion_tokens", 0) if usage else 0
            token_total  = getattr(usage, "total_tokens", token_input + token_output) if usage else token_input + token_output

            llm_logger.info(f"🪙 Groq Token Usage → Input: {token_input} | Output: {token_output} | Total: {token_total}")

            raw  = chat_completion.choices[0].message.content or ""
            text = _extract_json_block(_strip_think(raw))

            return LLMResponse(
                text=text,
                prompt_text=full_prompt,
                token_input=token_input,
                token_output=token_output,
                token_total=token_total,
                model=self.model,
                provider=self.PROVIDER_NAME,
            )

        except Exception as e:
            raise LLMProviderError(f"Groq API error: {e}") from e

    def is_available(self) -> bool:
        return self._client is not None


class DeepSeekClient(LLMClient):
    """LLM Client สำหรับ DeepSeek API - รองรับ OpenAI compatible format"""

    PROVIDER_NAME = "deepseek"
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.7,
    ):
        self.model = model
        self.temperature = temperature

        try:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=api_key or os.environ["DEEPSEEK_API_KEY"],
                base_url="https://api.deepseek.com",
            )
        except KeyError:
            raise LLMUnavailableError("DEEPSEEK_API_KEY not found in env.")
        except ImportError:
            raise LLMUnavailableError("openai package missing.")

    @with_retry(max_attempts=3)
    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        full_prompt = self._build_prompt_text(prompt_package)
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt_package.system},
                    {"role": "user",   "content": prompt_package.user},
                ],
                temperature=self.temperature,
                stream=False,
            )
            text = response.choices[0].message.content or ""

            usage = getattr(response, "usage", None)
            token_input  = getattr(usage, "prompt_tokens",     0) if usage else 0
            token_output = getattr(usage, "completion_tokens", 0) if usage else 0
            token_total  = getattr(usage, "total_tokens", token_input + token_output) if usage else token_input + token_output

            llm_logger.info(f"🪙 DeepSeek Token Usage → Input: {token_input} | Output: {token_output} | Total: {token_total}")

            return LLMResponse(
                text=text,
                prompt_text=full_prompt,
                token_input=token_input,
                token_output=token_output,
                token_total=token_total,
                model=self.model,
                provider=self.PROVIDER_NAME,
            )
        except Exception as e:
            raise LLMProviderError(f"DeepSeek API error: {e}") from e

    def is_available(self) -> bool:
        return self._client is not None


class OllamaClient(LLMClient):
    """
    LLM Client สำหรับ Ollama local inference server

    รองรับ model ทุกตัวที่ pull ลงใน Ollama แล้ว เช่น
      - qwen3.5:9b    (ถ้า available — มี thinking mode, strip ให้อัตโนมัติ)
      - llama3.1:8b

    Environment Variables (optional):
        OLLAMA_BASE_URL  : default http://localhost:11434
        OLLAMA_MODEL     : default qwen3.5:9b
    """

    PROVIDER_NAME = "ollama"

    def __init__(
        self,
        model: str = OLLAMA_DEFAULT_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        temperature: float = 0.1,
        num_ctx: int = 4096,
        timeout: int = 120,
        strip_thinking: bool = True,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.strip_thinking = strip_thinking

        self._chat_url = f"{self.base_url}/api/chat"
        self._tags_url = f"{self.base_url}/api/tags"

        if not self._ping():
            raise LLMUnavailableError(
                f"Ollama server ไม่ตอบสนองที่ {self.base_url}\n"
                f"  → รัน: ollama serve\n"
                f"  → pull model: ollama pull {self.model}"
            )

    # ── Public API ────────────────────────────────────────────────

    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        """
        ส่ง prompt ไปยัง Ollama และรับ LLMResponse กลับ

        Returns:
            LLMResponse: text (cleaned JSON) + prompt_text + token counts

        Raises:
            LLMProviderError: Ollama ตอบ error หรือ request ล้มเหลว
            LLMUnavailableError: server ไม่พร้อม
        """
        full_prompt = self._build_prompt_text(prompt_package)

        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
            },
            "messages": [
                {"role": "system", "content": self._inject_no_think(prompt_package.system)},
                {"role": "user",   "content": prompt_package.user},
            ],
        }

        try:
            resp = requests.post(
                self._chat_url,
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise LLMUnavailableError(
                f"เชื่อมต่อ Ollama ไม่ได้ที่ {self.base_url} — ตรวจสอบว่า ollama serve รันอยู่"
            )
        except requests.exceptions.Timeout:
            raise LLMProviderError(
                f"Ollama timeout ({self.timeout}s) สำหรับ model={self.model}"
            )
        except requests.exceptions.HTTPError as e:
            raise LLMProviderError(f"Ollama HTTP error: {e}") from e

        data = resp.json()

        raw = data.get("message", {}).get("content", "")
        if not raw:
            raise LLMProviderError("Ollama returned empty content")

        # Ollama token usage fields
        token_input  = data.get("prompt_eval_count", 0)
        token_output = data.get("eval_count", 0)
        token_total  = token_input + token_output

        llm_logger.info(f"🪙 Ollama Token Usage → Input: {token_input} | Output: {token_output} | Total: {token_total}")

        cleaned = _strip_think(raw) if self.strip_thinking else raw
        text = _extract_json_block(cleaned)

        return LLMResponse(
            text=text,
            prompt_text=full_prompt,
            token_input=token_input,
            token_output=token_output,
            token_total=token_total,
            model=self.model,
            provider=self.PROVIDER_NAME,
        )

    def is_available(self) -> bool:
        return self._ping()

    # ── Private Helpers ───────────────────────────────────────────

    def _ping(self) -> bool:
        """ตรวจสอบว่า Ollama daemon รันอยู่"""
        try:
            r = requests.get(self._tags_url, timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _inject_no_think(system_prompt: str) -> str:
        """
        เพิ่ม /no_think ถ้ายังไม่มีใน system prompt
        บอก Qwen3.5 ให้ข้ามขั้นตอน thinking และ output JSON ตรงๆ
        """
        if "/no_think" not in system_prompt:
            return "/no_think\n" + system_prompt
        return system_prompt

    def list_local_models(self) -> list[str]:
        """คืนรายชื่อ model ที่ pull ลงมาแล้วใน Ollama"""
        try:
            r = requests.get(self._tags_url, timeout=5)
            r.raise_for_status()
            models = r.json().get("models", [])
            return [m["name"] for m in models]
        except Exception:
            return []

    def __repr__(self) -> str:
        return (
            f"<OllamaClient model={self.model} "
            f"url={self.base_url} "
            f"available={self.is_available()}>"
        )

class OpenRouterClient(LLMClient):
    """
    LLM Client สำหรับ OpenRouter API
    รองรับทุก model ที่ OpenRouter มี — ใส่ชื่อตอนสร้าง object หรือใช้ shortcut ได้เลย

    Usage:
        # ใช้ default model
        client = OpenRouterClient()

        # ระบุ model เต็ม
        client = OpenRouterClient(model="anthropic/claude-haiku-4-5")

        # ใช้ shortcut key จาก MODELS dict
        client = OpenRouterClient(model="claude-haiku")
        client = OpenRouterClient(model="gpt-5-mini")
        client = OpenRouterClient(model="llama-70b")
        client = OpenRouterClient(model="grok-mini")
        client = OpenRouterClient(model="mistral-small")

        # ผ่าน Factory (รองรับ colon syntax)
        client = LLMClientFactory.create("openrouter")
        client = LLMClientFactory.create("openrouter", model="claude-haiku")
        client = LLMClientFactory.create("openrouter", model="anthropic/claude-haiku-4-5")

    Model reference: https://openrouter.ai/models

    Environment Variables:
        OPENROUTER_API_KEY   — required
        OPENROUTER_MODEL     — override default model (optional)
        OPENROUTER_APP_URL   — HTTP-Referer header (optional)
        OPENROUTER_APP_NAME  — X-Title header (optional)
    """

    PROVIDER_NAME = "openrouter"

    # ── Preset models ────────────────────────────────────────────────────────
    # shortcut → full OpenRouter model string
    MODELS: dict[str, str] = {
        "claude-opus-4.7": "anthropic/claude-opus-4.7",
        "claude-haiku-4-5":     "anthropic/claude-haiku-4-5",
        "claude-haiku-3-5": "anthropic/claude-3.5-haiku",
        "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
        "gpt-5-3-codex":    "openai/gpt-5.3-codex",
        "gpt-5.1-codex-mini": "openai/gpt-5.1-codex-mini",
        "gpt-5-2-chat": "openai/gpt-5.2-chat",
        "gpt-5-mini":       "openai/gpt-5-mini",
        "gpt-4o-mini":      "openai/gpt-4o-mini",
        "llama-70b":        "meta-llama/llama-3.3-70b-instruct",
        "grok-mini":        "x-ai/grok-3-mini",
        "mistral-small":    "mistralai/mistral-small-3.2-24b-instruct-2506",
        "nemotron-super":   "nvidia/nemotron-3-super-120b-a12b:free",
        "gemini-3.1-pro-preview":   "google/gemini-3.1-pro-preview",
        "gemini-3-1-flash-preview":   "google/gemini-3-flash-preview",
        "gemini-3-1-flash-lite-preview":   "google/gemini-3.1-flash-lite-preview",
        "gemini-2-5-flash-lite":   "google/gemini-2.5-flash-lite",
        "gemini-2-0-flash-lite":   "google/gemini-2.0-flash-lite-001",
        "deepseek-v-3-2": "deepseek/deepseek-v3.2",
    }

    DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-3-flash-preview")

    @classmethod
    def resolve_model(cls, model: str) -> str:
        """
        แปลง shortcut → full model string
        ถ้าไม่ match shortcut ใดๆ ส่งคืนตามเดิม (full string แล้ว)

        Examples:
            "claude-haiku"                     → "anthropic/claude-haiku-4-5"
            "anthropic/claude-haiku-4-5"       → "anthropic/claude-haiku-4-5"  (unchanged)
            "some/new-model-not-in-dict"        → "some/new-model-not-in-dict"  (unchanged)
        """
        return cls.MODELS.get(model, model)

    @classmethod
    def list_models(cls) -> None:
        """Print รายการ shortcut ทั้งหมดพร้อม full model name"""
        print(f"\n{'─'*55}")
        print(f"  OpenRouter Model Shortcuts")
        print(f"{'─'*55}")
        for shortcut, full in cls.MODELS.items():
            print(f"  {shortcut:<20} → {full}")
        print(f"{'─'*55}")
        print(f"  Default: {cls.DEFAULT_MODEL}\n")

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,           # None = ใช้ DEFAULT_MODEL
        temperature: float = 0.1,              # ต่ำ → deterministic สำหรับ trading
        site_url: Optional[str] = None,        # HTTP-Referer (optional แต่ดีต่อ rate limit)
        app_name: Optional[str] = None,        # X-Title (optional)
    ):
        # model priority: argument > env var > hardcoded default
        # resolve_model แปลง shortcut → full string อัตโนมัติ
        self.model       = self.resolve_model(model or self.DEFAULT_MODEL)
        self.temperature = temperature
        self.site_url    = site_url  or os.environ.get("OPENROUTER_APP_URL",  "")
        self.app_name    = app_name  or os.environ.get("OPENROUTER_APP_NAME", "GoldTradingAgent")

        api_key_val = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key_val:
            raise LLMUnavailableError(
                "OPENROUTER_API_KEY not found. Set env var or pass api_key."
            )

        try:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=api_key_val,
                base_url="https://openrouter.ai/api/v1",
            )
        except ImportError:
            raise LLMUnavailableError("openai package missing. Run: pip install openai")

    @with_retry(max_attempts=3)
    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        full_prompt = self._build_prompt_text(prompt_package)
        
        # 1. เตรียม API Kwargs พื้นฐาน
        api_kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt_package.system},
                {"role": "user",   "content": prompt_package.user},
            ],
            "temperature": self.temperature,
            "stream": False,
        }
        
        # 2. --- Routing ระบบ Thinking สำหรับทุกค่ายใน OpenRouter ---
        extra_body = {}
        
        # ใช้ getattr เพื่อป้องกัน Error กรณี PromptPackage เก่าไม่มีตัวแปรนี้
        thinking_mode = getattr(prompt_package, "thinking_mode", None)
        
        if thinking_mode:
            mode_lower = thinking_mode.lower()
            
            # ค่าย Google (Gemini)
            if "gemini" in self.model:
                extra_body["thinking_config"] = {
                    "include_thoughts": True,
                    "thinking_level": "high" if mode_lower in ["high", "extended"] else "medium"
                }
                
            # ค่าย Anthropic (Claude 3.7 ขึ้นไป)
            elif "claude-3.7" in self.model or "claude-3-7" in self.model:
                if mode_lower in ["high", "extended"]:
                    extra_body["thinking"] = {"type": "enabled", "budget_tokens": 4000}
                    api_kwargs["max_completion_tokens"] = 8000 # กฎของ Claude: max_completion ต้องมากกว่า budget
                    api_kwargs.pop("temperature", None) # บางกรณี Extended thinking ไม่ให้ปรับ temp
                    
            # ค่าย OpenAI (o1, o3-mini)
            elif "o1" in self.model or "o3" in self.model:
                if mode_lower in ["low", "medium", "high"]:
                    api_kwargs["reasoning_effort"] = mode_lower
                api_kwargs.pop("temperature", None) # ตระกูล o-series มักล็อคอุณหภูมิ

            # ค่าย DeepSeek (R1)
            # OpenRouter มักจะให้ R1 คืนค่า <think> กลับมาให้อัตโนมัติอยู่แล้ว 
            # จึงไม่ต้องเซ็ต extra_body พิเศษ แต่ตัว _extract_think_block จะช่วยดึงออกมาให้เอง

        if extra_body:
            api_kwargs["extra_body"] = extra_body

        # 3. --- ส่วนจัดการ Headers ---
        extra_headers = {}
        if self.site_url:
            extra_headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            extra_headers["X-Title"] = self.app_name
            
        if extra_headers:
            api_kwargs["extra_headers"] = extra_headers

        # 4. --- ยิง API ---
        try:
            # 🚨 แก้ไขแล้ว: โยน **api_kwargs เข้าไปแทนการ Hardcode 
            response = self._client.chat.completions.create(**api_kwargs)

            raw  = response.choices[0].message.content or ""
            
            # ถ้ามีฟังก์ชัน _extract_think_block ให้ใช้เพื่อดึง reasoning ออกมา (รองรับแท็ก <think> ของ DeepSeek ด้วย)
            # แต่ถ้ายังไม่มี ใช้ _strip_think แบบเดิมของคุณไปก่อนได้ครับ
            try:
                clean_text, reasoning = _extract_think_block(raw)
            except NameError:
                # Fallback กรณีคุณยังไม่ได้เพิ่ม _extract_think_block เข้าไปในไฟล์
                clean_text = _strip_think(raw)
                reasoning = None

            text = _extract_json_block(clean_text)

            # --- คำนวณ Token ---
            usage        = getattr(response, "usage", None)
            token_input  = getattr(usage, "prompt_tokens",     0) if usage else 0
            token_output = getattr(usage, "completion_tokens", 0) if usage else 0
            token_total  = getattr(usage, "total_tokens", token_input + token_output) if usage else token_input + token_output

            llm_logger.info(
                f"🪙 OpenRouter [{self.model}] Token Usage → "
                f"Input: {token_input} | Output: {token_output} | Total: {token_total}"
            )
            
            llm_logger.info(f"🪙 Gemini Token Usage → Input: {token_input} | Output: {token_output} | Total: {token_total}")
            llm_logger.debug(f"OUTPUT:\n{text}")

            # คืนค่า Response (ถ้า LLMResponse ของคุณรองรับ reasoning_text แล้ว ก็ส่งกลับไปได้เลย)
            response_kwargs = {
                "text": text,
                "prompt_text": full_prompt,
                "token_input": token_input,
                "token_output": token_output,
                "token_total": token_total,
                "model": self.model,
                "provider": self.PROVIDER_NAME,
            }
            
            # ใส่ reasoning กลับไปถ้า Dataclass รองรับ
            if hasattr(LLMResponse, "reasoning_text"):
                response_kwargs["reasoning_text"] = reasoning

            return LLMResponse(**response_kwargs)
            
        except Exception as e:
            raise LLMProviderError(
                f"OpenRouter API error [{self.model}] at {prompt_package.step_label}: {e}"
            ) from e

    def is_available(self) -> bool:
        return self._client is not None

    def __repr__(self) -> str:
        return (
            f"<OpenRouterClient model='{self.model}' "
            f"available={self.is_available()}>"
        )


# ---------------------------------------------------------------------------
# Fallback Chain Client
# ---------------------------------------------------------------------------


class FallbackChainClient(LLMClient):
    """
    LLM Client ที่รวม provider หลายตัวเข้าด้วยกัน
    ลองตัวแรกก่อน — ถ้าล้มเหลว (LLMProviderError / LLMUnavailableError)
    จะสลับไปตัวถัดไปอัตโนมัติโดยไม่ crash

    Usage:
        chain = FallbackChainClient([
            ("gemini", GeminiClient()),
            ("groq",   GroqClient()),
            ("mock",   MockClient()),
        ])
        result = chain.call(prompt_package)
        print(chain.active_provider)   # ชื่อ provider ที่ใช้จริง

    Behaviour:
    - ลอง provider ตามลำดับใน `clients`
    - Skip provider ที่ is_available() == False ตั้งแต่ต้น
    - เก็บ error log ทุกตัวใน `errors` สำหรับ debug
    - ถ้าทุกตัว fail → raise LLMProviderError รวม error ทั้งหมด
    """

    PROVIDER_NAME = "fallback_chain"

    def __init__(self, clients: list[tuple]):
        """
        clients: list ของ (name, client) หรือ (name, client, domain)

        domain — optional string ระบุ failure domain เช่น "google", "openai", "anthropic"
        หาก provider ใด fail แล้ว ระบบจะ mark domain นั้นเป็น failed ทันที และ skip
        provider ตัวอื่นใน domain เดียวกันโดยไม่ต้อง retry — ลด latency อย่างมีนัยสำคัญ
        เมื่อ API ทั้ง domain ล่ม (เช่น Google Gemini ทุก tier พัง)

        Backward-compatible: 2-tuple (name, client) จะถูก normalise เป็น domain=None
        และจะไม่มีการ skip ตาม domain (พฤติกรรมเดิมทุกอย่าง)
        """
        if not clients:
            raise ValueError("FallbackChainClient requires at least one client")
        # normalise ทุก entry เป็น 3-tuple (name, client, domain | None)
        self._clients: list[tuple[str, LLMClient, str | None]] = []
        for item in clients:
            if len(item) == 3:
                name, client, domain = item
            else:
                name, client = item
                domain = None
            self._clients.append((name, client, domain))
        self.active_provider: str = self._clients[0][0]
        self.errors: list[dict] = []

    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        """
        ลอง call ตามลำดับ — fallback อัตโนมัติเมื่อ error

        Failure Domain Logic:
            หาก provider fail และมี domain กำกับ → domain นั้นถูก mark เป็น failed
            provider ตัวถัดไปที่อยู่ใน domain เดียวกันจะถูก skip ทันที
            เช่น: gemini-3.1 (google) fail → gemini-2.5, gemini-2.0 ถูก skip โดยอัตโนมัติ

        Returns:
            LLMResponse จาก provider แรกที่สำเร็จ

        Raises:
            LLMProviderError: เมื่อทุก provider ล้มเหลว
        """
        self.errors = []
        failed_domains: set[str] = set()  # domain ที่ fail ไปแล้วในรอบนี้

        for name, client, domain in self._clients:

            # ── Failure Domain Skip ────────────────────────────────────────
            if domain and domain in failed_domains:
                msg = (
                    f"{name}: domain='{domain}' already failed — skipped "
                    f"(avoids redundant retry)"
                )
                sys_logger.warning(f"[FallbackChain] 🚫 {msg}")
                self.errors.append({
                    "provider": name, "error": msg,
                    "skipped": True, "domain_skip": True,
                })
                continue

            if not client.is_available():
                msg = f"{name}: is_available() = False — skipped"
                sys_logger.warning(f"[FallbackChain] {msg}")
                self.errors.append({
                    "provider": name, "error": msg,
                    "skipped": True, "domain_skip": False,
                })
                continue

            try:
                domain_tag = f" [domain={domain}]" if domain else ""
                sys_logger.info(
                    f"[FallbackChain] Trying provider '{name}'{domain_tag} "
                    f"(step={prompt_package.step_label})"
                )
                result = client.call(prompt_package)
                self.active_provider = name
                sys_logger.info(f"[FallbackChain] ✅ Success with '{name}'")
                return result

            except (LLMProviderError, LLMUnavailableError) as e:
                err_str = f"{type(e).__name__}: {e}"
                if domain:
                    failed_domains.add(domain)
                    sys_logger.warning(
                        f"[FallbackChain] ❌ '{name}' failed — "
                        f"domain '{domain}' marked as failed. "
                        f"Remaining '{domain}' providers will be skipped automatically."
                    )
                else:
                    sys_logger.warning(
                        f"[FallbackChain] ❌ '{name}' failed — {err_str}. "
                        f"Trying next provider..."
                    )
                self.errors.append({
                    "provider": name, "error": err_str,
                    "skipped": False, "domain_skip": False,
                })
                continue

            except Exception as e:
                err_str = f"Unexpected {type(e).__name__}: {e}"
                if domain:
                    failed_domains.add(domain)
                sys_logger.error(
                    f"[FallbackChain] 💥 '{name}' unexpected error — {err_str}"
                )
                self.errors.append({
                    "provider": name, "error": err_str,
                    "skipped": False, "domain_skip": False,
                })
                continue

        # ทุกตัว fail (หรือถูก skip ทั้งหมด)
        domain_skips = [e["provider"] for e in self.errors if e.get("domain_skip")]
        summary = " | ".join(
            f"{e['provider']}: {e['error']}" for e in self.errors if not e.get("domain_skip")
        )
        extra = f" (domain-skipped: {domain_skips})" if domain_skips else ""
        raise LLMProviderError(
            f"All providers in fallback chain failed.{extra}\n  → {summary}"
        )

    def is_available(self) -> bool:
        """True ถ้ามีอย่างน้อย 1 provider ที่พร้อม"""
        return any(client.is_available() for _, client, _ in self._clients)

    def __repr__(self) -> str:
        parts = [
            f"{n}[{d}]" if d else n
            for n, _, d in self._clients
        ]
        return (
            f"<FallbackChainClient providers={parts} "
            f"active='{self.active_provider}' "
            f"available={self.is_available()}>"
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class LLMClientFactory:
    """
    Factory สำหรับสร้าง LLMClient ตามชื่อ provider

    Usage:
        client = LLMClientFactory.create("gemini")
        client = LLMClientFactory.create("gemini", use_mock=True)
        client = LLMClientFactory.create("openai", model="gpt-4o")
        client = LLMClientFactory.create("claude")
        client = LLMClientFactory.create("mock", response_map={...})
    """

    _REGISTRY: dict[str, type[LLMClient]] = {
        "gemini":   GeminiClient,
        "openai":   OpenAIClient,
        "claude":   ClaudeClient,
        "mock":     MockClient,
        "groq":     GroqClient,
        "deepseek": DeepSeekClient,
        "ollama":   OllamaClient,
        "openrouter": OpenRouterClient,
    }

    @classmethod
    def create(cls, provider: str, **kwargs) -> LLMClient:
        """
        สร้าง LLMClient ตาม provider name

        Args:
            provider: "gemini" | "openai" | "claude" | "groq" | "deepseek"
                      "ollama" | "openrouter" | "mock"

                      รองรับ colon syntax สำหรับ openrouter:
                        "openrouter:claude-haiku"
                        "openrouter:gpt-5-mini"
                        "openrouter:llama-70b"
                        "openrouter:grok-mini"
                        "openrouter:mistral-small"
                        "openrouter:anthropic/claude-haiku-4-5"  (full name ก็ได้)

            **kwargs: ส่งต่อไปยัง constructor ของแต่ละ class

        Returns:
            LLMClient instance ที่พร้อมใช้งาน

        Raises:
            ValueError: ถ้า provider ไม่รู้จัก
            LLMUnavailableError: ถ้า client สร้างไม่ได้
        """
        provider_lower = provider.lower().strip()

        # ── colon syntax: "openrouter:model-name" ───────────────────────────
        if ":" in provider_lower:
            prefix, model_part = provider_lower.split(":", 1)
            if prefix == "openrouter":
                # model_part อาจเป็น shortcut หรือ full string
                # resolve ให้ OpenRouterClient จัดการใน __init__
                kwargs.setdefault("model", model_part)
                return OpenRouterClient(**kwargs)
            raise ValueError(
                f"Colon syntax only supported for 'openrouter'. Got: '{provider}'"
            )

        if provider_lower not in cls._REGISTRY:
            available = ", ".join(cls._REGISTRY.keys())
            raise ValueError(
                f"Unknown provider: '{provider}'.\n"
                f"  Available: {available}\n"
                f"  OpenRouter shortcut: openrouter:claude-haiku | openrouter:llama-70b | ..."
            )

        client_class = cls._REGISTRY[provider_lower]
        return client_class(**kwargs)

    @classmethod
    def available_providers(cls) -> list[str]:
        """คืนรายชื่อ provider ที่รองรับทั้งหมด"""
        return list(cls._REGISTRY.keys())

    @classmethod
    def register(cls, name: str, client_class: type[LLMClient]) -> None:
        """
        Register provider ใหม่ (Extensibility hook)

        Args:
            name: ชื่อ provider (lowercase)
            client_class: class ที่ extends LLMClient
        """
        if not issubclass(client_class, LLMClient):
            raise TypeError(f"{client_class} must be a subclass of LLMClient")
        cls._REGISTRY[name.lower()] = client_class