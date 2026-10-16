"""Central ORBITclip color themes; no Qt dependency or secret configuration."""
from __future__ import annotations

# Base UI stylesheet was designed for the Midnight palette. All other themes
# map its semantic colors rather than append fragile override stylesheets.
THEMES = {
    'midnight': {'name': 'Тёмная · Ночь', 'bg': '#101923', 'surface': '#17232E',
        'raised': '#202E3B', 'hover': '#293B49', 'input': '#1C2A35',
        'text': '#EAF1F5', 'muted': '#93A4B2', 'border': '#31424F',
        'accent': '#F7AA90', 'accent_text': '#1A2730', 'success': '#72D6BE'},
    'graphite': {'name': 'Тёмная · Графит', 'bg': '#171819', 'surface': '#232526',
        'raised': '#303333', 'hover': '#3B3E40', 'input': '#292C2E',
        'text': '#F0F0ED', 'muted': '#A0A8A8', 'border': '#4A4E50',
        'accent': '#D4A98D', 'accent_text': '#252422', 'success': '#99CCB5'},
    'ice': {'name': 'Тёмная · Лёд', 'bg': '#0C1D28', 'surface': '#122A38',
        'raised': '#1C3748', 'hover': '#23495C', 'input': '#142E3E',
        'text': '#EBF6FC', 'muted': '#9DBACB', 'border': '#335B70',
        'accent': '#83D8E9', 'accent_text': '#09232B', 'success': '#8DE3CE'},
    'warm': {'name': 'Тёмная · Песок', 'bg': '#211B1B', 'surface': '#302726',
        'raised': '#40322E', 'hover': '#4A3934', 'input': '#382C2A',
        'text': '#F6ECE3', 'muted': '#C4AD9D', 'border': '#59463F',
        'accent': '#EBB976', 'accent_text': '#30241A', 'success': '#ABCEAA'},
    'forest': {'name': 'Тёмная · Хвойный лес', 'bg': '#101D1B', 'surface': '#182B27',
        'raised': '#244039', 'hover': '#305046', 'input': '#1C342E',
        'text': '#E8F4EC', 'muted': '#A0B8AC', 'border': '#38574D',
        'accent': '#A8D9AD', 'accent_text': '#15291F', 'success': '#89CDB4'},
    'plum': {'name': 'Тёмная · Слива', 'bg': '#1C1625', 'surface': '#292135',
        'raised': '#382D46', 'hover': '#4C3A5A', 'input': '#30263E',
        'text': '#F4EBFA', 'muted': '#BCAACB', 'border': '#554566',
        'accent': '#D8B4E8', 'accent_text': '#21152C', 'success': '#A8D8C2'},
    'ocean': {'name': 'Тёмная · Океан', 'bg': '#0E1C29', 'surface': '#142B3A',
        'raised': '#1E3D4F', 'hover': '#295267', 'input': '#183242',
        'text': '#E9F4FA', 'muted': '#9EB9C8', 'border': '#345B70',
        'accent': '#8CCAE8', 'accent_text': '#102535', 'success': '#8EDAC9'},
    'cream': {'name': 'Светлая · Крем', 'bg': '#F5F0E7', 'surface': '#FFFCF6',
        'raised': '#EEE5D7', 'hover': '#E5D8C5', 'input': '#FCF6EC',
        'text': '#342D2A', 'muted': '#796C60', 'border': '#D1C2AF',
        'accent': '#A46250', 'accent_text': '#FFFFFF', 'success': '#377D69'},
    'light': {'name': 'Светлая · Бумага', 'bg': '#F2F4F6', 'surface': '#FFFFFF',
        'raised': '#E9EEF1', 'hover': '#DDE5EA', 'input': '#F7F9FB',
        'text': '#203343', 'muted': '#647786', 'border': '#B7C6D0',
        'accent': '#B5533E', 'accent_text': '#FFFFFF', 'success': '#277C64'},
}

# Every literal color in the original Qt stylesheet is considered part of its
# visual grammar and is translated to a semantic theme role.
BASE_COLORS = {
    '#101923': 'bg', '#17232E': 'surface', '#202E3B': 'raised',
    '#293B49': 'hover', '#1C2A35': 'input', '#1D2B37': 'raised',
    '#14212C': 'surface', '#263644': 'raised', '#273847': 'hover',
    '#33414D': 'hover', '#344857': 'hover', '#3C5363': 'hover',
    '#344957': 'hover', '#384C58': 'hover', '#1C2B38': 'surface',
    '#EAF1F5': 'text', '#ECF4F6': 'text', '#F2F5F7': 'text',
    '#F3F6F9': 'text', '#F3F5F6': 'text', '#F5F7F9': 'text',
    '#93A4B2': 'muted', '#92A3B2': 'muted', '#B9C9D4': 'muted',
    '#BBCBD3': 'muted', '#A7B8C3': 'muted', '#BCCBD3': 'muted',
    '#31424F': 'border', '#334552': 'border', '#304451': 'border',
    '#354957': 'border', '#3A4E5C': 'border', '#405565': 'border',
    '#607482': 'border', '#526677': 'muted', '#4E7781': 'hover',
    '#F7AA90': 'accent', '#E7A28E': 'accent', '#F6B08E': 'accent',
    '#FFB49B': 'accent', '#FFC2AC': 'accent', '#1A2730': 'accent_text',
}


def normalize_theme(value):
    return value if value in THEMES else 'midnight'


def palette(value):
    return THEMES[normalize_theme(value)]


def stylesheet(base: str, name: str):
    theme = palette(name)
    # A one-pass replacement avoids replacing colors already substituted.
    import re
    matcher = re.compile('|'.join(re.escape(x) for x in sorted(BASE_COLORS, key=len, reverse=True)), re.I)
    mapping = {old.lower(): theme[role] for old, role in BASE_COLORS.items()}
    return matcher.sub(lambda m: mapping[m.group().lower()], base)
