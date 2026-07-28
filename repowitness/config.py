"""Configuration - env vars and defaults."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


_AUDIT_CONFIG_KEYS = {
    "base",
    "contracts-ref",
    "format",
    "output",
    "include-untracked",
    "check-results",
    "junit",
    "sarif",
    "evidence-snapshot",
    "fail-on",
}
_LIST_CONFIG_KEYS = {"check-results", "junit", "sarif", "fail-on"}


def load_audit_config(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError(f"{path}: configuration exceeds the 1 MB limit")
    try:
        payload = yaml.safe_load(raw.decode("utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: configuration must be a mapping")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError(f"{path}: top-level option names must be strings")
    unknown_top_level = set(payload) - {"version", "audit"}
    if unknown_top_level:
        raise ValueError(
            f"{path}: unknown top-level option: {sorted(unknown_top_level)[0]}"
        )
    if str(payload.get("version", "")) != "1":
        raise ValueError(f"{path}: version must be 1")
    audit = payload.get("audit", {})
    if not isinstance(audit, dict):
        raise ValueError(f"{path}: audit must be a mapping")
    if any(not isinstance(key, str) for key in audit):
        raise ValueError(f"{path}: audit option names must be strings")
    unknown = set(audit) - _AUDIT_CONFIG_KEYS
    if unknown:
        raise ValueError(f"{path}: unknown audit option: {sorted(unknown)[0]}")
    for key in _LIST_CONFIG_KEYS:
        if key not in audit:
            continue
        value = audit[key]
        if isinstance(value, str):
            audit[key] = [value]
        elif not isinstance(value, list) or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise ValueError(f"{path}: audit.{key} must be a string or string list")
    if "include-untracked" in audit and not isinstance(
        audit["include-untracked"], bool
    ):
        raise ValueError(f"{path}: audit.include-untracked must be a boolean")
    choices = {
        "contracts-ref": {"base", "head", "worktree"},
        "format": {"markdown", "json"},
    }
    for key, allowed in choices.items():
        if key in audit and (
            not isinstance(audit[key], str) or audit[key] not in allowed
        ):
            raise ValueError(
                f"{path}: audit.{key} must be one of {', '.join(sorted(allowed))}"
            )
    for key in {"base", "output", "evidence-snapshot"}:
        if key in audit and (
            not isinstance(audit[key], str) or not audit[key].strip()
        ):
            raise ValueError(f"{path}: audit.{key} must be a non-empty string")
    invalid_verdicts = set(audit.get("fail-on", ())) - {
        "fail",
        "warn",
        "unverified",
    }
    if invalid_verdicts:
        raise ValueError(
            f"{path}: invalid audit.fail-on verdict: {sorted(invalid_verdicts)[0]}"
        )
    return audit


def _load_dotenv():
    """Load .env from cwd, walking up to home dir. No-op if python-dotenv missing."""
    try:
        from dotenv import load_dotenv
        # search cwd first, then parent dirs up to ~
        env_path = Path(".env")
        if not env_path.exists():
            cur = Path.cwd()
            home = Path.home()
            while cur != home and cur != cur.parent:
                candidate = cur / ".env"
                if candidate.exists():
                    env_path = candidate
                    break
                cur = cur.parent
        load_dotenv(env_path, override=False)
    except ImportError:
        pass  # python-dotenv not installed, silently skip


@dataclass
class Config:
    model: str = "gpt-5.5"
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    max_context_tokens: int = 128_000
    provider: str = "openai"

    @classmethod
    def from_env(cls) -> "Config":
        # load .env if present (won't override existing env vars)
        _load_dotenv()
        # pick up common env vars automatically
        api_key = (
            os.getenv("REPOWITNESS_API_KEY")
            or os.getenv("CORECODER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or ""
        )
        return cls(
            model=(
                os.getenv("REPOWITNESS_MODEL")
                or os.getenv("CORECODER_MODEL")
                or "gpt-5.5"
            ),
            api_key=api_key,
            base_url=(
                os.getenv("REPOWITNESS_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
                or os.getenv("CORECODER_BASE_URL")
            ),
            max_tokens=int(
                os.getenv("REPOWITNESS_MAX_TOKENS")
                or os.getenv("CORECODER_MAX_TOKENS")
                or "4096"
            ),
            temperature=float(
                os.getenv("REPOWITNESS_TEMPERATURE")
                or os.getenv("CORECODER_TEMPERATURE")
                or "0"
            ),
            max_context_tokens=int(
                os.getenv("REPOWITNESS_MAX_CONTEXT")
                or os.getenv("CORECODER_MAX_CONTEXT")
                or "128000"
            ),
            provider=(
                os.getenv("REPOWITNESS_PROVIDER")
                or os.getenv("CORECODER_PROVIDER")
                or "openai"
            ),
        )
