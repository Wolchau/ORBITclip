"""Read distributable connection defaults without overwriting a user's saved choices.

Defaults are plaintext and are not a secure way to distribute a relay token.
"""
from __future__ import annotations
import json
from pathlib import Path


def load_connection_defaults(file: str | Path) -> dict:
    """Return only supported nonempty string settings; ignore malformed files."""
    try:
        value=json.loads(Path(file).read_text(encoding='utf-8'))
    except (OSError,ValueError,UnicodeError):
        return {}
    if not isinstance(value,dict):return {}
    return {key:value[key].strip() for key in ('https_url','https_token')
            if isinstance(value.get(key),str) and value[key].strip()}


def resolve_connection_settings(settings: dict, file: str | Path, fallback_url: str) -> tuple[str,str]:
    """Keep existing settings if set; populate only blank connection fields."""
    initial=load_connection_defaults(file)
    url=str(settings.get('https_url') or settings.get('remote_url') or initial.get('https_url') or fallback_url)
    token=str(settings.get('https_token') or settings.get('remote_token') or initial.get('https_token') or '')
    return url,token
