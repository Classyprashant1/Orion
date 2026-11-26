"""Modular AI Language Model Provider Hook (Synopsis Section 5 #7 & Section 15).

ORION's primary mode is deterministic rule-based command processing.
When a user configures ORION_AI_PROVIDER=gemini or openai with a valid API key
in `.env`, ORION can answer general questions via `ask <question>` or optional
unmatched-command fallback.
"""

from __future__ import annotations

from typing import Any

import httpx

from orion.config import OrionConfig


class AIProviderModule:
    """Pluggable LLM adapter supporting Gemini and OpenAI REST APIs."""

    SYSTEM_INSTRUCTION = (
        "You are ORION, a concise, helpful desktop virtual assistant running on Windows. "
        "Keep answers clear, accurate, and under 3 sentences so they are pleasant to speak aloud."
    )

    def __init__(self, config: OrionConfig, timeout: float = 15.0) -> None:
        self.config = config
        self.timeout = timeout

    @property
    def provider_name(self) -> str:
        return self.config.ai_provider

    @property
    def is_configured(self) -> bool:
        if self.config.ai_provider == "gemini":
            return bool(self.config.gemini_api_key)
        if self.config.ai_provider == "openai":
            return bool(self.config.openai_api_key)
        return False

    def status_info(self) -> dict[str, Any]:
        return {
            "provider": self.config.ai_provider,
            "configured": self.is_configured,
            "model": (
                self.config.gemini_model
                if self.config.ai_provider == "gemini"
                else (
                    self.config.openai_model
                    if self.config.ai_provider == "openai"
                    else "none"
                )
            ),
        }

    def ask(self, prompt: str) -> str:
        """Query the configured LLM provider."""
        question = prompt.strip()
        if not question:
            raise ValueError("Please provide a question to ask.")
        if not self.is_configured:
            raise RuntimeError(
                "AI Question Answering is not configured. Set ORION_AI_PROVIDER (gemini or openai) "
                "and the corresponding API key in your .env file to enable it."
            )
        if self.config.ai_provider == "gemini":
            return self._ask_gemini(question)
        if self.config.ai_provider == "openai":
            return self._ask_openai(question)
        raise RuntimeError(f"Unsupported AI provider: {self.config.ai_provider}")

    def _ask_gemini(self, question: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.config.gemini_model}:generateContent"
        )
        payload = {
            "system_instruction": {"parts": [{"text": self.SYSTEM_INSTRUCTION}]},
            "contents": [{"parts": [{"text": question}]}],
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                url,
                params={"key": self.config.gemini_api_key},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise RuntimeError("Gemini returned an empty response.")
            parts = candidates[0].get("content", {}).get("parts", [])
            text = " ".join(p.get("text", "") for p in parts).strip()
            return text or "I did not receive a text answer from Gemini."

    def _ask_openai(self, question: str) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}
        payload = {
            "model": self.config.openai_model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_INSTRUCTION},
                {"role": "user", "content": question},
            ],
            "max_tokens": 220,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("OpenAI returned an empty response.")
            return str(choices[0]["message"]["content"]).strip()
