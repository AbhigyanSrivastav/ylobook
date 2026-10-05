"""Small demo settings. Set DEFAULT_API_URL to the verified deployment before release."""

import os
from urllib.parse import urlsplit

# Deliberately unset until a real deployment is provisioned; never send profiles
# to a guessed or unowned hostname. This is the only release-time URL setting.
DEFAULT_API_URL = ""
INTERESTS = ("AI Agents", "Developer Tools", "Startups", "Design", "Research")
POLL_SECONDS = 3


def api_url() -> str:
    url = os.getenv("YLOBOOK_API_URL", DEFAULT_API_URL).strip().rstrip("/")
    if not url:
        raise RuntimeError(
            "The public Ylobook demo has not been deployed yet. "
            "For development set YLOBOOK_API_URL=http://localhost:8000."
        )
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username:
        raise RuntimeError("YLOBOOK_API_URL must be an HTTP(S) URL without embedded credentials.")
    return url
