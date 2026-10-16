"""Clipboard Flow helpers: ephemeral sequential paste, source exclusions, and suggestions.

No SQL templates, background network requests, or persistent copied content.
"""
from collections import deque
from datetime import datetime
import re


class PasteQueue:
    MAX_ITEMS = 40

    def __init__(self):
        self._items = deque()

    def __len__(self):
        return len(self._items)

    def push(self, text):
        value = str(text or '')
        if not value or len(self._items) >= self.MAX_ITEMS:
            return False
        self._items.append(value)
        return True

    def pop(self):
        return self._items.popleft() if self._items else None

    def clear(self):
        self._items.clear()

    def preview(self):
        return [x.replace('\n', ' ↵ ')[:95] for x in self._items]


def normalize_exclusions(value):
    """Match actual foreground process name, never a window title or wildcard."""
    entries = value if isinstance(value, list) else []
    return sorted({str(v).strip().casefold()[:60] for v in entries
                   if str(v).strip() and len(str(v)) <= 60})


def is_excluded(app_name, exclusions):
    name = str(app_name or '').strip().casefold()
    return bool(name and name != 'неизвестно' and name in normalize_exclusions(exclusions))


def quick_actions(text, kind):
    """Small list of context-sensitive actions; never execute input."""
    from orbit_smart import action_catalog
    if not isinstance(text, str) or not text.strip() or len(text) > 200_000:
        return []
    suggestions = action_catalog(text, kind)
    return [entry for entry in suggestions if not entry.get('report')][:5]
