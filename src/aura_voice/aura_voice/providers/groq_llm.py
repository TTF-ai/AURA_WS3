"""Groq LLM provider for intent extraction."""

import os
import json
import httpx

from .llm_provider import LLMProvider


ALLOWED_INTENTS = [
    "FOLLOW_USER",
    "STOP_FOLLOWING",
    "GO_TO_LOCATION",
    "STOP_ROBOT",
    "WHAT_ARE_YOU_DOING",
    "WHO_AM_I",
    "WHAT_IS_MY_LANGUAGE",
    "CHANGE_LANGUAGE",
    "HELP",
    "STATUS",
    "SEND_MESSAGE",
    "UNKNOWN",
]

SYSTEM_PROMPT = """You are AURA, a ROS 2 assistive robot. You help elderly and disabled users.

Strict rules:
1. You can ONLY choose from these intents: {intents}
2. Return EXACTLY one valid JSON object and nothing else.
3. Do not add markdown, code fences, commentary, or any text before/after the JSON.
4. If the user input is a greeting or a simple conversation, choose intent "UNKNOWN" unless the phrase clearly asks for a robot action.
5. Do not invent intents outside the list.
6. Do not output ROS commands, velocities, or action code.
7. Keep response_text short, friendly, and in the user's preferred language.

JSON format:
{{
  "intent": "<INTENT>",
  "parameters": {{}} ,
  "response_text": "<short response in user's preferred language>"
}}

For CHANGE_LANGUAGE, use: "parameters": {{"language": "en"}} or {{"language": "kn"}} or {{"language": "en+kn"}}

Current context:
- Authenticated user: {authenticated}
- Username: {username}
- Preferred language: {language}
- Follow state: {follow_state}
- Behavior: {behavior}
"""


class GroqLLM(LLMProvider):
    """LLM intent extraction via Groq API."""

    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, model: str = "openai/gpt-oss-20b", timeout: float = 10.0):
        self.model = model
        self.timeout = timeout
        self.api_key = os.environ.get("GROQ_API_KEY", "")

    @staticmethod
    def _extract_json_object(content: str):
        """Extract a JSON object from content that may contain markdown or text around it."""
        if not content:
            raise ValueError("empty content")

        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]

        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("JSON payload is not an object")
        return parsed

    def generate_intent(
        self,
        user_text: str,
        system_prompt: str = None,
        context: dict = None,
    ) -> dict:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY environment variable not set")

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
            parsed = self._extract_json_object(content)

            intent = parsed.get("intent", "UNKNOWN")
            if intent not in ALLOWED_INTENTS:
                intent = "UNKNOWN"

            return {
                "intent": intent,
                "parameters": parsed.get("parameters", {}),
                "response_text": parsed.get("response_text", "I didn't understand that."),
            }

        except (json.JSONDecodeError, KeyError, ValueError):
            return {
                "intent": "UNKNOWN",
                "parameters": {},
                "response_text": "I didn't understand that.",
            }

        except httpx.TimeoutException:
            raise RuntimeError("Groq LLM request timed out")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Groq LLM API error: {e.response.status_code} {e.response.text}"
            )

    def is_available(self) -> bool:
        return bool(self.api_key)
