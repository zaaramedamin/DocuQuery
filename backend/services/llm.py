"""
Thin helpers around the Gemini client shared by reformulation, reranking,
summaries and OCR, so model-specific settings live in one place.
"""

import json
import re
from typing import Any

from google.genai import types

from config import gemini_client, GENERATION_MODEL


def generation_config(max_output_tokens: int, json_output: bool = False) -> types.GenerateContentConfig:
    """
    Gemini 3 models "think" before answering, and those thinking tokens count
    toward max_output_tokens. Keep thinking low so replies stay fast.
    Older models (gemini-2.5-*) don't accept this setting, so they keep
    their default.
    """
    thinking = (
        types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
        if GENERATION_MODEL.startswith("gemini-3")
        else None
    )
    return types.GenerateContentConfig(
        max_output_tokens=max_output_tokens,
        thinking_config=thinking,
        response_mime_type="application/json" if json_output else None,
    )


def generate_text(contents: Any, *, model: str | None = None, max_output_tokens: int = 1024) -> str:
    """One-shot text generation. Raises if the client is missing or the call fails."""
    if not gemini_client:
        raise RuntimeError("Gemini client is not initialized (GEMINI_API_KEY missing).")
    resp = gemini_client.models.generate_content(
        model=model or GENERATION_MODEL,
        contents=contents,
        config=generation_config(max_output_tokens),
    )
    return (resp.text or "").strip()


def parse_json_loose(text: str) -> Any | None:
    """
    Parse JSON from model output. Tolerates ```json fences and prose around
    the payload; returns None when nothing parseable is found.
    """
    if not text:
        return None
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the first {...} or [...] block in the text.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def generate_json(contents: Any, *, model: str | None = None, max_output_tokens: int = 1024) -> Any | None:
    """One-shot generation that returns parsed JSON (or None if unparseable)."""
    if not gemini_client:
        raise RuntimeError("Gemini client is not initialized (GEMINI_API_KEY missing).")
    resp = gemini_client.models.generate_content(
        model=model or GENERATION_MODEL,
        contents=contents,
        config=generation_config(max_output_tokens, json_output=True),
    )
    return parse_json_loose(resp.text or "")
