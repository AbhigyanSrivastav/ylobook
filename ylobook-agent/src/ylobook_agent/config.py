import getpass
import json
import os
import tempfile
import warnings
from pathlib import Path


def config_path() -> Path:
    return Path.home() / ".ylobook" / "config.json"


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text())
        if not isinstance(config, dict):
            raise TypeError
        return config
    except (OSError, TypeError, ValueError):
        raise RuntimeError(f"Cannot read Ylobook config at {path}. Check its JSON format.") from None


def save_config(config: dict) -> None:
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # A private temporary file + atomic replacement avoids truncated config and
    # the window of world-readable credentials before chmod.
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".config-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(config, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def groq_key(config: dict) -> str | None:
    value = os.getenv("GROQ_API_KEY") or config.get("groq_api_key")
    return value.strip() if isinstance(value, str) and value.strip() else None


def configure() -> None:
    config = load_config()
    prompt = "Groq API key (blank keeps existing): " if groq_key(config) else "Groq API key: "
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            key = getpass.getpass(prompt).strip()
        except getpass.GetPassWarning:
            raise RuntimeError("A terminal with hidden input is required, or set GROQ_API_KEY.") from None
    if key:
        config["groq_api_key"] = key
        save_config(config)
        print("Groq key saved in ~/.ylobook/config.json (owner-only permissions).")
    elif not groq_key(config):
        raise RuntimeError("No Groq API key supplied.")


def ensure_groq_key() -> str:
    key = groq_key(load_config())
    if not key:
        configure()
        key = groq_key(load_config())
    if not key:
        raise RuntimeError("A Groq key is required. Run ylobook config.")
    return key


def save_profile(url: str, profile: dict) -> None:
    config = load_config()
    config.setdefault("profiles", {})[url] = profile
    save_config(config)
