"""
Translator — text translation via local Ollama LLM (no API key needed).
"""

import json
import requests
from typing import Optional

from config import OLLAMA_URL, RESPONDER_MODEL


class Translator:

    @staticmethod
    def translate(text: str, target_lang: str,
                  source_lang: str = None,
                  ollama_url: str = None,
                  model: str = None) -> str:
        """Translate text to target language using local Ollama."""
        url = (ollama_url or OLLAMA_URL).rstrip("/api").rstrip("/") + "/api/chat"
        model = model or RESPONDER_MODEL

        source = f" from {source_lang}" if source_lang else ""
        prompt = (
            f"Translate the following text{source} to {target_lang}. "
            f"Return ONLY the translated text, no explanation, no quotation marks.\n\n"
            f"Text: {text}"
        )

        try:
            resp = requests.post(
                url,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            translated = result.get("message", {}).get("content", "").strip()
            translated = translated.strip('"').strip("'")
            return translated if translated else text
        except Exception:
            return None

    @staticmethod
    def detect_language(text: str,
                        ollama_url: str = None,
                        model: str = None) -> Optional[str]:
        """Detect the language of given text using local Ollama."""
        url = (ollama_url or OLLAMA_URL).rstrip("/api").rstrip("/") + "/api/chat"
        model = model or RESPONDER_MODEL

        prompt = (
            f"What language is this text written in? "
            f"Answer with ONLY the language name (e.g. 'French', 'Spanish', 'English'). "
            f"Nothing else.\n\nText: {text}"
        )

        try:
            resp = requests.post(
                url,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get("message", {}).get("content", "").strip()
        except Exception:
            return None

    @staticmethod
    def languages() -> list:
        """Return a list of common language names the translator supports."""
        return [
            "Arabic", "Chinese", "Czech", "Danish", "Dutch", "English",
            "Finnish", "French", "German", "Greek", "Hebrew", "Hindi",
            "Hungarian", "Indonesian", "Italian", "Japanese", "Korean",
            "Norwegian", "Polish", "Portuguese", "Romanian", "Russian",
            "Spanish", "Swedish", "Thai", "Turkish", "Ukrainian", "Vietnamese",
        ]


translator = Translator()
