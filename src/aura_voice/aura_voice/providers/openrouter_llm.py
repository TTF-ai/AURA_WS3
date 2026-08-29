"""OpenRouter LLM provider — fallback for Groq."""

import os
import json
import httpx

from .llm_provider import LLMProvider
from .groq_llm import ALLOWED_INTENTS, SYSTEM_PROMPT


class OpenRouterLLM(LLMProvider):
    """LLM intent extraction via OpenRouter API."""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        model: str = "meta-llama/llama-3.1-8b-instruct",
        timeout: float = 15.0,
    ):
        self.model = model
        self.timeout = timeout
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")

    def generate_intent(
        self,
        user_text: str,
        system_prompt: str = None,
        context: dict = None,
    ) -> dict:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY environment variable not set")

        ctx = context or {}

        prompt = SYSTEM_PROMPT.format(
            intents=", ".join(ALLOWED_INTENTS),
            authenticated=ctx.get("authenticated", False),
            username=ctx.get("username", "unknown"),
            language=ctx.get("preferred_language", "en"),
            follow_state=ctx.get("follow_state", "IDLE"),
            behavior=ctx.get("behavior", "UNKNOWN"),
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.1,
            "max_tokens": 256,
        }

        try:
            response = httpx.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            content = result["choices"][0]["message"]["content"]

            # Try to extract JSON from response
            # Sometimes models wrap JSON in markdown code blocks
            if "```" in content:
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    content = content[start:end]

            parsed = json.loads(content)

            intent = parsed.get("intent", "UNKNOWN")
            if intent not in ALLOWED_INTENTS:
                intent = "UNKNOWN"

            return {
                "intent": intent,
                "parameters": parsed.get("parameters", {}),
                "response_text": parsed.get("response_text", ""),
            }

        except (json.JSONDecodeError, KeyError):
            return {
                "intent": "UNKNOWN",
                "parameters": {},
                "response_text": "I didn't understand that.",
            }
        except httpx.TimeoutException:
            raise RuntimeError("OpenRouter LLM request timed out")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"OpenRouter LLM API error: {e.response.status_code}"
            )

    def is_available(self) -> bool:
        return bool(self.api_key)
