"""Pure and versioned drum preferences, geometry profiles, and screen placement.

All coordinates are logical Qt pixels; nothing assumes a primary display
or nonnegative desktop coordinates.
"""
SHAPES = {
    "compact": ("Компактный", (318, 226)),
    "classic": ("Классический", (390, 302)),
    "wide": ("Широкий", (522, 260)),
    "ribbon": ("Лента", (550, 186)),
}
POSITIONS = {
    "auto": "Автоматически · у курсора",
    "cursor_above": "Строго над курсором",
    "cursor_below": "Под курсором",
    "screen_center": "Центр монитора с курсором",
    "clock": "Рядом с виджетом часов",
}
HEADERS = {
    "full": "Плашка",
    "compact": "Компактный текст",
    "minimal": "Только название",
    "hidden": "Без заголовка",
}
HEADER_POSITIONS = {"top": "Сверху", "bottom": "Снизу"}
DEFAULTS = {
    "shape": "compact",
    "position": "auto",
    "opacity": 92,
    "neighbor_opacity": 45,
    "neighbor_gap": 20,
    "neighbors": 2,
    "header": "compact",
    "header_position": "top",
    "show_index": True,
}


def normalize_options(raw):
    raw = raw if isinstance(raw, dict) else {}
    value = DEFAULTS.copy()
    for key, accepted in (("shape", SHAPES), ("position", POSITIONS),
                          ("header", HEADERS), ("header_position", HEADER_POSITIONS)):
        if raw.get(key) in accepted:
            value[key] = raw[key]
    for key, low, high in (("opacity", 35, 100),
                           ("neighbor_opacity", 5, 100),
                           ("neighbor_gap", 0, 65),
                           ("neighbors", 1, 4)):
        try:
            value[key] = max(low, min(high, int(raw.get(key, DEFAULTS[key]))))
        except (ValueError, TypeError):
            pass
    value["show_index"] = bool(raw.get("show_index", True))
    return value


def place_popup(area, anchor, popup, mode="auto", *, margin=12):
    """Return top-left, bounded to a monitor availableGeometry (x,y,w,h).

    'cursor_above' really means above the mouse pointer; external text-caret
    bounds are intentionally NOT invented or guessed.
    """
    left, top, width, height = area
    px, py = anchor
    pw, ph = popup
    left, top, width, height = map(int, (left, top, width, height))
    px, py = int(px), int(py)
    pw, ph = int(pw), int(ph)
    if mode == "screen_center":
        x = left + (width - pw) // 2
        y = top + (height - ph) // 2
    elif mode == "clock":
        x = px - pw // 2
        y = py + 18
    else:
        x = px - pw // 2
        above = py - ph - 21
        below = py + 21
        if mode == "cursor_below":
            y = below if below + ph <= top + height - margin else above
        else:
            y = above if above >= top + margin else below
    max_x = left + width - pw - margin
    max_y = top + height - ph - margin
    x = min(max_x, max(left + margin, x)) if max_x >= left + margin else left
    y = min(max_y, max(top + margin, y)) if max_y >= top + margin else top
    return int(x), int(y)


def shape_size(options):
    return SHAPES[normalize_options(options)["shape"]][1]
