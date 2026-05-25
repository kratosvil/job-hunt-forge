import json
from typing import Any

import anthropic
import boto3
import httpx
from google import genai
from google.genai import types
from loguru import logger

from config.settings import settings


class LLMClient:
    """
    Provider-agnostic LLM client.

    Routes requests to Gemini, Anthropic, or Ollama based on DEFAULT_LLM_PROVIDER.
    Always returns parsed JSON when json_mode=True.
    """

    _GEMINI_MODEL = "gemini-2.0-flash"

    def __init__(self) -> None:
        self._provider = settings.default_llm_provider
        if self._provider == "gemini":
            self._gemini = genai.Client(api_key=settings.gemini_api_key)
        elif self._provider == "anthropic":
            self._anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        elif self._provider == "ollama":
            self._ollama_url = settings.ollama_base_url.rstrip("/")
            self._ollama_model = settings.ollama_model
        elif self._provider == "bedrock":
            self._bedrock = boto3.client(
                "bedrock-runtime",
                region_name=settings.bedrock_region,
            )
            self._bedrock_model_id = settings.bedrock_model_id

    def complete(self, prompt: str, json_mode: bool = False) -> Any:
        logger.debug(f"LLM call via {self._provider} (json_mode={json_mode})")
        if self._provider == "gemini":
            return self._gemini_complete(prompt, json_mode)
        if self._provider == "ollama":
            return self._ollama_complete(prompt, json_mode)
        if self._provider == "bedrock":
            return self._bedrock_complete(prompt, json_mode)
        return self._anthropic_complete(prompt, json_mode)

    def _gemini_complete(self, prompt: str, json_mode: bool) -> Any:
        config = types.GenerateContentConfig(
            response_mime_type="application/json"
        ) if json_mode else None

        response = self._gemini.models.generate_content(
            model=self._GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
        text = response.text.strip()
        if json_mode:
            return json.loads(text)
        return text

    def _ollama_complete(self, prompt: str, json_mode: bool) -> Any:
        payload: dict[str, Any] = {
            "model": self._ollama_model,
            "prompt": prompt,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        response = httpx.post(
            f"{self._ollama_url}/api/generate",
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
        text = response.json()["response"].strip()
        if json_mode:
            return json.loads(text)
        return text

    def _bedrock_complete(self, prompt: str, json_mode: bool) -> Any:
        system = "Return only valid JSON, no markdown, no explanation." if json_mode else ""
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system

        response = self._bedrock.invoke_model(
            modelId=self._bedrock_model_id,
            body=json.dumps(body),
        )
        text = json.loads(response["body"].read())["content"][0]["text"].strip()
        if json_mode:
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        return text

    def _anthropic_complete(self, prompt: str, json_mode: bool) -> Any:
        message = self._anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        if json_mode:
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        return text


llm = LLMClient()
