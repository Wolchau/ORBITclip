"""Pure projection and animation helpers for the floating clipboard drum.

The geometry is intentionally independent of Qt so it can be regression-tested
on CI without a window system. Positive offsets travel down the drum.
"""
from __future__ import annotations

import math

FACE_STEP = math.radians(49)
FACE_HALF = math.radians(22.0)
VISIBILITY_LIMIT = math.radians(84)


def next_target(previous: int, selected: int, count: int, step_hint: int = 0) -> int:
    """Unwrap a cyclic list index into a continuous animated position.

    A wheel hint resolves the otherwise ambiguous direction for two items and
    preserves consecutive fast wheel ticks while a prior animation is running.
    """
    if count <= 1:
        return 0
    selected %= count
    step_hint = int(step_hint)
    if step_hint and (previous + step_hint) % count == selected:
        return previous + step_hint
    delta = (selected - previous) % count
    if delta > count / 2 or (count % 2 == 0 and delta == count / 2 and step_hint < 0):
        delta -= count
    return previous + delta


def face_geometry(relative: float, *, center_x: float = 195.0,
                  center_y: float = 158.0, radius: float = 100.0,
                  width: float = 346.0, step_degrees: float = 49.0,
                  half_degrees: float = 22.0):
    """Project a rectangular strip wrapped around a horizontal cylinder.

    Returns top/bottom widths and Y positions. The apparent height follows
    sin(angle) and naturally compresses towards both ends of the drum.
    """
    angle = relative * math.radians(step_degrees)
    if abs(angle) > VISIBILITY_LIMIT:
        return None
    half = math.radians(half_degrees)
    start = max(-math.pi / 2, angle - half)
    end = min(math.pi / 2, angle + half)
    y0 = center_y + radius * math.sin(start)
    y1 = center_y + radius * math.sin(end)
    top_width = width * (0.875 + 0.125 * math.cos(start))
    bottom_width = width * (0.875 + 0.125 * math.cos(end))
    facing = max(0.0, math.cos(angle))
    return {
        'angle': angle,
        'top_y': y0, 'bottom_y': y1,
        'top_left': center_x - top_width / 2,
        'top_right': center_x + top_width / 2,
        'bottom_left': center_x - bottom_width / 2,
        'bottom_right': center_x + bottom_width / 2,
        'height': y1 - y0,
        'facing': facing,
        'opacity': max(0.0, (facing - 0.08) / 0.92) ** 1.35,
    }


def visible_faces(cursor: float, *, count: int, extent: int = 3,
                  step_degrees: float = 49.0, half_degrees: float = 22.0,
                  center_y: float = 158.0, radius: float = 100.0,
                  width: float = 346.0):
    """Return sorted cylinder strips for a fractional cursor position."""
    if count <= 0:
        return []
    middle = math.floor(cursor)
    result = []
    for unwrapped in range(middle - extent, middle + extent + 2):
        relative = unwrapped - cursor
        face = face_geometry(relative, step_degrees=step_degrees,
                             half_degrees=half_degrees, center_y=center_y,
                             radius=radius, width=width)
        if face is not None and face['height'] > 0.5:
            face['index'] = unwrapped % count
            face['unwrapped'] = unwrapped
            face['relative'] = relative
            result.append(face)
    # Depth order: rear facets first, front facet last.
    result.sort(key=lambda f: f['facing'])
    return result
