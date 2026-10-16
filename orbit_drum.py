"""Frameless, smoothly rotating cylindrical clipboard switcher for Qt.

No focus is taken from the user's active application. Transparency is genuine:
there is no full-window card or border, only the floating cylinder facets.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
    QPolygonF, QRadialGradient, QBrush,
)
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QWidget

from orbit_drum_geometry import next_target, visible_faces
from orbit_drum_styles import DRUM_STYLES, normalize_drum_style


class DrumBubble(QWidget):
    """Three-dimensional clipboard wheel: QPainter perspective + eased rotation."""

    def __init__(self, app):
        super().__init__(None)
        self.app = app
        self.style_name = normalize_drum_style(getattr(app, 'drum_style', 'minimal'))
        self.animate_categories = bool(getattr(app, 'animate_drum_categories', True))
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint |
            Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.setAutoFillBackground(False)
        self.setFixedSize(390, 302)
        self.heading = 'Буфер обмена'
        self.position = ''
        self.items = ['', '', '']
        self._entries = []
        self._keys = ()
        self._cursor = 0.0
        self._target = 0
        self._static_mode = False
        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._set_cursor)
        self._animation.finished.connect(self._finish_animation)
        self._category_frame = None
        self._category_progress = 1.0
        self._category_animation = QVariantAnimation(self)
        self._category_animation.setDuration(215)
        self._category_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._category_animation.valueChanged.connect(self._set_category_progress)
        self._category_animation.finished.connect(self._finish_category_transition)

    def set_style(self, value):
        self.style_name = normalize_drum_style(value)
        self.update()

    def set_category_animation(self, enabled):
        self.animate_categories = bool(enabled)
        if not self.animate_categories:
            self._category_animation.stop()
            self._category_frame = None
            self._category_progress = 1.0
            self.update()

    def _begin_category_transition(self, next_heading):
        if str(next_heading) == self.heading or not self.isVisible() or not self._entries:
            return
        self._category_animation.stop()
        self._category_frame = (self.heading, self.position,
                                list(self._entries), self._cursor, self._static_mode)
        if self.animate_categories:
            self._category_progress = 0.0
            self._category_animation.setStartValue(0.0)
            self._category_animation.setEndValue(1.0)
            self._category_animation.start()
        else:
            self._category_frame = None
            self._category_progress = 1.0

    def _set_category_progress(self, value):
        self._category_progress = float(value)
        self.update()

    def _finish_category_transition(self):
        self._category_progress = 1.0
        self._category_frame = None
        self.update()

    @staticmethod
    def _preview(item):
        if item.get('encrypted'):
            return '••• Защищённая запись'
        value = str(item.get('text') or item.get('title') or '')
        return ' '.join(value.split())[:220] or 'Пустая запись'

    @staticmethod
    def _id(item):
        # The clip ID stays stable while metadata/text may be updated in place.
        return str(item.get('id', item.get('text', item.get('title', ''))))

    def show_neighbors(self, choices, index, category, step_hint=0):
        if not choices:
            return self.show_empty(category)
        count = len(choices)
        index %= count
        old_keys = self._keys
        keys = tuple(self._id(item) for item in choices)
        old_heading = self.heading
        visible_before = self.isVisible()
        self._begin_category_transition(category)
        self.heading = str(category)
        self.position = f'{index + 1} / {count}'
        self.items = [self._preview(choices[(index - 1) % count]),
                      self._preview(choices[index]),
                      self._preview(choices[(index + 1) % count])]
        self._entries = list(choices)
        self._keys = keys
        self._static_mode = False

        # A new category, list, or popup gets a fresh position, no flying jump.
        if not visible_before or keys != old_keys or old_heading != self.heading or count == 1:
            self._animation.stop()
            self._target = index
            self._cursor = float(index)
        else:
            target = next_target(self._target, index, count, step_hint)
            if target != self._target:
                starting = self._cursor
                self._animation.stop()
                self._target = target
                self._animation.setStartValue(starting)
                self._animation.setEndValue(float(target))
                # Fast wheel ticks accelerate instead of spawning queued animations.
                distance = abs(target - starting)
                self._animation.setDuration(max(95, min(285, int(145 + 38 * distance))))
                self._animation.start()
        self._display()

    def show_item(self, item, cat_label, index, total):
        """Compatibility with the compact switcher's direct-single-item API."""
        self._animation.stop()
        self._begin_category_transition(cat_label)
        self.heading = str(cat_label)
        self.position = f'{index + 1} / {total}'
        self.items = ['', self._preview(item), '']
        self._entries = [item]
        self._keys = (self._id(item),)
        self._static_mode = True
        self._cursor = 0.0
        self._target = 0
        self._display()

    def show_empty(self, category):
        self._animation.stop()
        self._begin_category_transition(category)
        self.heading = str(category)
        self.position = '0 / 0'
        self.items = ['', 'Нет записей', '']
        self._entries = [{'text': 'Нет записей'}]
        self._keys = ()
        self._static_mode = True
        self._cursor = 0.0
        self._target = 0
        self._display()

    def _set_cursor(self, value):
        self._cursor = float(value)
        self.update()

    def _finish_animation(self):
        self._cursor = float(self._target)
        self.update()

    def hideEvent(self, event):
        self._animation.stop()
        self._category_animation.stop()
        self._category_frame = None
        self._category_progress = 1.0
        super().hideEvent(event)

    def _display(self):
        clock = self.app.clock
        screen = QApplication.screenAt(clock.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + 10, min(area.right() - self.width() - 10,
                    clock.frameGeometry().center().x() - self.width() // 2))
            desired = clock.y() + clock.height() + 9
            if desired + self.height() + 12 > area.bottom():
                desired = clock.y() - self.height() - 9
            y = max(area.top() + 10, min(area.bottom() - self.height() - 10, desired))
            self.move(x, y)
        self.update()
        if not self.isVisible():
            self.show()
        self.raise_()

    def _draw_face(self, painter, face, preview, pal):
        skin = DRUM_STYLES[self.style_name]
        intensity = face['opacity']
        y0, y1 = face['top_y'], face['bottom_y']
        if intensity <= .015 or y1 - y0 < 7:
            return
        cx = (face['top_left'] + face['top_right']) / 2
        polygon = QPolygonF([
            QPointF(face['top_left'], y0), QPointF(face['top_right'], y0),
            QPointF(face['bottom_right'], y1), QPointF(face['bottom_left'], y1),
        ])
        shape = QPainterPath()
        shape.addPolygon(polygon)
        shape.closeSubpath()

        # A restrained ambient shadow gives the active face a little separation.
        if abs(face['relative']) < .65:
            painter.save()
            painter.translate(0, 3)
            shadow = QColor(0, 0, 0, int(skin['shadow'] * intensity))
            painter.fillPath(shape, shadow)
            painter.restore()

        material=skin['material']
        if material=='glass':
            top=QColor('#497F94');bottom=QColor('#152F43')
        elif material=='metal':
            top=QColor('#A7B2BC');bottom=QColor('#465563')
        elif material=='obsidian':
            top=QColor('#292438');bottom=QColor('#080D18')
        else:
            top=QColor(pal['raised']);bottom=QColor(pal['surface'])
        # Front is gently lifted; rear strips darken as they curve away.
        top.setAlpha(int((skin['top_alpha'] if intensity > .72 else skin['top_alpha']*.86) * intensity))
        bottom.setAlpha(int((skin['bottom_alpha'] if intensity > .72 else skin['bottom_alpha']*.78) * intensity))
        grad = QLinearGradient(cx, y0, cx, y1)
        grad.setColorAt(0, top)
        grad.setColorAt(.43, QColor(top))
        grad.setColorAt(1, bottom)
        painter.fillPath(shape, QBrush(grad))

        # Curved specular band, clipped to the projected face.
        # Material presets change reflectivity, not drum geometry.
        painter.save()
        painter.setClipPath(shape)
        sheen = QLinearGradient(face['top_left'], y0, face['top_right'], y0)
        bright = QColor(skin['highlight'])
        bright.setAlpha(int(skin['reflection'] * intensity))
        dark = QColor(pal['bg'])
        dark.setAlpha(int(34 * intensity))
        clear = QColor(bright); clear.setAlpha(0)
        sheen.setColorAt(0.0, dark)
        sheen.setColorAt(.16, clear)
        sheen.setColorAt(.31, bright)
        sheen.setColorAt(.37, clear)
        sheen.setColorAt(.77, clear)
        sheen.setColorAt(1.0, dark)
        painter.fillPath(shape, QBrush(sheen))
        if skin['texture'] and abs(face['relative']) < .7:
            # Fine horizontal brushed-metal grain (low contrast and cheap to paint).
            grain = QColor(pal['text'])
            grain.setAlpha(int(skin['texture'] * intensity))
            painter.setPen(QPen(grain, .45))
            for scan in range(int(y0) + 5, int(y1) - 2, 4):
                painter.drawLine(QPointF(face['top_left']+10, scan),
                                 QPointF(face['top_right']-10, scan))
        painter.restore()

        # Avoid enclosing the drum in an outer window border: only facet edges.
        edge = QColor(pal['border'])
        edge.setAlpha(int(skin['edge'] * intensity))
        painter.setPen(QPen(edge, .7))
        painter.drawLine(QPointF(face['top_left'], y0), QPointF(face['top_right'], y0))
        painter.drawLine(QPointF(face['bottom_left'], y1), QPointF(face['bottom_right'], y1))

        # The pair of fine rails catches light at the cylinder's edges.
        rim = QColor(pal['text'])
        rim.setAlpha(int(skin['rim'] * intensity))
        painter.setPen(QPen(rim, .8))
        painter.drawLine(QPointF(face['top_left'] + 3, y0+2), QPointF(face['bottom_left'] + 3, y1-2))
        painter.drawLine(QPointF(face['top_right'] - 3, y0+2), QPointF(face['bottom_right'] - 3, y1-2))

        # Material details must be obvious at a glance, not alpha variations.
        if material=='glass':
            painter.save()
            painter.setClipPath(shape)
            glass_shine=QColor('#E3F8FF');glass_shine.setAlpha(int(108*intensity))
            painter.setPen(QPen(glass_shine,1.15))
            painter.drawLine(QPointF(face['top_left']+21,y0+2),
                             QPointF(face['bottom_left']+44,y1-2))
            painter.drawLine(QPointF(face['top_right']-24,y0+2),
                             QPointF(face['bottom_right']-15,y1-2))
            if abs(face['relative'])<.55:
                for at in (face['top_left']+18,face['top_right']-18):
                    painter.setBrush(QColor(176,229,245,int(93*intensity)))
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(QPointF(at,(y0+y1)/2),3,3)
            painter.restore()
        elif material=='metal':
            painter.save()
            painter.setClipPath(shape)
            steel=QColor('#DCE3E8');steel.setAlpha(int(126*intensity))
            steel_dark=QColor('#101822');steel_dark.setAlpha(int(125*intensity))
            for at in (face['top_left']+13,face['top_right']-13):
                middle=(y0+y1)/2
                painter.setPen(QPen(steel_dark,1.1));painter.setBrush(steel)
                painter.drawEllipse(QPointF(at,middle),3.7,3.7)
                painter.setPen(QPen(steel_dark,1))
                painter.drawLine(QPointF(at-2,middle),QPointF(at+2,middle))
            painter.setPen(QPen(steel_dark,1.1))
            for tick in range(int(face['top_left'])+26,int(face['top_right'])-26,19):
                painter.drawLine(QPointF(tick,y0+3),QPointF(tick+4,y0+3))
            painter.restore()
        elif material=='obsidian':
            painter.save()
            painter.setClipPath(shape)
            accent=QColor(skin['highlight'])
            accent.setAlpha(int(215*intensity))
            painter.setPen(QPen(accent,2.1,Qt.SolidLine,Qt.RoundCap))
            painter.drawLine(QPointF(face['top_right']-11,y0+9),
                             QPointF(face['bottom_right']-11,y1-9))
            painter.setBrush(accent);painter.setPen(Qt.NoPen)
            if abs(face['relative'])<.55:
                painter.drawEllipse(QPointF(face['top_right']-25,(y0+y1)/2),4,4)
            painter.restore()

        is_front = abs(face['relative']) < .52
        if is_front:
            accent = QColor(pal['accent'])
            accent.setAlpha(int(skin['accent'] * intensity))
            painter.setPen(QPen(accent, 2.2, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(face['top_left'] + 8, y0 + 13),
                             QPointF(face['bottom_left'] + 8, y1 - 13))

        painter.save()
        painter.setClipPath(shape)
        font = QFont(painter.font())
        font.setPixelSize(13 if is_front else max(10, int(12 * max(.78, face['facing']))))
        font.setWeight(QFont.DemiBold if is_front else QFont.Normal)
        painter.setFont(font)
        fg = QColor('#0E202B' if material=='metal' and is_front else
                    '#F0F6F9' if material in ('glass','obsidian') and is_front else
                    pal['text'] if is_front else pal['muted'])
        fg.setAlpha(int((247 if is_front else 195) * intensity))
        painter.setPen(fg)
        horizontal = min(face['top_left'], face['bottom_left']) + 23
        width = max(face['top_right'], face['bottom_right']) - horizontal - 20
        metrics = QFontMetrics(font)
        if is_front and y1 - y0 >= 49:
            # Split into two deliberate, elided lines rather than overflow facets.
            text = preview
            line_one = metrics.elidedText(text, Qt.ElideRight, int(width * 1.77))
            cut = min(len(text), max(1, len(line_one.rstrip('…'))))
            if cut >= len(text):
                first = metrics.elidedText(text, Qt.ElideRight, int(width))
                second = ''
            else:
                preferred = text.rfind(' ', 8, cut + 1)
                if preferred >= int(cut * .55):
                    cut = preferred
                first = metrics.elidedText(text[:cut].strip(), Qt.ElideRight, int(width))
                second = metrics.elidedText(text[cut:].strip(), Qt.ElideRight, int(width))
            line_h = metrics.height()
            total_h = line_h * (2 if second else 1)
            top_y = (y0 + y1 - total_h) / 2
            painter.drawText(QRectF(horizontal, top_y, width, line_h + 2),
                             Qt.AlignVCenter | Qt.AlignLeft, first)
            if second:
                painter.drawText(QRectF(horizontal, top_y + line_h, width, line_h + 2),
                                 Qt.AlignVCenter | Qt.AlignLeft, second)
        else:
            label = metrics.elidedText(preview, Qt.ElideRight, int(width))
            painter.drawText(QRectF(horizontal, y0 + 2, width, max(1, y1-y0-4)),
                             Qt.AlignVCenter | Qt.AlignLeft, label)
        painter.restore()

    def _paint_scene(self, painter, pal, heading, position, entries, cursor, static_mode):
        # A floating category badge is legible even over bright desktop windows.
        badge = QRectF(19, 5, 278, 34)
        painter.setPen(QPen(QColor(pal['border']), .9))
        pill = QLinearGradient(badge.left(), badge.top(), badge.left(), badge.bottom())
        top = QColor(pal['raised']); top.setAlpha(246)
        bottom = QColor(pal['surface']); bottom.setAlpha(240)
        pill.setColorAt(0, top); pill.setColorAt(1, bottom)
        painter.setBrush(QBrush(pill))
        painter.drawRoundedRect(badge, 11, 11)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(pal['accent']))
        painter.drawEllipse(QRectF(31, 19, 7, 7))
        font = QFont(painter.font())
        font.setPixelSize(13); font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        painter.setPen(QColor(pal['text']))
        label = metrics.elidedText(str(heading), Qt.ElideRight, 235)
        painter.drawText(QRectF(48, 9, 237, 25), Qt.AlignVCenter | Qt.AlignLeft, label)

        font.setPixelSize(11); font.setWeight(QFont.Medium)
        painter.setFont(font)
        painter.setPen(QColor(pal['muted']))
        painter.drawText(QRectF(303, 10, 67, 22),
                         Qt.AlignVCenter | Qt.AlignRight, str(position))
        if not entries:
            return

        skin = DRUM_STYLES[self.style_name]
        halo = QRadialGradient(QPointF(195, 158), 172, QPointF(195, 158))
        glow = QColor(pal['bg'])
        glow.setAlpha(skin['halo'])
        halo.setColorAt(0, glow)
        glow.setAlpha(0)
        halo.setColorAt(1, glow)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(QRectF(5, 38, 380, 245))
        if static_mode:
            faces = [face for face in visible_faces(0.0, count=1)
                     if face['relative'] == 0]
        else:
            faces = visible_faces(cursor, count=len(entries))
        painter.save()
        factor=skin.get('width_scale',1.0)
        painter.translate(195,0)
        painter.scale(factor,1.0)
        painter.translate(-195,0)
        for face in faces:
            self._draw_face(painter, face, self._preview(entries[face['index']]), pal)
        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = self.app.palette
        if self._category_frame is not None and self._category_progress < 1.0:
            progress = self._category_progress
            old_title, old_position, old_entries, old_cursor, old_static = self._category_frame
            # Adjacent category cylinders exchange positions with a soft lateral
            # displacement. No extra top-level windows, and rapid cycling remains safe.
            painter.save()
            painter.setOpacity(1.0 - progress)
            painter.translate(-26.0 * progress, 0)
            self._paint_scene(painter, pal, old_title, old_position,
                              old_entries, old_cursor, old_static)
            painter.restore()
            painter.save()
            painter.setOpacity(progress)
            painter.translate(24.0 * (1.0 - progress), 0)
            self._paint_scene(painter, pal, self.heading, self.position,
                              self._entries, self._cursor, self._static_mode)
            painter.restore()
        else:
            self._paint_scene(painter, pal, self.heading, self.position,
                              self._entries, self._cursor, self._static_mode)
        painter.end()
