"""Frameless, smoothly rotating cylindrical clipboard switcher for Qt.

No focus is taken from the user's active application. Transparency is genuine:
there is no full-window card or border, only the floating cylinder facets.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import (
    QCursor, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
    QPolygonF, QRadialGradient, QBrush,
)
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QWidget

from orbit_drum_geometry import next_target, visible_faces
from orbit_drum_styles import DRUM_STYLES, normalize_drum_style
from orbit_drum_layout import DEFAULTS, normalize_options, place_popup, shape_size


class DrumBubble(QWidget):
    """Three-dimensional clipboard wheel: QPainter perspective + eased rotation."""

    def __init__(self, app):
        super().__init__(None)
        self.app = app
        self.style_name = normalize_drum_style(getattr(app, 'drum_style', 'minimal'))
        self.animate_categories = bool(getattr(app, 'animate_drum_categories', True))
        self.options = normalize_options(getattr(app, 'drum_options', DEFAULTS))
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint |
            Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.setAutoFillBackground(False)
        self.setFixedSize(*shape_size(self.options))
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

    def set_options(self, options):
        self.options = normalize_options(options)
        size = shape_size(self.options)
        if (self.width(), self.height()) != size:
            self.setFixedSize(*size)
        if self.isVisible():
            self._display()
        else:
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
        # Pointer location, not the clock widget, determines the current screen.
        # Qt desktop coordinates may be negative (left/upper secondary display).
        mode = self.options['position']
        pointer = QCursor.pos()
        clock = self.app.clock
        clock_center = clock.frameGeometry().center()
        anchor = clock_center if mode == 'clock' else pointer
        screen = (QApplication.screenAt(anchor)
                  or QApplication.screenAt(pointer)
                  or QApplication.primaryScreen())
        if screen is not None:
            # Explicitly move the native tool window to the target QScreen.
            # Without this, macOS may keep a Qt.Tool window on its first screen.
            self.winId()
            handle = self.windowHandle()
            if handle is not None and handle.screen() is not screen:
                handle.setScreen(screen)
            region = screen.availableGeometry()
            if mode == 'clock':
                anchor = clock.frameGeometry().bottomLeft()
                anchor.setX(clock_center.x())
            x, y = place_popup(
                (region.x(), region.y(), region.width(), region.height()),
                (anchor.x(), anchor.y()), (self.width(), self.height()), mode)
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
            top=QColor(pal['accent']).lighter(115)
            bottom=QColor(pal['raised']).darker(125)
        elif material=='metal':
            top=QColor(pal['muted']).lighter(137)
            bottom=QColor(pal['raised'])
        elif material=='obsidian':
            top=QColor(pal['raised']).darker(130)
            bottom=QColor(pal['bg']).darker(180)
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
        bright = QColor(pal['accent'] if material != 'metal' else pal['text'])
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
            accent=QColor(pal['accent'])
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
        font.setStretch(round(100*390/self.width()))
        font.setWeight(QFont.DemiBold if is_front else QFont.Normal)
        painter.setFont(font)
        fg = QColor('#11202A' if material=='metal' and is_front else
                    '#F0F6F9' if material=='obsidian' and is_front else
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

    def _paint_header(self, painter, pal, heading, position):
        mode = self.options['header']
        if mode == 'hidden':
            return
        y = 270 if self.options['header_position'] == 'bottom' else 7
        font = QFont(painter.font())
        font.setPixelSize(13 if mode == 'full' else 12)
        font.setStretch(round(100*390/self.width()))
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        index = str(position) if self.options['show_index'] and mode != 'minimal' else ''
        if mode == 'full':
            badge = QRectF(18, y-2, 354 if index else 288, 32)
            painter.setPen(QPen(QColor(pal['border']), .8))
            painter.setBrush(QColor(pal['surface']))
            painter.drawRoundedRect(badge, 9, 9)
            painter.setPen(QColor(pal['accent']))
            painter.drawEllipse(QRectF(28, y+11, 5, 5))
            x, title_width = 43, 232
        else:
            # No heavyweight capsule around the category.
            x, title_width = 19, 267
        painter.setPen(QColor(pal['text']))
        label = QFontMetrics(font).elidedText(str(heading), Qt.ElideRight, title_width)
        painter.drawText(QRectF(x, y, title_width, 27), Qt.AlignVCenter | Qt.AlignLeft, label)
        if index:
            font.setPixelSize(11); font.setWeight(QFont.Normal)
            painter.setFont(font)
            painter.setPen(QColor(pal['muted']))
            painter.drawText(QRectF(300, y, 67, 27),
                             Qt.AlignVCenter | Qt.AlignRight, index)

    def _draw_ribbon(self, painter, pal, entries, cursor, static_mode):
        """Distinct horizontal card layout; same selection index and animation."""
        n = min(self.options['neighbors'], max(0, len(entries)-1))
        offset = (25 + self.options['neighbor_gap'] * .8)
        base = 0.0 if static_mode else cursor
        front = round(base)
        faces = []
        for unwrapped in range(front-n, front+n+1):
            rel = unwrapped-base
            if abs(rel) > n+.55:
                continue
            faces.append((rel, entries[unwrapped % len(entries)]))
        faces.sort(key=lambda item: -abs(item[0]))
        for relative, entry in faces:
            focus = abs(relative) < .52
            scale = max(.58, 1-.12*abs(relative))
            w = (220 if focus else 108)*scale
            h = (83 if focus else 65)*scale
            x = 195 + relative*offset - w/2
            y = 160 - h/2 + abs(relative)*3
            material=DRUM_STYLES[self.style_name]['material']
            if material=='glass':
                color=QColor(pal['accent']).darker(160 if focus else 240)
            elif material=='metal':
                color=QColor(pal['muted']).lighter(128 if focus else 104)
            elif material=='obsidian':
                color=QColor(pal['bg']).darker(175 if focus else 137)
            else:
                color=QColor(pal['raised'] if focus else pal['surface'])
            color.setAlpha(210 if material=='glass' else 245 if focus else 220)
            strength = 1.0 if focus else self.options['neighbor_opacity']/100.0
            painter.save()
            painter.setOpacity(painter.opacity()*strength)
            painter.setBrush(color)
            painter.setPen(QPen(QColor(pal['accent'] if focus else pal['border']),
                                1.8 if focus else .75))
            painter.drawRoundedRect(QRectF(x,y,w,h), 13 if focus else 9, 13 if focus else 9)
            if focus:
                marker=QColor(pal['accent'])
                painter.setBrush(marker);painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(QRectF(x+9,y+11,3,h-22),1.5,1.5)
            font=QFont(painter.font());font.setPixelSize(14 if focus else 11)
            font.setStretch(round(100*390/self.width()))
            font.setWeight(QFont.DemiBold if focus else QFont.Normal)
            painter.setFont(font)
            painter.setPen(QColor(pal['text'] if focus else pal['muted']))
            available=max(10,int(w-25))
            title=QFontMetrics(font).elidedText(self._preview(entry),Qt.ElideRight,available)
            painter.drawText(QRectF(x+15,y+3,w-25,h-6),
                             Qt.AlignLeft|Qt.AlignVCenter,title)
            painter.restore()

    def _paint_scene(self, painter, pal, heading, position, entries, cursor, static_mode):
        self._paint_header(painter, pal, heading, position)
        if not entries:
            return
        skin = DRUM_STYLES[self.style_name]
        if self.options['shape'] == 'ribbon':
            self._draw_ribbon(painter,pal,entries,cursor,static_mode)
            return
        halo = QRadialGradient(QPointF(195, 158), 172, QPointF(195, 158))
        glow = QColor(pal['bg'])
        glow.setAlpha(skin['halo'])
        halo.setColorAt(0, glow)
        glow.setAlpha(0)
        halo.setColorAt(1, glow)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(QRectF(5, 38, 380, 245))
        n = self.options['neighbors']
        # The ring angular spacing adapts to the selected number of neighbors.
        step = min(49.0, 76.0/(n+.53))
        half = step*.45
        if static_mode:
            faces = [face for face in visible_faces(
                0.0, count=1, extent=0, step_degrees=step,half_degrees=half)
                     if face['relative'] == 0]
        else:
            faces = [face for face in visible_faces(
                cursor, count=len(entries), extent=n+1,
                step_degrees=step, half_degrees=half)
                     if abs(face['relative']) <= n+.55]
        painter.save()
        factor=skin.get('width_scale',1.0)
        painter.translate(195,0)
        painter.scale(factor,1.0)
        painter.translate(-195,0)
        for face in faces:
            strength=(1.0 if abs(face['relative']) < .52 else
                      self.options['neighbor_opacity']/100.0)
            painter.save()
            painter.setOpacity(painter.opacity()*strength)
            if abs(face['relative']) > .1:
                painter.translate(math.sin(face['angle'])*self.options['neighbor_gap'],0)
            self._draw_face(painter, face, self._preview(entries[face['index']]), pal)
            painter.restore()
        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = self.app.palette
        painter.scale(self.width()/390.0,self.height()/302.0)
        overall = self.options['opacity']/100.0
        painter.setOpacity(overall)
        if self._category_frame is not None and self._category_progress < 1.0:
            progress = self._category_progress
            old_title, old_position, old_entries, old_cursor, old_static = self._category_frame
            # Adjacent category cylinders exchange positions with a soft lateral
            # displacement. No extra top-level windows, and rapid cycling remains safe.
            painter.save()
            painter.setOpacity(overall*(1.0 - progress))
            painter.translate(-26.0 * progress, 0)
            self._paint_scene(painter, pal, old_title, old_position,
                              old_entries, old_cursor, old_static)
            painter.restore()
            painter.save()
            painter.setOpacity(overall*progress)
            painter.translate(24.0 * (1.0 - progress), 0)
            self._paint_scene(painter, pal, self.heading, self.position,
                              self._entries, self._cursor, self._static_mode)
            painter.restore()
        else:
            self._paint_scene(painter, pal, self.heading, self.position,
                              self._entries, self._cursor, self._static_mode)
        painter.end()
