"""Pure helpers for ORBITclip Qt view; safe to exercise without Qt.

Parsing handles pasted TSV/CSV/semicolon/Markdown tables (maximum 5 rows
rendered, with overflow noted); only ordinary HTTPS links may be opened.
"""
from __future__ import annotations
import csv
import io
import re
from urllib.parse import urlparse

MAX_PREVIEW_ROWS = 5
MAX_PREVIEW_COLUMNS = 6


def next_nonempty_category(categories, current, has_items):
    """Walk circularly forward, omitting empty categories; never return None."""
    if not categories:
        return 0
    current = int(current) % len(categories)
    for offset in range(1, len(categories) + 1):
        index = (current + offset) % len(categories)
        if has_items(categories[index][0]):
            return index
    return current


def safe_web_url(text):
    if not isinstance(text, str) or text.strip() != text or '\n' in text or '\r' in text:
        return ''
    try:
        parsed = urlparse(text)
    except ValueError:
        return ''
    if parsed.scheme.lower() not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        return ''
    if any(ord(c) < 32 for c in text):
        return ''
    return text


def _markdown_table(lines):
    if len(lines) < 2 or not lines[0].lstrip().startswith('|'):
        return None
    def split(line):
        return [c.strip() for c in line.strip().strip('|').split('|')]
    heads = split(lines[0]); sep = split(lines[1])
    if len(heads) < 2 or len(sep) != len(heads):return None
    if not all(re.fullmatch(r':?-{3,}:?', piece) for piece in sep):return None
    rows = [split(line) for line in lines[2:] if line.strip().startswith('|')]
    return heads, rows


def parse_table_preview(text, max_rows=MAX_PREVIEW_ROWS, max_cols=MAX_PREVIEW_COLUMNS):
    """Return (column labels, rows, remaining row count) or None.

    CSV and TSV are parsed with stdlib to support quoted commas/newlines.
    Only bounded text is parsed to keep the GUI responsive.
    """
    if not isinstance(text,str) or len(text)>200_000:return None
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines)<2:return None
    markdown = _markdown_table(lines)
    if markdown:
        header, rows = markdown
    else:
        raw = '\n'.join(lines)
        options = ['\t', ';', ',']
        candidate = None
        for delim in options:
            try:
                parsed = list(csv.reader(io.StringIO(raw),delimiter=delim))
            except csv.Error:
                continue
            if len(parsed) < 2:continue
            widths = [len(r) for r in parsed if r]
            if not widths or min(widths)<2 or len(set(widths))!=1:continue
            candidate = parsed;break
        if candidate is None:return None
        header, rows = candidate[0], candidate[1:]
    if len(header)<2:return None
    width=min(len(header),max_cols)
    labels=[str(c).strip()[:38] or f'Колонка {i+1}' for i,c in enumerate(header[:width])]
    if len(header)>width:labels[-1] += ' …'
    data=[[str(cell).strip().replace('\n',' ↵ ')[:90] for cell in row[:width]] for row in rows[:max_rows]]
    return labels, data, max(0,len(rows)-len(data))
