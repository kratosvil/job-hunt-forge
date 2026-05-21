import json
from typing import Any

import anthropic
import google.generativeai as genai
from loguru import logger

from config.settings import settings


class LLMClient:
    """
    Provider-agnostic LLM client.

    Routes requests to Gemini or Anthropic based on DEFAULT_LLM_PROVIDER.
    Always returns parsed JSON when json_mode=True.
    """

    def __init__(self) -> None:
        self._provider = settings.default_llm_provider
        if self._provider == "gemini":
            genai.configure(api_key=settings.gemini_api_key)
            self._gemini = genai.GenerativeModel("gemini-1.5-flash")
        elif self._provider == "anthropic":
            self._anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def complete(self, prompt: str, json_mode: bool = False) -> Any:
        logger.debug(f"LLM call via {self._provider} (json_mode={json_mode})")
        if self._provider == "gemini":
            return self._gemini_complete(prompt, json_mode)
        return self._anthropic_complete(prompt, json_mode)

    def _gemini_complete(self, prompt: str, json_mode: bool) -> Any:
        config = {"response_mime_type": "application/json"} if json_mode else {}
        response = self._gemini.generate_content(prompt, generation_config=config)
        text = response.text.strip()
        if json_mode:
            return json.loads(text)
        return text

    def _anthropic_complete(self, prompt: str, json_mode: bool) -> Any:
        message = self._anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        if json_mode:
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        return text


llm = LLMClient()
