"""Small demo settings."""

import os
from urllib.parse import urlsplit

# Release-time default. Override with YLOBOOK_API_URL for local development.
DEFAULT_API_URL = "https://ylobook-api.onrender.com"
INTERESTS = ("AI Agents", "Developer Tools", "Startups", "Design", "Research")
POLL_SECONDS = 3


def api_url() -> str:
    url = os.getenv("YLOBOOK_API_URL", DEFAULT_API_URL).strip().rstrip("/")
    if not url:
        raise RuntimeError(
            "No Ylobook backend URL is configured. "
            "Set YLOBOOK_API_URL=http://localhost:8000 for local development."
        )
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username:
        raise RuntimeError("YLOBOOK_API_URL must be an HTTP(S) URL without embedded credentials.")
    return url
