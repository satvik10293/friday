"""
core/security/validation.py — FRIDAY 4.0
Input validation + sanitization helpers used by the executor/policies (deeper than
a skill's own validate()). Schema validation, shell-command screening, and path
containment for the eventual file/automation skills.
"""

from __future__ import annotations

from pathlib import Path

from core.skills.exceptions import ValidationError

_SHELL_BLOCKLIST = (
    "rm -rf", "format", "del /f", "shutdown", "reboot", "mkfs", "dd if=",
    ":(){:|:&};:", "> /dev/sda", "diskpart",
)


def validate_args(schema: dict, args: dict) -> None:
    """Schema = {field: {'required': bool, 'type': type|tuple}}. Raises ValidationError."""
    for field, spec in schema.items():
        if spec.get("required") and field not in args:
            raise ValidationError(f"missing required arg '{field}'")
        if field in args and "type" in spec and not isinstance(args[field], spec["type"]):
            raise ValidationError(f"arg '{field}' has wrong type")


def sanitize_shell(command: str) -> str:
    """Raise if the command matches a known-dangerous pattern; else return it."""
    low = (command or "").lower()
    for bad in _SHELL_BLOCKLIST:
        if bad in low:
            raise ValidationError(f"blocked shell pattern: {bad!r}")
    return command


def is_safe_path(path: str | Path, allowed_roots: list[str | Path]) -> bool:
    """True if `path` resolves inside one of the allowed roots."""
    try:
        target = Path(path).resolve()
    except Exception:
        return False
    for root in allowed_roots:
        try:
            target.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False
