"""Shared utility functions for API endpoints."""

from fastapi import Request


def get_user_locale(request: Request) -> str:
    """
    Get the user's preferred locale from Accept-Language header.

    Parses the Accept-Language header and returns a normalized locale string.
    Format: "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"

    Args:
        request: FastAPI request object

    Returns:
        Locale string (e.g., 'de-DE', 'en-US')
    """
    accept_language = request.headers.get("accept-language", "")
    if accept_language:
        languages = accept_language.split(",")
        if languages:
            primary_lang = languages[0].split(";")[0].strip()
            if primary_lang == "de" or primary_lang.startswith("de-"):
                return "de-DE"
            elif primary_lang == "en" or primary_lang.startswith("en-"):
                return "en-US"
            elif "-" in primary_lang:
                return primary_lang
    return "en-US"
