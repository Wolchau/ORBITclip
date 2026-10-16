"""Cross-platform ORBITclip selector with a real QComboBox model and a themed popup."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QListView, QStyledItemDelegate, QStyleFactory,
    QAbstractItemView,
)
from orbit_appearance import normalize_theme, palette


class _OptionDelegate(QStyledItemDelegate):
    """Force comfortable option height, including on Windows at 125–200% DPI."""
    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QSize(base.width(), max(38, base.height() + 12))


class OrbitSelect(QComboBox):
    """Non-native combo popup, retaining QComboBox's single authoritative model."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # QListWidget owns a *separate* model and produced empty popups in 7.5.
        # QListView binds to the QComboBox model through setView().
        self._fusion_style = QStyleFactory.create('Fusion')
        if self._fusion_style is not None:
            self.setStyle(self._fusion_style)
        view = QListView(self)
        view.setItemDelegate(_OptionDelegate(view))
        view.setSpacing(2)
        view.setUniformItemSizes(False)
        view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setView(view)
        self.setObjectName('orbit-select')
        self.setMinimumHeight(43)
        self.setMinimumWidth(145)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(17)
        app = QApplication.instance()
        self.set_theme(app.property('orbit_theme') if app is not None else 'midnight')

    def set_theme(self, theme):
        p = palette(normalize_theme(theme))
        self._arrow_color = QColor(p['muted'])
        self.setStyleSheet(f"""
            QComboBox#orbit-select {{
                color: {p['text']};
                background-color: {p['input']};
                border: 1px solid {p['border']};
                border-radius: 11px;
                padding: 8px 40px 8px 14px;
                selection-background-color: {p['hover']};
            }}
            QComboBox#orbit-select:hover {{ border-color: {p['muted']}; }}
            QComboBox#orbit-select:focus {{ border-color: {p['accent']}; }}
            QComboBox#orbit-select::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 35px;
                border: none;
                background: transparent;
            }}
            QComboBox#orbit-select::down-arrow {{
                image: none;
                width: 0px;
                height: 0px;
                border: none;
            }}
        """)
        self.view().setStyleSheet(f"""
            QListView {{
                background: {p['raised']};
                color: {p['text']};
                border: 1px solid {p['border']};
                border-radius: 9px;
                padding: 6px 4px;
                outline: 0;
                selection-background-color: {p['hover']};
            }}
            QListView::item {{
                min-height: 34px;
                padding: 5px 10px;
                color: {p['text']};
                background: transparent;
                border-radius: 6px;
            }}
            QListView::item:hover {{ background: {p['hover']}; }}
            QListView::item:selected {{
                color: {p['text']};
                background: {p['hover']};
            }}
        """)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        # The arrow is part of the same field, never a separately bordered block.
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self._arrow_color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x = self.width() - 22
        y = self.height() / 2
        from PySide6.QtCore import QPointF
        p.drawLine(QPointF(x - 5, y - 2), QPointF(x, y + 3))
        p.drawLine(QPointF(x, y + 3), QPointF(x + 5, y - 2))
        p.end()
