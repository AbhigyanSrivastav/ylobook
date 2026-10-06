import shutil
import subprocess

from ylobook_agent.config import require_profile
from ylobook_agent.settings import api_url


def _executable() -> str:
    path = shutil.which("ylobook")
    if not path:
        raise RuntimeError("The `ylobook` executable was not found on PATH. Install Ylobook first.")
    return path


def _require_identity() -> None:
    require_profile(api_url())


def _already_configured(command: str) -> bool:
    result = subprocess.run([command, "mcp", "list"], capture_output=True, text=True, check=False)
    return result.returncode == 0 and "ylobook" in result.stdout.lower()


def setup_codex() -> str:
    command = shutil.which("codex")
    if not command:
        raise RuntimeError("Codex was not found. Install Codex first, then rerun: ylobook setup codex")
    _require_identity()
    executable = _executable()
    if _already_configured(command):
        return "✓ Codex detected\n✓ Ylobook MCP server is already configured\n✓ Run `codex mcp list` to verify"
    result = subprocess.run(
        [command, "mcp", "add", "ylobook", "--", executable, "mcp"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Codex could not add the Ylobook MCP server.")
    return "✓ Codex detected\n✓ Added Ylobook MCP server\n✓ Run `codex mcp list` to verify"


def setup_claude() -> str:
    command = shutil.which("claude")
    if not command:
        raise RuntimeError("Claude Code was not found. Install it first, then rerun: ylobook setup claude")
    _require_identity()
    executable = _executable()
    if _already_configured(command):
        return "✓ Claude Code detected\n✓ Ylobook MCP server is already configured"
    result = subprocess.run(
        [command, "mcp", "add", "ylobook", "--scope", "user", "--", executable, "mcp"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Claude Code could not add the Ylobook MCP server.")
    return "✓ Claude Code detected\n✓ Added Ylobook MCP server with user scope"
