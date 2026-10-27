#!/usr/bin/env python3
"""ORBITclip Qt 7.4.1 — floating clock, clipboard vault, encrypted peer-to-peer relay chat.

UI: PySide6 / Qt. Protocol + private JSON formats remain compatible with ORBITclip v6.
Render does not store message bodies; both devices must be online.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import queue
import secrets
import sys
import threading
import time
import urllib.error
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize, QPoint, QRect, QEvent, QObject, QUrl, QStandardPaths
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QBrush, QCursor, QKeySequence, QDesktopServices, QTextLayout, QTextOption, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QToolButton, QLineEdit, QScrollArea, QPlainTextEdit, QComboBox, QDialog, QMenu,
    QInputDialog, QMessageBox, QFileDialog, QFormLayout, QSpinBox, QSlider, QCheckBox,
    QSizePolicy, QStackedWidget, QGraphicsDropShadowEffect, QListWidget, QListWidgetItem, QAbstractItemView, QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView, QSystemTrayIcon
)

from kinetic_clipboard import ClipboardVault, LABELS, ACCENTS, private_write
from kinetic_remote import (
    RemoteBridge, MessageStore, encrypt_message, decrypt_message, make_pair_code,
    validate_config, http_json, MAX_FILE_SIZE
)
from kinetic_pairing import PairingBridge
from kinetic_hotkeys import Hotkeys
from orbit_switcher import ClipboardWheel
from orbit_tls import public_urlopen
from orbit_version import CLIENT_VERSION
from orbit_categories import CategoryModel, WheelQueue, ICONS, category_click_handler
from orbit_peers import DeviceIdentity, PeerDirectory
from orbit_ui_logic import next_nonempty_category, parse_table_preview, safe_web_url
from orbit_attachments import save_attachment
from orbit_file_transfer import FileSender, FileReceiver, LEGACY_FILE_SIZE
from orbit_delivery import DurableOutbox
from orbit_client_defaults import resolve_connection_settings
from orbit_smart import smart_actions, action_catalog
from orbit_extract_ui import ExtractDialog
from orbit_semantic import find as semantic_find
from orbit_history_view import history_matches, visible_page, PAGE_SIZE
from orbit_context import foreground_app
from orbit_workspaces import Workspaces
from orbit_workspace_ui import WorkspaceWindow
from orbit_appearance import THEMES, palette, stylesheet, normalize_theme
from orbit_notifications import NotificationStore
from orbit_analytics import AnalyticsStore
from orbit_activity_ui import NotificationCenterWindow, AnalyticsWindow
from orbit_drum import DrumBubble
from orbit_drum_styles import DRUM_STYLES, normalize_drum_style
from orbit_drum_layout import (DEFAULTS as DRUM_DEFAULTS, normalize_options as normalize_drum_options,
                               SHAPES, POSITIONS, HEADERS, HEADER_POSITIONS)
from orbit_select import OrbitSelect
from orbit_flow import PasteQueue, QueuePresets, normalize_exclusions, is_excluded
from orbit_queue_ui import PasteQueueWindow
from orbit_global_shortcuts import FlowShortcuts
from orbit_palette import CommandPalette
from orbit_drum_preview import DrumLivePreview
from orbit_update_ui import UpdateWindow
from orbit_update import consume_status, log_update, read_history
from orbit_messenger_ui import FileReviewDialog, validate_dropped_files

APP_NAME = 'ORBITclip'
QT_CLIENT_VERSION = CLIENT_VERSION
DEFAULT_RELAY_URL = 'https://kinetic-relay.onrender.com'
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'assets'
SETTINGS_FILE = Path.home() / '.chronochip_settings.json'
COLORS = {
    'bg':'#101923', 'surface':'#17232E','raised':'#202E3B','hover':'#293B49',
    'border':'#31424F','text':'#EAF1F5','muted':'#93A4B2','faint':'#718391',
    'peach':'#F7AA90','mint':'#72D6BE','blue':'#75BAFF','purple':'#C6A8F1',
    'danger':'#E68F8C','input':'#1C2A35'
}
STYLE = '''
QWidget { background-color:#101923; color:#EAF1F5; font-family:"Inter","SF Pro Text","Segoe UI",Arial; font-size:12px; }
QLabel {background:transparent;}
QFrame#shell { background-color:#17232E; border:1px solid #334552; border-radius:18px; }
QFrame#card { background-color:#1D2B37; border:1px solid #304451; border-radius:13px; }
QFrame#side { background-color:#14212C; border:0; border-radius:14px; }
QLabel#heading { font-size:19px; font-weight:700; color:#F2F5F7; }
QLabel#muted { color:#92A3B2; font-size:11px; }
QLabel#subhead { color:#B9C9D4; font-size:11px; font-weight:700; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background:#1C2A35; color:#ECF4F6; border:1px solid #354957; border-radius:10px; padding:9px; selection-background-color:#4E7781; }
QLineEdit:focus, QPlainTextEdit:focus { border-color:#E7A28E; }
QPushButton { background:#263644; color:#EAF1F5; border:1px solid #3A4E5C; border-radius:10px; padding:8px 12px; font-weight:600; }
QPushButton:hover { background:#344857; border-color:#607482; }
QPushButton:pressed { background:#3C5363; }
QPushButton#primary { background:#F7AA90; border:0; color:#1A2730; font-weight:700; }
QPushButton#primary:hover { background:#FFC2AC; }
QPushButton#nav { background:transparent; border:0; border-radius:9px; padding:9px; text-align:left; color:#A7B8C3; font-weight:500; }
QPushButton#nav:hover { background:#273847; color:#F3F6F9; }
QPushButton#nav[chosen="true"] { background:#33414D; color:#FFB49B; font-weight:700; }
QToolButton { background:transparent; border:none; border-radius:9px; color:#BBCBD3; padding:5px; }
QToolButton:hover { background:#384C58; color:#F5F7F9; }
QToolButton#marked { color:#F6B08E; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { background:transparent; width:8px; margin:7px 0; }
QScrollBar::handle:vertical { background:#526677; min-height:32px; border-radius:4px; }
QScrollBar::handle:vertical:hover { background:#F7AA90; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { height:0px; }
QMenu { background:#1C2B38; color:#F3F5F6; border:1px solid #405565; padding:6px; border-radius:11px; }
QMenu::item { padding:8px 14px; border-radius:7px; }
QMenu::item:selected { background:#344957; }
QCheckBox { color:#BCCBD3; spacing:7px; }
QCheckBox::indicator { width:17px; height:17px; }
'''


def icon(name: str) -> QIcon:
    location = ASSETS / 'icons' / f'{name}.svg'
    return QIcon(str(location)) if location.exists() else QIcon()


def tool(name: str, tooltip: str, callback, size=18) -> QToolButton:
    b=QToolButton()
    b.setIcon(icon(name))
    b.setIconSize(QSize(size,size))
    b.setFixedSize(29,29)
    b.setToolTip(tooltip)
    b.clicked.connect(callback)
    return b


def label(text, color='muted', size=None) -> QLabel:
    w=QLabel(str(text))
    w.setObjectName('muted' if color=='muted' else 'subhead')
    if size:
        font=w.font();font.setPointSize(size);w.setFont(font)
    return w


def action(text, cb=None, primary=False, icon_name=None) -> QPushButton:
    b=QPushButton(text)
    if primary:b.setObjectName('primary')
    if icon_name:b.setIcon(icon(icon_name));b.setIconSize(QSize(16,16))
    if cb:b.clicked.connect(cb)
    return b


def read_settings():
    try:
        value=json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError,UnicodeError):return {}


def tooltip_time(ts):
    try:return datetime.fromtimestamp(float(ts)).strftime('%d.%m  %H:%M')
    except (ValueError,OverflowError,TypeError):return ''


def truncate(s, n=140):
    s=' '.join(str(s).split())
    return s[:n-1]+'…' if len(s)>n else s


def error(parent, text):
    QMessageBox.warning(parent, 'ORBITclip', str(text))


class OrbitPill(QWidget):
    """Always-on-top minimal clock with anchored hover expansion and edge snapping."""
    def __init__(self, app):
        super().__init__(None)
        self.app=app
        # Native macOS window: Qt.Tool panels often disappear when the app loses focus.
        # Qt.Window stays independent and non-modal, while the top-most hint keeps
        # the clock visible above other applications.
        if platform.system()=='Darwin':
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        else:
            self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.compact_w=166;self.expanded_w=282;self.h=47
        self.is_expanded=False
        self.expand_left=False
        self._drag_start=None
        self._moved=False
        self._x=int(app.settings.get('x',0))
        self._y=int(app.settings.get('y',0))
        geo=QApplication.primaryScreen().availableGeometry()
        if not self._x:self._x=geo.right()-self.compact_w-18
        if not self._y:self._y=geo.top()+38
        self.setGeometry(self._x,self._y,self.compact_w,self.h)
        self.history_btn=tool('clipboard','Открыть историю',app.open_history)
        self.chat_btn=tool('send','Переписка и передача',app.open_chat)
        self.online_btn=tool('remote','Устройства онлайн',app.open_online)
        for b in (self.history_btn,self.chat_btn,self.online_btn):
            b.setParent(self); b.hide()
            b.setStyleSheet('QToolButton{background:#283B49;border-radius:8px;padding:4px;} QToolButton:hover{background:#425768;}')
        self._flash_until=0.0
        self._draw_timer=QTimer(self); self._draw_timer.timeout.connect(self.update)
        self._draw_timer.start(200)
        self._collapse_timer=QTimer(self);self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self.collapse)

    def paintEvent(self, ev):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        rect=self.rect().adjusted(1,1,-2,-2)
        p.setPen(QPen(QColor(self.app.palette['border']),1))
        p.setBrush(QColor(self.app.palette['surface']))
        p.drawRoundedRect(rect,16,16)
        today=datetime.now()
        dx=self.expanded_w-self.compact_w if self.is_expanded and self.expand_left else 0
        p.save();p.translate(dx,0)
        p.setPen(QColor(self.app.palette['muted'] if self.app.offline else self.app.palette['accent']));p.setBrush(QColor(self.app.palette['muted'] if self.app.offline else self.app.palette['accent']))
        p.drawEllipse(13,19,7,7)
        f=QFont('Arial',18,QFont.DemiBold)
        p.setFont(f);p.setPen(QColor(self.app.palette['text']))
        p.drawText(QRect(29,7,102,30),Qt.AlignVCenter|Qt.AlignLeft,today.strftime('%H:%M'))
        p.setFont(QFont('Arial',8,QFont.Medium));p.setPen(QColor('#93A9B7'))
        p.drawText(QRect(120,11,37,15), Qt.AlignRight|Qt.AlignVCenter,today.strftime('%d.%m'))
        p.setPen(Qt.NoPen);p.setBrush(QColor('#344450'))
        p.drawRoundedRect(QRect(30,39,120,2),1,1)
        p.setBrush(QColor(self.app.palette['accent']));p.drawRoundedRect(QRect(30,39,max(3,int(120*today.second/60)),2),1,1)
        p.restore()
        if time.monotonic()<self._flash_until:
            p.setPen(QPen(QColor('#78E1C6'),2));p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(1,1,-1,-1),15,15)
        if self.is_expanded:
            p.setPen(QPen(QColor('#354957'),1));p.drawLine(163 if not self.expand_left else 119,11,163 if not self.expand_left else 119,36)

    def expand(self):
        self._collapse_timer.stop()
        if self.is_expanded:return
        self.is_expanded=True
        screen=QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        mid=screen.availableGeometry().center().x()
        self.expand_left=self.x()+self.compact_w/2>mid
        if self.expand_left:
            self._x=self.x(); self.setGeometry(self._x-(self.expanded_w-self.compact_w),self.y(),self.expanded_w,self.h)
        else:self.resize(self.expanded_w,self.h)
        self.history_btn.setGeometry(9 if self.expand_left else 176,9,29,29)
        self.chat_btn.setGeometry(43 if self.expand_left else 210,9,29,29)
        self.online_btn.setGeometry(77 if self.expand_left else 244,9,29,29)
        self.history_btn.show();self.chat_btn.show();self.online_btn.show()
        self.update()

    def collapse(self):
        if not self.is_expanded or self.underMouse():return
        self.history_btn.hide();self.chat_btn.hide();self.online_btn.hide()
        if self.expand_left:
            self.setGeometry(self.x()+self.expanded_w-self.compact_w,self.y(),self.compact_w,self.h)
        else:self.resize(self.compact_w,self.h)
        self.is_expanded=False
        self.update()

    def enterEvent(self,e):self.expand();super().enterEvent(e)
    def leaveEvent(self,e):self._collapse_timer.start(430);super().leaveEvent(e)
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton:
            self._drag_start=e.globalPosition().toPoint()-self.pos();self._moved=False
        elif e.button()==Qt.RightButton:
            menu=QMenu(self)
            menu.addAction('История буфера',self.app.open_history)
            menu.addAction('⌕ Быстрый поиск и команды…',self.app.open_palette)
            menu.addAction('Вставить следующий из очереди',self.app.paste_next_from_queue)
            menu.addAction('Редактор очереди вставки…',self.app.open_queue)
            menu.addAction('Связь и переписка',self.app.open_chat)
            menu.addAction('Устройства онлайн…',self.app.open_online)
            menu.addAction('Общие пространства…',self.app.open_workspaces)
            menu.addAction('SQL Explorer · база и ER-схема…',self.app.open_sql_explorer)
            menu.addAction('Уведомления…',self.app.open_notification_center)
            menu.addAction('Моя аналитика…',self.app.open_analytics)
            menu.addAction('Настройки…',self.app.open_settings)
            menu.addAction('Настроить прокрутку',self.app.edit_scroll_settings)
            menu.addAction('Диагностика Ctrl + колесо',self.app.wheel_diagnostics)
            menu.addAction('Перезапустить перехват',self.app.restart_wheel)
            if platform.system()=='Darwin':
                menu.addAction('Права глобального ввода macOS…',self.app.open_mac_input_permissions)
            menu.addSeparator()
            menu.addAction('Завершить ORBITclip',self.app.shutdown)
            menu.exec(e.globalPosition().toPoint())

    def mouseMoveEvent(self,e):
        if self._drag_start is not None:
            diff=e.globalPosition().toPoint()-self._drag_start
            self.move(diff);self._moved=True
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self,e):
        if self._drag_start is not None:
            if self._moved:
                screen=QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
                avail=screen.availableGeometry();x,y=self.x(),self.y();w=self.width();h=self.height()
                if abs(x-avail.left())<=28:x=avail.left()
                if abs((x+w)-avail.right())<=28:x=avail.right()-w+1
                if abs(y-avail.top())<=28:y=avail.top()
                if abs((y+h)-avail.bottom())<=28:y=avail.bottom()-h+1
                self.move(x,y)
                base_x=x+(self.expanded_w-self.compact_w if self.is_expanded and self.expand_left else 0)
                self.app.settings.update(x=base_x,y=y);self.app.save_settings()
            self._drag_start=None
        super().mouseReleaseEvent(e)

    def flash(self):self._flash_until=time.monotonic()+.7;self.update()


class FloatingToast(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.ToolTip|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        row=QHBoxLayout(self);row.setContentsMargins(10,8,10,8)
        frame=QFrame();frame.setObjectName('shell');row.addWidget(frame)
        inner=QHBoxLayout(frame);inner.setContentsMargins(15,10,15,10)
        self.mark=QLabel('●');self.mark.setStyleSheet('color:#78D7BE;font-size:13px')
        inner.addWidget(self.mark)
        self.title=QLabel();self.title.setMaximumWidth(270);self.title.setWordWrap(True);inner.addWidget(self.title)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.hide)

    def pop(self, text):
        self.title.setText(truncate(text,125))
        self.adjustSize()
        geom=QApplication.primaryScreen().availableGeometry()
        self.move(geom.right()-self.width()-24,geom.top()+76)
        self.show();self.raise_();self.timer.start(3300)


class ScrollBubble(QWidget):
    def __init__(self):
        super().__init__(None)
        # Tool + MacAlwaysShowToolWindow stays visible while another app has focus.
        self.setWindowFlags(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating,True)
        if platform.system()=='Darwin':
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow,True)
        lay=QVBoxLayout(self);lay.setContentsMargins(4,4,4,4)
        wrap=QFrame();wrap.setObjectName('shell');wrap.setMinimumWidth(280)
        inside=QVBoxLayout(wrap);inside.setContentsMargins(13,9,13,11);inside.setSpacing(4)
        self.head=QLabel();self.head.setStyleSheet('color:#F6AB92;font-size:10px;font-weight:700')
        self.title=QLabel();self.title.setStyleSheet('color:#8D9BA6;font-size:10px')
        self.preview=QLabel()
        self.preview.setWordWrap(True)
        self.preview.setFixedWidth(314)
        self.preview.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.preview.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.preview.setFixedHeight(self.preview.fontMetrics().lineSpacing()*2+5)
        inside.addWidget(self.head);inside.addWidget(self.title);inside.addWidget(self.preview)
        lay.addWidget(wrap)

    def show_item(self, item, cat_label, index, total):
        self.head.setText(f'{cat_label.upper()}    {index+1} / {total}')
        self.title.setText(item.get('title') or item.get('category') or '')
        self.title.setVisible(bool(self.title.text()))
        self.preview.setText(self.two_line_preview(item.get('text') or 'Защищённая запись'))
        self.adjustSize()
        pos=QCursor.pos()
        screen=QApplication.screenAt(pos) or QApplication.primaryScreen()
        avail=screen.availableGeometry()
        self.move(max(avail.left()+8,min(pos.x()+19,avail.right()-self.width()-8)),
                  max(avail.top()+8,min(pos.y()-self.height()-15,avail.bottom()-self.height()-8)))
        self.show()

    def two_line_preview(self,text):
        """Wrap to two visual lines by font metrics instead of raw character count."""
        plain=' '.join(str(text).split())
        layout=QTextLayout(plain,self.preview.font())
        option=QTextOption();option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout();lines=[]
        for _ in range(3):
            line=layout.createLine()
            if not line.isValid():break
            line.setLineWidth(self.preview.width()-4)
            lines.append(plain[line.textStart():line.textStart()+line.textLength()].strip())
        layout.endLayout()
        if len(lines)>2:
            lines=lines[:2]
            lines[-1]=self.preview.fontMetrics().elidedText(lines[-1]+'…',Qt.ElideRight,self.preview.width()-6)
        return '\n'.join(lines)

    def show_empty(self, cat_label):
        self.head.setText(str(cat_label).upper())
        self.title.hide()
        self.preview.setText('В этой категории пока нет записей')
        self.adjustSize()
        pos=QCursor.pos()
        screen=QApplication.screenAt(pos) or QApplication.primaryScreen()
        avail=screen.availableGeometry()
        self.move(max(avail.left()+8,min(pos.x()+19,avail.right()-self.width()-8)),
                  max(avail.top()+8,min(pos.y()-self.height()-15,avail.bottom()-self.height()-8)))
        self.show()


class CategoryEditor(QDialog):
    """Rename, icon-change, hide from wheel, add/delete user categories."""
    def __init__(self,app,parent=None):
        super().__init__(parent);self.app=app
        self.setWindowTitle('Категории ORBITclip');self.resize(550,455)
        l=QVBoxLayout(self);l.addWidget(label('Категории для библиотеки · галочка управляет кольцевой прокруткой'))
        self.list=QListWidget();l.addWidget(self.list,1)
        actions=QHBoxLayout();l.addLayout(actions)
        for caption,callback in [('Добавить',self.add),('Изменить',self.edit),('Удалить',self.delete),('Вернуть стандартные',self.restore)]:
            actions.addWidget(action(caption,callback))
        actions.addStretch()
        l.addWidget(label('Удалённые стандартные категории можно восстановить. Записи не удаляются.'))
        close=action('Готово',self.accept,primary=True);l.addWidget(close)
        self.refresh()

    def refresh(self):
        selected=self.current_id();self.list.clear()
        for c in self.app.categories.visible_categories():
            mark='◉' if c['wheel'] else '○'
            item=QListWidgetItem(f"{mark}  {c['name']}    ·   {c['icon']}")
            item.setData(Qt.UserRole,c['id']);item.setIcon(icon(c['icon']))
            self.list.addItem(item)
            if c['id']==selected:self.list.setCurrentItem(item)
    def current_id(self):
        i=self.list.currentItem()
        return i.data(Qt.UserRole) if i else None
    def details(self,c=None):
        dialog=QDialog(self);dialog.setWindowTitle('Категория');dialog.resize(400,235)
        l=QVBoxLayout(dialog);l.addWidget(label('Имя категории'))
        name=QLineEdit(c['name'] if c else '');l.addWidget(name)
        l.addWidget(label('Векторная иконка'))
        icons=OrbitSelect()
        for entry in ICONS:icons.addItem(icon(entry),entry,entry)
        if c:icons.setCurrentIndex(max(0,icons.findData(c['icon'])))
        l.addWidget(icons)
        wheel=QCheckBox('Показывать в Ctrl + Alt · кольцо категорий');wheel.setChecked(c['wheel'] if c else True)
        l.addWidget(wheel)
        bar=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        bar.accepted.connect(dialog.accept);bar.rejected.connect(dialog.reject);l.addWidget(bar)
        if dialog.exec()!=QDialog.Accepted:return None
        return name.text(),icons.currentData(),wheel.isChecked()
    def add(self):
        d=self.details()
        if d:
            try:self.app.categories.add(*d);self.app.persist_categories();self.refresh()
            except ValueError as e:error(self,e)
    def edit(self):
        c=self.app.categories.get(self.current_id())
        if not c:return
        d=self.details(c)
        if d:
            try:self.app.categories.edit(c['id'],*d);self.app.persist_categories();self.refresh()
            except ValueError as e:error(self,e)
    def delete(self):
        c=self.app.categories.get(self.current_id())
        if not c:return
        if QMessageBox.question(self,'Категории','Убрать категорию? Записи останутся в общей истории.')!=QMessageBox.Yes:return
        if not c['system']:
            for item in self.app.vault.items:
                if item.get('category')==c['id']:item['category']=''
            self.app.vault.save()
        try:self.app.categories.delete(c['id'])
        except ValueError as e:return error(self,e)
        self.app.persist_categories();self.refresh()
    def restore(self):
        self.app.categories.restore_builtin();self.app.persist_categories();self.refresh()


class WheelEditor(QDialog):
    """Drag & drop the exact visible Ctrl+Wheel candidate list."""
    def __init__(self,app,parent=None):
        super().__init__(parent);self.app=app;self.setWindowTitle('Очередь Ctrl + колесо')
        self.resize(610,625)
        layout=QVBoxLayout(self)
        layout.addWidget(label('Перетаскивай записи мышью. Порядок сохраняется для обычной прокрутки.'))
        head=QHBoxLayout();layout.addLayout(head)
        head.addWidget(label('Категория'))
        self.cat=OrbitSelect()
        for c in app.categories.wheel_categories():self.cat.addItem(icon(c['icon']),c['name'],c['id'])
        self.cat.currentIndexChanged.connect(self.rebuild);head.addWidget(self.cat,1)
        head.addWidget(label('Лимит'))
        self.limit=QSpinBox();self.limit.setRange(1,100);self.limit.setValue(app.wheel_limit)
        self.limit.valueChanged.connect(self.rebuild);head.addWidget(self.limit)
        layout.addWidget(label('Первые строки можно закрепить кнопкой «Зафиксировать порядок». Новые копирования заполняют свободные места.'))
        self.list=QListWidget();self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction);self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.list,1)
        footer=QHBoxLayout();layout.addLayout(footer)
        footer.addWidget(action('Зафиксировать порядок',self.save_order,primary=True))
        footer.addWidget(action('Сбросить очередь',self.reset_order))
        footer.addStretch();footer.addWidget(action('Закрыть',self.accept))
        self.rebuild()
    def rebuild(self,*args):
        self.list.clear();category=self.cat.currentData() or 'all'
        q=WheelQueue(self.app.wheel_queue.manual_map,self.limit.value())
        entries=q.candidates(self.app.vault.items,self.app.categories,category)
        for rank,item in enumerate(entries,1):
            cat=self.app.categories.get(item.get('category',''))
            cap=item.get('title') or (cat['name'] if cat else LABELS.get(item.get('kind'),('','Текст'))[1])
            preview='🔒 защищённая запись' if item.get('encrypted') else truncate(item.get('text',''),72)
            line=QListWidgetItem(f'{rank:02d}   {cap}   ·   {preview}')
            line.setData(Qt.UserRole,item['id']);line.setIcon(icon(item.get('kind','text')))
            self.list.addItem(line)
    def save_order(self):
        ordered=[self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]
        self.app.wheel_limit=self.limit.value();self.app.wheel_queue.limit=self.limit.value()
        self.app.wheel_queue.move_front(ordered,self.app.vault.items,self.app.categories,self.cat.currentData() or 'all')
        self.app.save_settings();self.rebuild()
    def reset_order(self):
        self.app.wheel_queue.reset(self.cat.currentData() or 'all');self.app.save_settings();self.rebuild()


class VaultRow(QFrame):
    def __init__(self, window, item):
        super().__init__()
        self.window=window;self.item=item;self.item_id=item['id']
        self.setObjectName('card')
        preview_data=(parse_table_preview(item.get('text','')) if item.get('kind')=='table' and not item.get('encrypted') else None)
        self.setFixedHeight((62+26+max(1,len(preview_data[1]))*24+(23 if preview_data[2] else 0)) if preview_data else 60)
        outer=QVBoxLayout(self);outer.setContentsMargins(9,5,7,5);outer.setSpacing(5)
        header=QWidget();header.setStyleSheet('background: transparent')
        lay=QHBoxLayout(header);lay.setContentsMargins(0,0,0,0);lay.setSpacing(5)
        outer.addWidget(header)
        kind=item.get('kind','text')
        picture=QLabel();picture.setPixmap(icon(kind if kind!='sql' else 'sql').pixmap(23,23))
        picture.setFixedWidth(29)
        lay.addWidget(picture)
        middle=QVBoxLayout();middle.setSpacing(2)
        title=item.get('title') or item.get('category') or LABELS.get(kind,('','Текст'))[1]
        top=QLabel(truncate(title,48));top.setStyleSheet('font-size:11px;font-weight:700;color:#DDECF3')
        line=QLabel('••••••••  Защищённая запись' if item.get('encrypted') else truncate(item.get('text',''),100))
        line.setObjectName('muted');line.setStyleSheet('color:#95A8B7;font-size:11px')
        middle.addWidget(top);middle.addWidget(line)
        lay.addLayout(middle,1)
        self.setMinimumWidth(0)
        top.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        line.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        age=label(tooltip_time(item.get('ts',0)));age.setFixedWidth(73);lay.addWidget(age)
        star=tool('favorite','Убрать из избранного' if item.get('pinned') else 'В избранное',lambda:window.toggle_favorite(self.item_id))
        if item.get('pinned'):star.setObjectName('marked');star.setStyleSheet('QToolButton{background:#614A48;border-radius:9px;}')
        lay.addWidget(star)
        lay.addWidget(tool('close','Удалить запись',lambda:window.remove_item(self.item_id)))
        if kind=='link' and safe_web_url(item.get('text','')):
            go=tool('link','Открыть ссылку в браузере',self.open_link)
            lay.addWidget(go)
        lay.addWidget(tool('eye','Открыть подробный просмотр',lambda:window.preview_item(self.item_id)))
        lay.addWidget(tool('settings','Действия с записью',self.menu))
        if preview_data:
            names,rows,remaining=preview_data
            grid=QTableWidget(len(rows),len(names),self)
            grid.setObjectName('previewTable')
            grid.setHorizontalHeaderLabels(names)
            grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
            grid.setSelectionMode(QAbstractItemView.NoSelection)
            grid.setFocusPolicy(Qt.NoFocus)
            grid.setAlternatingRowColors(True)
            grid.verticalHeader().hide()
            grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            grid.horizontalHeader().setMinimumSectionSize(45)
            grid.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            grid.setStyleSheet('QTableWidget{background:#162530;alternate-background-color:#213440;'
                'gridline-color:#334654;border:1px solid #334654;border-radius:8px;color:#DFE8EC;font-size:11px}'
                'QHeaderView::section{background:#2B4150;color:#B6CCD8;border:0;'
                'border-right:1px solid #405362;padding:3px;font-weight:600}')
            grid.horizontalHeader().setFixedHeight(25)
            grid.verticalHeader().setDefaultSectionSize(24)
            for ri,row in enumerate(rows):
                for ci,cell in enumerate(row):
                    cell_widget=QTableWidgetItem(cell)
                    cell_widget.setToolTip(cell)
                    grid.setItem(ri,ci,cell_widget)
            grid.setFixedHeight(26+max(1,len(rows))*24+3)
            outer.addWidget(grid)
            if remaining:
                extra=label(f'Ещё строк: {remaining}')
                outer.addWidget(extra)
            outer.addStretch(1)

    def open_link(self):
        url=safe_web_url(self.item.get('text',''))
        if not url:return error(self.window,'Недопустимая ссылка')
        if not QDesktopServices.openUrl(QUrl(url)):
            error(self.window,'Не удалось открыть ссылку в браузере')

    def mouseDoubleClickEvent(self,e):
        if e.button()==Qt.LeftButton:self.window.copy_item(self.item_id)

    def menu(self):
        """Actions only: permanent star/delete/open buttons must not be duplicated."""
        item=self.window.app.vault.find(self.item_id)
        if not item:return
        m=QMenu(self)
        def add(name,caption,callback,root=None):
            host=root if root is not None else m
            host.addAction(icon(name),caption,callback)
        add('copy','Копировать',lambda:self.window.copy_item(self.item_id))
        if not item.get('encrypted'):
            add('history','Добавить в очередь вставки',lambda:self.window.app.enqueue_item(self.item_id))
        add('remote','Отправить устройству…',lambda:self.window.app.send_clip_item(self.item_id))
        if not item.get('encrypted'):
            add('code','Извлечь данные…',lambda:self.window.extract_item(self.item_id))
            add('code','Умные действия…',lambda:self.window.smart_item(self.item_id))
            add('remote','Опубликовать в пространстве…',lambda:self.window.publish_item(self.item_id))
        m.addSeparator()
        add('text','Название и категория…',lambda:self.window.rename_item(self.item_id))
        scroll=m.addMenu(icon('history'),'Кольцевая прокрутка')
        add('priority','Убрать приоритет' if item.get('scroll_priority') else 'Закрепить первым',
            lambda:self.window.toggle_priority(self.item_id),scroll)
        add('eye-off' if item.get('scroll_enabled',True) else 'eye',
            'Исключить из прокрутки' if item.get('scroll_enabled',True) else 'Вернуть в прокрутку',
            lambda:self.window.toggle_scroll(self.item_id),scroll)
        if item.get('pinned'):
            add('hotkey','Горячая клавиша…',lambda:self.window.bind_item(self.item_id),scroll)
        if not item.get('encrypted'):
            add('eye-off','Зашифровать запись…',lambda:self.window.encrypt_item(self.item_id))
        else:
            add('eye','Расшифровать и скопировать…',lambda:self.window.copy_item(self.item_id))
        m.exec(QCursor.pos())


class VaultWindow(QWidget):
    def __init__(self, app):
        super().__init__(None)
        self.setWindowFlag(Qt.Window, True)  # Independent window: never auto-dismiss on focus loss.
        self.app=app;self.category='all';self.space_mode='personal';self.source_app=''
        self.setWindowTitle('ORBITclip · Библиотека · v'+CLIENT_VERSION)
        self.setWindowIcon(QIcon(str(ASSETS/'orbit_icon.png')))
        self.resize(1060,640)
        self.setMinimumWidth(720)
        self._view_signature=None
        self.render_limit=PAGE_SIZE
        self.search_timer=QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.refresh)
        self.build()

    def build(self):
        self.setObjectName('shell')
        base=QHBoxLayout(self);base.setContentsMargins(12,12,12,12);base.setSpacing(12)
        sidebar=QFrame();sidebar.setObjectName('side');sidebar.setFixedWidth(175)
        left=QVBoxLayout(sidebar);left.setContentsMargins(9,14,9,10);left.setSpacing(5)
        brand=QLabel('◉  ORBITclip');brand.setToolTip('Версия '+CLIENT_VERSION);brand.setStyleSheet('font-size:15px;font-weight:700;color:#F7B398;padding:5px 6px 17px')
        left.addWidget(brand)
        self.nav={}
        self.nav_container=QWidget()
        self.nav_layout=QVBoxLayout(self.nav_container)
        self.nav_layout.setContentsMargins(0,0,0,0);self.nav_layout.setSpacing(3)
        nav_scroller=QScrollArea();nav_scroller.setWidgetResizable(True)
        nav_scroller.setWidget(self.nav_container)
        left.addWidget(nav_scroller,1)
        self.rebuild_nav()
        base.addWidget(sidebar)

        main=QVBoxLayout();main.setContentsMargins(2,6,2,4);main.setSpacing(10)
        top=QHBoxLayout()
        title=QLabel('Библиотека фрагментов');title.setObjectName('heading')
        top.addWidget(title);top.addStretch()
        top.addWidget(action('Очередь…',self.app.open_queue))
        top.addWidget(action('Пространства…',self.app.open_workspaces,icon_name='remote'))
        self.more_button=tool('settings','Дополнительные инструменты и настройки (категории, прокрутка…) ',self.open_tools_menu,20)
        self.more_button.setFixedSize(34,34)
        top.addWidget(self.more_button)
        main.addLayout(top)
        space_tabs=QHBoxLayout()
        self.personal_tab=action('Личное',lambda:self.set_space_mode('personal'))
        self.apps_tab=action('По приложениям',lambda:self.set_space_mode('apps'))
        self.shared_tab=action('Общие пространства',lambda:self.set_space_mode('shared'))
        space_tabs.addWidget(self.personal_tab)
        space_tabs.addWidget(self.apps_tab)
        space_tabs.addWidget(self.shared_tab)
        space_tabs.addStretch(1)
        main.addLayout(space_tabs)
        # Shared workspaces are visible pills, not an old-style combo box.
        self.workspace_strip=QScrollArea()
        self.workspace_strip.setWidgetResizable(True)
        self.workspace_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.workspace_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.workspace_strip.setFixedHeight(49)
        self.workspace_strip.setStyleSheet('QScrollArea QScrollBar:horizontal{height:6px;}')
        self.workspace_buttons_host=QWidget()
        self.workspace_buttons=QHBoxLayout(self.workspace_buttons_host)
        self.workspace_buttons.setContentsMargins(1,3,1,3)
        self.workspace_buttons.setSpacing(6)
        self.workspace_strip.setWidget(self.workspace_buttons_host)
        self.selected_workspace=None
        self._workspace_signature=None
        main.addWidget(self.workspace_strip)
        self.app_strip=QScrollArea();self.app_strip.setWidgetResizable(True)
        self.app_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.app_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.app_strip.setFixedHeight(45)
        self.app_buttons_host=QWidget()
        self.app_buttons=QHBoxLayout(self.app_buttons_host)
        self.app_buttons.setContentsMargins(1,3,1,3)
        self.app_buttons.setSpacing(5)
        self.app_strip.setWidget(self.app_buttons_host)
        self.app_buttons_signature=None
        main.addWidget(self.app_strip)
        search_controls=QHBoxLayout()
        self.search=QLineEdit()
        self.search.setPlaceholderText('⌕  Найти по словам или смысловым подсказкам')
        self.search.textChanged.connect(self.on_search_changed)
        search_controls.addWidget(self.search,1)
        self.semantic_mode=QCheckBox('По смыслу · эксперимент')
        self.semantic_mode.setToolTip('Локальный словарь русских и английских понятий. '
                                      'Это предварительная версия, без нейросети и внешних сервисов.')
        self.semantic_mode.toggled.connect(self.refresh)
        search_controls.addWidget(self.semantic_mode)
        self.period_combo=QComboBox()
        for title,value in [('За всё время','all'),('Сегодня','today'),
                            ('7 дней','week'),('30 дней','month')]:
            self.period_combo.addItem(title,value)
        self.period_combo.setToolTip('Показывать записи за выбранный период')
        self.period_combo.currentIndexChanged.connect(self.refresh)
        search_controls.addWidget(self.period_combo)
        main.addLayout(search_controls)
        self.counter=label('');main.addWidget(self.counter)
        hint=label('Двойной клик — копировать  ·  глаз — полный предпросмотр  ·  ★ — избранное')
        main.addWidget(hint)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True)
        self.contents=QWidget();self.contents.setMinimumWidth(0);self.rows=QVBoxLayout(self.contents)
        self.rows.setContentsMargins(1,1,5,2);self.rows.setSpacing(5)
        self.scroll.setWidget(self.contents);main.addWidget(self.scroll,1)
        foot=QHBoxLayout();foot.addWidget(label('Двойной клик — копировать · ⚙ — дополнительные действия'));foot.addStretch();foot.addWidget(label('v'+CLIENT_VERSION))
        main.addLayout(foot)
        base.addLayout(main,1)
        self.refresh()

    def open_tools_menu(self):
        menu=QMenu(self)
        def add(section, icon_name, name, callback):
            section.addAction(icon(icon_name),name,callback)
        add(menu,'settings','Управление категориями…',self.edit_categories)
        add(menu,'history','Порядок Ctrl + колесо…',self.app.edit_scroll_settings)
        add(menu,'clipboard','Редактор очереди вставки…',self.app.open_queue)
        add(menu,'clipboard','Коллекции по приложениям…',self.choose_source_app)
        menu.addSeparator()
        add(menu,'remote','Управление пространствами…',self.app.open_workspaces)
        add(menu,'remote','Мессенджер…',self.app.open_chat)
        add(menu,'sql','SQL Explorer · ER-схема…',self.app.open_sql_explorer)
        menu.addSeparator()
        add(menu,'pause' if not self.app.paused else 'check',
            'Приостановить запись истории' if not self.app.paused else 'Возобновить запись',self.toggle_capture)
        add(menu,'close','Очистить обычную историю…',self.clear_recent)
        add(menu,'settings','Настройки приложения…',self.app.open_settings)
        menu.exec(self.more_button.mapToGlobal(QPoint(0,self.more_button.height())))

    def choose_workspace(self,workspace_id):
        self.selected_workspace=workspace_id
        self.space_mode='shared'
        self.refresh()

    def refresh_workspace_strip(self):
        available=[(wid,space['name']) for wid,space in self.app.workspaces.spaces.items()
                   if space['members'].get(self.app.identity.id)=='accepted']
        if self.selected_workspace not in {wid for wid,_ in available}:
            self.selected_workspace=available[0][0] if available else None
        signature=tuple(available)
        # Keep button widths readable; horizontal overflow is scrollable.
        # The rest of the history width must not shrink as spaces are added.
        self.workspace_buttons_host.setMinimumWidth(
            sum(min(220,max(90,len(name)*9+26))+8 for _,name in available)+16 if available else 280)
        if signature!=self._workspace_signature:
            self._workspace_signature=signature
            while self.workspace_buttons.count():
                node=self.workspace_buttons.takeAt(0)
                if node.widget():node.widget().deleteLater()
            self.space_buttons={}
            for wid,name in available:
                button=action(name,lambda checked=False,key=wid:self.choose_workspace(key))
                button.setToolTip(name)
                button.setMaximumWidth(220)
                self.workspace_buttons.addWidget(button)
                self.space_buttons[wid]=button
            if not available:
                self.workspace_buttons.addWidget(label('Нет доступных пространств'))
                self.workspace_buttons.addWidget(action('Создать…',self.app.open_workspaces))
            self.workspace_buttons.addStretch(1)
        for wid,button in getattr(self,'space_buttons',{}).items():
            button.setObjectName('primary' if wid==self.selected_workspace else '')
            button.style().unpolish(button);button.style().polish(button)
        self.workspace_strip.setVisible(self.space_mode=='shared')

    def rebuild_nav(self):
        if not hasattr(self,'nav_layout'):return
        while self.nav_layout.count():
            child=self.nav_layout.takeAt(0)
            if child.widget():child.widget().deleteLater()
        self.nav={}
        for c in self.app.categories.visible_categories():
            k=c['id']
            b=action('  '+c['name'],category_click_handler(k,self.change_filter),icon_name=c['icon'])
            b.setIconSize(QSize(23,23))
            b.setObjectName('nav');b.setProperty('chosen','true' if k==self.category else 'false')
            self.nav_layout.addWidget(b);self.nav[k]=b
        self.nav_layout.addStretch()

    def mark_source_active(self):
        names=sorted({str(x.get('source_app') or 'Неизвестно') for x in self.app.vault.items},key=str.casefold)
        signature=tuple(names)
        if signature!=self.app_buttons_signature:
            self.app_buttons_signature=signature
            while self.app_buttons.count():
                child=self.app_buttons.takeAt(0)
                if child.widget():child.widget().deleteLater()
            self.app_pills={}
            for name in ['Все приложения']+names:
                source='' if name=='Все приложения' else name
                b=action(name,lambda checked=False,value=source:self.change_source(value))
                b.setMaximumWidth(185);b.setToolTip(name)
                self.app_buttons.addWidget(b);self.app_pills[source]=b
            self.app_buttons.addStretch()
            self.app_buttons_host.setMinimumWidth(sum(max(110,min(185,len(name)*9+32)) for name in ['Все приложения']+names)+10)
        for source,b in getattr(self,'app_pills',{}).items():
            b.setObjectName('primary' if source==self.source_app else '')
            b.style().unpolish(b);b.style().polish(b)
        self.app_strip.setVisible(self.space_mode=='apps')

    def on_source_changed(self,*_):
        self.refresh()

    def change_source(self,name):
        self.source_app=name
        self.category='all'
        self.space_mode='apps'
        self.refresh()

    def change_filter(self,k):
        if not isinstance(k,str) or self.app.categories.get(k) is None:
            return  # Ignore malformed/obsolete category IDs, including Qt clicked(bool).
        self.category=k
        for key,b in self.nav.items():
            b.setProperty('chosen','true' if k==key else 'false')
            b.style().unpolish(b);b.style().polish(b)
        self.refresh()

    def edit_categories(self):
        win=CategoryEditor(self.app,self)
        if win.exec()==QDialog.Accepted:
            if self.category not in [c['id'] for c in self.app.categories.categories]:self.category='all'
            self.rebuild_nav();self.refresh()

    def choose_source_app(self):
        self.set_space_mode('apps')

    def set_space_mode(self,mode):
        if mode not in ('personal','apps','shared'):return
        self.space_mode=mode
        self.refresh()

    def extract_item(self,ident):
        item=self.app.vault.find(ident)
        if not item or item.get('encrypted'):
            return error(self,'Нельзя анализировать защищённый фрагмент')
        try:
            ExtractDialog(self.app,item,self).exec()
        except ValueError as exc:
            error(self,str(exc))

    def smart_item(self,ident):
        item=self.app.vault.find(ident)
        if not item or item.get('encrypted'):return
        try:steps=action_catalog(item.get('text',''),item.get('kind','text'))
        except ValueError as ex:return error(self,ex)
        if not steps:return error(self,'Для этого фрагмента пока нет преобразований')
        dialog=QDialog(self);dialog.setWindowTitle('ORBITclip · Умные действия · v'+CLIENT_VERSION)
        dialog.resize(960,610);dialog.setMinimumSize(680,450)
        root=QVBoxLayout(dialog);root.setContentsMargins(18,16,18,16);root.setSpacing(10)
        title=QLabel('Работа с фрагментом');title.setObjectName('heading');root.addWidget(title)
        root.addWidget(label('Результат вычисляется локально · исходная запись остаётся без изменений'))
        columns=QHBoxLayout();root.addLayout(columns,1)
        menu=QListWidget();menu.setFixedWidth(252)
        for step in steps:
            record=QListWidgetItem(('◉  ' if step['report'] else '↗  ')+step['title'])
            record.setToolTip(step['description']);menu.addItem(record)
        columns.addWidget(menu)
        right=QVBoxLayout();columns.addLayout(right,1)
        description=label('');description.setWordWrap(True);right.addWidget(description)
        comparison=QHBoxLayout();right.addLayout(comparison)
        original=QPlainTextEdit(item.get('text',''));original.setReadOnly(True)
        original.setPlaceholderText('Исходный текст')
        output=QPlainTextEdit();output.setPlaceholderText('Предварительный результат')
        comparison.addWidget(original,1);comparison.addWidget(output,1)
        meta=label('');right.addWidget(meta)
        current={'step':steps[0]}
        def update_preview(row,*_):
            if row<0 or row>=len(steps):return
            step=steps[row];current['step']=step
            description.setText(step['description'])
            output.setPlainText(step['result']);output.setReadOnly(step['report'])
            meta.setText('Отчёт / диагностика' if step['report'] else 'Преобразование · предварительный просмотр')
        menu.currentRowChanged.connect(update_preview)
        menu.setCurrentRow(0)
        controls=QHBoxLayout();root.addLayout(controls)
        def copy():self.app.copy_text(output.toPlainText());dialog.accept()
        def as_entry():
            if current['step']['report']:
                return error(dialog,'Диагностический отчёт нельзя сохранять вместо исходной записи. Скопируй его отдельно.')
            self.app.add_to_history(output.toPlainText(),force=True);dialog.accept();self.refresh()
        def export():
            if current['step']['report']:return error(dialog,'Для экспорта используй кнопку «Скопировать отчёт»')
            filepath,_=QFileDialog.getSaveFileName(dialog,'Экспорт',str(Path.home()/('fragment'+current['step']['extension'])))
            if filepath:
                try:Path(filepath).write_text(output.toPlainText(),encoding='utf-8')
                except OSError as ex:error(dialog,ex)
        controls.addWidget(action('Скопировать результат',copy,primary=True))
        controls.addWidget(action('Сохранить новым фрагментом',as_entry))
        controls.addWidget(action('Экспортировать…',export))
        controls.addStretch();controls.addWidget(action('Закрыть',dialog.reject))
        dialog.exec()

    def publish_item(self,ident):
        if self.app.offline:return error(self,'Режим «Быть оффлайн»: публикация отключена')
        item=self.app.vault.find(ident)
        if not item:return
        if item.get('encrypted'):return error(self,'Защищённую запись нельзя публиковать')
        choices=[(wid,s['name']) for wid,s in self.app.workspaces.spaces.items()
                 if s['members'].get(self.app.identity.id)=='accepted']
        if not choices:return error(self,'Сначала создай общее пространство или прими приглашение')
        labels=[x[1] for x in choices]
        chosen,ok=QInputDialog.getItem(self,'Опубликовать запись','Рабочее пространство:',labels,0,False)
        if not ok:return
        wid=choices[labels.index(chosen)][0]
        if QMessageBox.question(self,'Публикация','Отправить выбранный фрагмент участникам пространства «'+chosen+'»?')!=QMessageBox.Yes:return
        try:payload=self.app.workspaces.publish(wid,item)
        except ValueError as ex:return error(self,str(ex))
        self.app.broadcast_workspace(wid,payload)
        self.app.toast.pop('Фрагмент отправлен участникам онлайн · офлайн-очереди пока нет')
        self.refresh()

    def on_search_changed(self,*_):
        # Do not instantiate hundreds of QWidget cards for every keystroke.
        self.search_timer.start(160)

    def show_more(self):
        self.render_limit+=PAGE_SIZE
        self.refresh()

    def refresh(self):
        if not hasattr(self,'rows'):return
        needle=self.search.text().casefold().strip()
        source=self.source_app if self.space_mode=='apps' else ''
        period=self.period_combo.currentData() or 'all'
        semantic=bool(needle and self.semantic_mode.isChecked())
        signature=(self.space_mode,self.category,source,period,needle,
                   semantic,self.selected_workspace)
        changed=signature!=self._view_signature
        old_scroll=0 if changed else self.scroll.verticalScrollBar().value()
        if changed:
            self.render_limit=PAGE_SIZE
            self._view_signature=signature
        while self.rows.count():
            child=self.rows.takeAt(0)
            if child.widget():child.widget().deleteLater()
        if hasattr(self,'personal_tab'):
            self.personal_tab.setObjectName('primary' if self.space_mode=='personal' else '')
            self.apps_tab.setObjectName('primary' if self.space_mode=='apps' else '')
            self.shared_tab.setObjectName('primary' if self.space_mode=='shared' else '')
            for tab in (self.personal_tab,self.apps_tab,self.shared_tab):
                tab.style().unpolish(tab);tab.style().polish(tab)
        sources=tuple(sorted({str(x.get('source_app') or 'Неизвестно')
                              for x in self.app.vault.items},key=str.casefold))
        for key,button in self.nav.items():
            button.setProperty('chosen','true' if key==self.category else 'false')
            button.style().unpolish(button);button.style().polish(button)
        self.mark_source_active()
        self.refresh_workspace_strip()
        if self.space_mode=='apps' and source and source not in sources:
            self.source_app=''
            source=''
        if self.space_mode=='shared':
            wid=self.selected_workspace
            space=self.app.workspaces.spaces.get(wid,{})
            clips=space.get('clips',[])
            matches=[x for x in reversed(clips)
                     if needle in (x.get('text','')+' '+x.get('title','')).casefold()]
            shown,remaining=visible_page(matches,self.render_limit)
            self.counter.setText(
                f'Показано {len(shown)} из {len(matches)} опубликованных записей')
            if not matches:
                self.rows.addWidget(label('Здесь ещё нет опубликованных фрагментов. '
                                          'Открой личную историю и выбери «Опубликовать…».'))
            for c in shown:
                line=QFrame();line.setObjectName('card')
                hl=QHBoxLayout(line)
                title=c.get('title') or c.get('kind','Текст')
                sender=c.get('sender','')
                owner_name=('Я' if sender==self.app.identity.id else
                            self.app.identity.trusted.get(sender,{}).get('name',sender[:8]))
                hl.addWidget(label(truncate(title+' · '+owner_name+' · '+c.get('text',''),170)),1)
                hl.addWidget(action('Копировать',
                                    lambda _=False,v=c['text']:self.app.copy_text(v)))
                self.rows.addWidget(line)
            if remaining:
                self.rows.addWidget(action(f'Показать ещё {min(PAGE_SIZE,remaining)} '
                                            f'· осталось {remaining}',self.show_more))
            self.rows.addStretch()
        else:
            entries=history_matches(
                self.app.vault.items,needle,source,period,semantic,
                category_match=lambda v:self.app.categories.matches(v,self.category))
            shown,remaining=visible_page(entries,self.render_limit)
            self.counter.setText(
                f'Показано {len(shown)} из {len(entries)} записей · '
                f'{self.app.vault.favorite_count} избранных')
            if not entries:
                empty=label('Записей не найдено · измени период или условия поиска')
                empty.setAlignment(Qt.AlignCenter)
                self.rows.addWidget(empty)
            for item in shown:
                self.rows.addWidget(VaultRow(self,item))
            if remaining:
                self.rows.addWidget(action(f'Показать ещё {min(PAGE_SIZE,remaining)} '
                                            f'· осталось {remaining}',self.show_more))
            self.rows.addStretch()
        if changed:
            self.scroll.verticalScrollBar().setValue(0)
        else:
            # Defer until Qt has recalculated row layout, preserve browsing
            # position after a clipboard event, favourite edit or load-more.
            QTimer.singleShot(0,lambda value=old_scroll:
                self.scroll.verticalScrollBar().setValue(
                    min(value,self.scroll.verticalScrollBar().maximum())))

    def preview_item(self,ident):
        """Readable large text preview; never expose encrypted content."""
        item=self.app.vault.find(ident)
        if not item:return
        encrypted=bool(item.get('encrypted'))
        dialog=QDialog(self)
        dialog.setWindowTitle('ORBITclip · Предпросмотр фрагмента')
        dialog.resize(710,490)
        outer=QVBoxLayout(dialog)
        kind=item.get('kind','text')
        name=str(item.get('title') or LABELS.get(kind,('','Текст'))[1])
        title=QLabel(name)
        title.setTextFormat(Qt.PlainText)
        title.setStyleSheet('font-size:16px;font-weight:700')
        outer.addWidget(title)
        source=item.get('source_app') or 'Неизвестно'
        outer.addWidget(label(f'Тип: {kind} · Источник: {source} · '+tooltip_time(item.get('ts',0))))
        content=QPlainTextEdit()
        content.setReadOnly(True)
        content.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        content.setPlainText('🔒 Защищённая запись. Для доступа используй действие «Копировать».'
                             if encrypted else str(item.get('text',''))[:200_000])
        outer.addWidget(content,1)
        bottom=QHBoxLayout()
        bottom.addWidget(action('Копировать',lambda:self.copy_item(ident)))
        if not encrypted:
            bottom.addWidget(action('Извлечь данные…',lambda:self.extract_item(ident)))
            bottom.addWidget(action('В очередь',lambda:self.app.enqueue_item(ident)))
            bottom.addWidget(action('Преобразования…',lambda:self.smart_item(ident)))
        bottom.addStretch()
        bottom.addWidget(action('Закрыть',dialog.accept,primary=True))
        outer.addLayout(bottom)
        dialog.exec()

    def copy_item(self,ident):
        item=self.app.vault.find(ident)
        if not item:return
        text=item.get('text','')
        if item.get('encrypted'):
            pwd,ok=QInputDialog.getText(self,'Расшифровать запись','Пароль записи:',QLineEdit.Password)
            if not ok:return
            try:text=self.app.vault.decrypt_item(ident,pwd)
            except ValueError as ex:return error(self,str(ex))
        self.app.copy_text(text);self.app.toast.pop('Скопировано в буфер')

    def toggle_favorite(self,ident):
        self.app.vault.favorite(ident);self.app.reset_hotkeys();self.refresh()

    def remove_item(self,ident):
        item=self.app.vault.find(ident)
        if not item:return
        if item.get('pinned') or item.get('encrypted'):
            if QMessageBox.question(self,'Удаление','Удалить избранную или защищённую запись?')!=QMessageBox.Yes:return
        self.app.vault.delete(ident);self.app.reset_hotkeys();self.refresh()

    def rename_item(self,ident):
        item=self.app.vault.find(ident)
        if not item:return
        dialog=QDialog(self);dialog.setWindowTitle('Свойства фрагмента');dialog.resize(410,210)
        lay=QVBoxLayout(dialog)
        lay.addWidget(label('Название'))
        name=QLineEdit(item.get('title',''));lay.addWidget(name)
        lay.addWidget(label('Категория'))
        cats=OrbitSelect();cats.addItem('Без категории','')
        for c in self.app.categories.categories:
            if c['id'] not in ('all','favorites','code') and c.get('visible',True):
                cats.addItem(c['name'],c['id'])
        idx=cats.findData(item.get('category',''))
        cats.setCurrentIndex(max(0,idx));lay.addWidget(cats)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);lay.addWidget(buttons)
        if dialog.exec()==QDialog.Accepted:
            self.app.vault.describe(ident,title=name.text(),category=cats.currentData() or '')
            self.refresh()

    def toggle_priority(self,ident):self.app.vault.toggle_priority(ident);self.refresh()
    def toggle_scroll(self,ident):self.app.vault.toggle_scroll(ident);self.refresh()

    def encrypt_item(self,ident):
        pwd,ok=QInputDialog.getText(self,'Защита записи','Придумай пароль (от 8 символов):',QLineEdit.Password)
        if not ok:return
        confirm,ok=QInputDialog.getText(self,'Защита записи','Повтори пароль:',QLineEdit.Password)
        if not ok:return
        if pwd!=confirm:return error(self,'Пароли не совпадают')
        original=(self.app.vault.find(ident) or {}).get('text','')
        try:self.app.vault.encrypt_item(ident,pwd)
        except ValueError as ex:return error(self,ex)
        # Do not leave the newly sealed secret in the system clipboard.
        if original and self.app.clipboard.text()==original:
            self.app.clipboard.setText('')
            self.app._last_clip=''
        self.app.reset_hotkeys();self.refresh()

    def bind_item(self,ident):
        item=self.app.vault.find(ident)
        if not item:return
        suggestion=('cmd' if platform.system()=='Darwin' else 'ctrl')+'+alt+1'
        shortcut,ok=QInputDialog.getText(self,'Горячая клавиша','Например, Ctrl+Alt+1 или Cmd+Alt+K:',text=item.get('hotkey') or suggestion)
        if not ok:return
        try:self.app.vault.bind(ident,shortcut);self.app.reset_hotkeys();self.refresh()
        except ValueError as ex:error(self,ex)

    def toggle_capture(self):
        self.app.paused=not self.app.paused
        self.app.settings['recording_paused']=self.app.paused;self.app.save_settings();self.refresh()

    def clear_recent(self):
        if QMessageBox.question(self,'Очистка','Очистить обычную историю? Избранное сохранится.')==QMessageBox.Yes:
            self.app.vault.clear_recent();self.refresh()

    def keyPressEvent(self,e):
        if e.matches(QKeySequence.StandardKey.Find):self.search.setFocus();self.search.selectAll();return
        super().keyPressEvent(e)


class MessageBubble(QFrame):
    """Compact Telegram-style bubble, keeping message controls within the bubble."""
    def __init__(self, app, content, own=False, stamp='', saved_path='', sender='', on_reply=None, on_forward=None, on_delete=None, grouped=False):
        super().__init__();self.app=app
        self.content=content;self.own=own;self.on_reply=on_reply;self.on_forward=on_forward;self.on_delete=on_delete
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_message_menu)
        self.setObjectName('chatBubble')
        theme=app.palette
        light=QColor(theme['bg']).lightness()>155
        shade = (QColor(theme['accent']).lighter(260).name() if light else QColor(theme['accent']).darker(250).name()) if own else theme['raised']
        self.setStyleSheet(
            f'QFrame#chatBubble{{background:{shade};border:1px solid '+
            (QColor(theme['accent']).darker(180).name() if own else theme['border'])+
            ';border-radius:17px;} QLabel{border:0;background:transparent;}')
        self.setMaximumWidth(475)
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Maximum,QSizePolicy.Preferred)
        inner=QVBoxLayout(self);inner.setContentsMargins(14,7 if grouped else 10,14,8);inner.setSpacing(4)
        if not own and sender and not grouped:
            who=QLabel(sender)
            who.setStyleSheet('color:'+theme['accent']+';font-size:10px;font-weight:600;')
            inner.addWidget(who)
        quoted=content.get('reply_to')
        if isinstance(quoted,dict):
            summary=QLabel(('↳ '+('Вы' if quoted.get('own') else 'Собеседник')+' · '+truncate(str(quoted.get('text','')),95)))
            summary.setWordWrap(True);summary.setTextFormat(Qt.PlainText)
            summary.setStyleSheet(f"background:{theme['surface']};color:{theme['muted']};border-left:2px solid {theme['accent']};border-radius:4px;padding:5px;font-size:10px;")
            inner.addWidget(summary)
        kind=content.get('kind')
        if kind in ('file','file_ref'):
            name=str(content.get('name','attachment'))
            line=QHBoxLayout();line.setSpacing(7)
            file_ico=QLabel('▣');file_ico.setStyleSheet('color:'+theme['accent']+';font-size:22px;')
            line.addWidget(file_ico)
            info=QVBoxLayout();info.setSpacing(1)
            filename=QLabel(truncate(name,46))
            filename.setToolTip(name)
            filename.setStyleSheet('color:'+theme['text']+';font-size:12px;font-weight:600;')
            info.addWidget(filename)
            file_path=Path(saved_path) if saved_path else None
            self.saved_path=file_path
            if file_path and file_path.is_file():
                sub=QLabel('Сохранено на компьютере')
                sub.setStyleSheet('color:'+theme['muted']+';font-size:10px;')
                info.addWidget(sub)
                filename.setToolTip(str(file_path))
            elif own:
                info.addWidget(QLabel('Отправленный файл'))
            else:
                sub=QLabel('Файл ещё не сохранён')
                sub.setStyleSheet('color:#DEA49F;font-size:10px;')
                info.addWidget(sub)
            line.addLayout(info,1)
            inner.addLayout(line)
            # Local-only preview of saved attachments; no remote image fetching.
            if file_path and file_path.is_file() and file_path.suffix.lower() in (
                    '.png','.jpg','.jpeg','.webp','.gif'):
                reader=QImageReader(str(file_path))
                reader.setAutoTransform(True)
                reader.setScaledSize(QSize(280,180))
                if reader.canRead():
                    image=reader.read()
                    if not image.isNull():
                        thumbnail=QLabel()
                        thumbnail.setPixmap(QPixmap.fromImage(image))
                        thumbnail.setAlignment(Qt.AlignLeft)
                        thumbnail.setToolTip('Предпросмотр сохранённого изображения')
                        inner.addWidget(thumbnail)
        else:
            txt=str(content.get('text',''))
            excerpt=QLabel(truncate(txt,2600))
            excerpt.setTextInteractionFlags(Qt.TextSelectableByMouse)
            excerpt.setTextFormat(Qt.PlainText)
            excerpt.setWordWrap(True)
            excerpt.setMaximumWidth(440)
            excerpt.setStyleSheet('font-size:13px;color:'+theme['text']+';line-height:1.3;')
            inner.addWidget(excerpt)
        # Keep only the timestamp in the layout. Tools are overlaid on hover,
        # so the bubble never changes height when action buttons appear.
        foot=QHBoxLayout();foot.setContentsMargins(0,0,0,0);foot.setSpacing(0)
        foot.addStretch(1)
        when=QLabel((('✓✓ ' if content.get('_delivered') else '◷ ') if own and content.get('delivery_id') else ('✓ ' if own else ''))+stamp)
        when.setStyleSheet('color:'+theme['muted']+';font-size:9px;')
        foot.addWidget(when)
        inner.addLayout(foot)
        self.hover_actions=QFrame(self)
        self.hover_actions.setObjectName('hoverActions')
        self.hover_actions.setStyleSheet('QFrame#hoverActions{background:#172934;border:1px solid #456071;border-radius:7px;}')
        tools=QHBoxLayout(self.hover_actions)
        tools.setContentsMargins(2,1,2,1);tools.setSpacing(0)
        def add_button(name,tooltip,callback):
            button=tool(name,tooltip,callback,15)
            button.setFixedSize(25,23)
            tools.addWidget(button)
        if kind in ('file','file_ref') and self.saved_path and self.saved_path.is_file():
            add_button('document','Открыть файл',self.open_saved_file)
            add_button('history','Показать в папке',self.show_folder)
        elif kind not in ('file','file_ref'):
            add_button('copy','Скопировать сообщение',lambda:self.app.copy_text(str(content.get('text',''))))
        if self.on_reply is not None:
            add_button('send','Ответить',lambda:self.on_reply(self.content,self.own))
        if self.on_forward is not None:
            add_button('remote','Переслать',lambda:self.on_forward(self.content))
        if self.on_delete is not None:
            add_button('close','Удалить у себя',self.on_delete)
        self.hover_actions.adjustSize()
        self.hover_actions.hide()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'hover_actions'):
            w=self.hover_actions.sizeHint().width()
            h=self.hover_actions.sizeHint().height()
            self.hover_actions.setGeometry(5,max(1,self.height()-h-2),w,h)
            self.hover_actions.raise_()

    def enterEvent(self,event):
        self.hover_actions.show()
        self.hover_actions.raise_()
        super().enterEvent(event)

    def leaveEvent(self,event):
        # Parent hover remains active when the pointer enters an action button.
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self.hover_actions.hide()
        super().leaveEvent(event)

    def show_message_menu(self,at):
        menu=QMenu(self)
        if self.content.get('kind')=='text':
            menu.addAction('Копировать текст',lambda:self.app.copy_text(str(self.content.get('text',''))))
        if self.on_reply:menu.addAction('Ответить',lambda:self.on_reply(self.content,self.own))
        if self.on_forward:menu.addAction('Переслать…',lambda:self.on_forward(self.content))
        if self.on_delete:menu.addAction('Удалить у себя',self.on_delete)
        if self.content.get('kind') in ('file','file_ref') and getattr(self,'saved_path',None):
            menu.addAction('Открыть файл',self.open_saved_file)
        menu.exec(self.mapToGlobal(at))

    def open_saved_file(self):
        if self.saved_path and self.saved_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_path)))
        else:error(self,'Локальный файл больше не найден')

    def show_folder(self):
        if self.saved_path and self.saved_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_path.parent)))
        else:error(self,'Папка с файлом недоступна')


class ChatComposer(QPlainTextEdit):
    """Enter sends; Shift+Enter inserts a newline. Ctrl/Cmd+Enter also sends."""
    def __init__(self,send_callback,parent=None,file_callback=None):
        super().__init__(parent)
        self.send_callback=send_callback
        self.file_callback=file_callback
        self.setAcceptDrops(True)

    def dragEnterEvent(self,event):
        if self.file_callback and event.mimeData().hasUrls() and any(
                url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self,event):
        if self.file_callback and event.mimeData().hasUrls() and any(
                url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:super().dragMoveEvent(event)

    def dropEvent(self,event):
        if self.file_callback and event.mimeData().hasUrls():
            paths=[url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.file_callback(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Return,Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                return super().keyPressEvent(event)
            if not (event.modifiers() & Qt.AltModifier):
                self.send_callback()
                event.accept()
                return
        super().keyPressEvent(event)


class ChatWindow(QWidget):
    """Independent two-pane messenger: conversation list + private history."""
    def __init__(self, app):
        super().__init__(None)
        self.setWindowFlag(Qt.Window, True)
        self.app=app
        self.reply_to=None
        self.setWindowTitle('ORBITclip · Сообщения · v'+CLIENT_VERSION)
        self.setWindowIcon(QIcon(str(ASSETS/'orbit_icon.png')))
        self.resize(1120,760)
        self.setMinimumSize(790,550)
        self.setAcceptDrops(True)
        self.build()

    def apply_theme(self):
        p=self.app.palette
        self.setStyleSheet(f"""
            QWidget#messengerShell{{background:{p['bg']};}}
            QFrame#chatSidebar{{background:{p['surface']};border:1px solid {p['border']};border-radius:16px;}}
            QFrame#chatHeader{{background:{p['surface']};border:1px solid {p['border']};border-radius:14px;}}
            QFrame#chatComposer{{background:{p['raised']};border:1px solid {p['border']};border-radius:17px;}}
            QPlainTextEdit#chatInput{{background:transparent;color:{p['text']};border:0;padding:8px 6px;font-size:13px;}}
            QListWidget#dialogList{{background:transparent;border:0;outline:0;}}
            QListWidget#dialogList::item{{border-radius:11px;padding:12px 10px;margin-bottom:4px;
                                          background:transparent;color:{p['text']};}}
            QListWidget#dialogList::item:hover{{background:{p['hover']};}}
            QListWidget#dialogList::item:selected{{background:{p['hover']};color:{p['text']};}}
        """)
        if hasattr(self,'msg_scroll'):
            self.msg_scroll.setStyleSheet(
                f'QScrollArea#messageScroll{{background:{p["bg"]};border-radius:15px;border:0;}}')
            self.msg_container.setStyleSheet('background:'+p['bg']+';')
        if hasattr(self,'avatar'):
            self.avatar.setStyleSheet(
                f"background:{p['hover']};color:{p['accent']};border-radius:19px;"
                "font-size:18px;font-weight:700;")

    def build(self):
        self.setObjectName('messengerShell')
        self.apply_theme()
        lay=QVBoxLayout(self);lay.setContentsMargins(12,11,12,12);lay.setSpacing(10)
        headline=QHBoxLayout()
        title=QLabel('ORBITclip');title.setStyleSheet('font-size:20px;font-weight:750;color:#F5B49F;')
        headline.addWidget(title)
        headline.addWidget(label(' / сообщения'))
        headline.addStretch()
        self.online=label('● Проверяем сервер');headline.addWidget(self.online)
        headline.addWidget(action('Пространства',self.app.open_workspaces))
        lay.addLayout(headline)
        tabs=QHBoxLayout()
        self.chat_tab=action('Сообщения',lambda:self.set_page(0),primary=True)
        self.connect_tab=action('Устройства и подключение',lambda:self.set_page(1))
        tabs.addWidget(self.chat_tab);tabs.addWidget(self.connect_tab);tabs.addStretch()
        lay.addLayout(tabs)
        self.pages=QStackedWidget();lay.addWidget(self.pages,1)
        self.build_chat();self.build_connect()
        self.apply_theme()
        self.set_page(0 if self.app.remote_config or self.app.identity.trusted else 1)
        self.refresh_peers()

    def build_chat(self):
        page=QWidget()
        outer=QHBoxLayout(page);outer.setContentsMargins(0,2,0,0);outer.setSpacing(8)
        sidebar=QFrame();sidebar.setObjectName('chatSidebar');sidebar.setFixedWidth(282)
        left=QVBoxLayout(sidebar);left.setContentsMargins(12,15,12,12);left.setSpacing(10)
        label_convos=QLabel('Диалоги');label_convos.setStyleSheet('font-weight:700;font-size:15px;');left.addWidget(label_convos)
        self.sidebar_search=QLineEdit()
        self.sidebar_search.setPlaceholderText('⌕  Поиск по диалогам')
        self.sidebar_search.textChanged.connect(self.refresh_dialog_list)
        left.addWidget(self.sidebar_search)
        self.dialog_list=QListWidget()
        self.dialog_list.setObjectName('dialogList')
        self.dialog_list.setSpacing(2)
        self.dialog_list.setWordWrap(True)
        self.dialog_list.currentItemChanged.connect(self.choose_dialog)
        left.addWidget(self.dialog_list,1)
        left.addWidget(action('＋  Подключить устройство',lambda:self.set_page(1)))
        outer.addWidget(sidebar)
        right=QVBoxLayout();right.setSpacing(7);right.setContentsMargins(0,0,0,0)
        bar=QFrame();bar.setObjectName('chatHeader')
        heading=QHBoxLayout(bar);heading.setContentsMargins(16,12,16,12);heading.setSpacing(12)
        self.avatar=QLabel('◎');self.avatar.setFixedSize(38,38);self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet('background:#354E57;color:#9FE5D0;border-radius:19px;font-size:18px;font-weight:700;')
        heading.addWidget(self.avatar)
        info=QVBoxLayout();info.setSpacing(2)
        self.peer_name=QLabel('Выбери диалог')
        self.peer_name.setStyleSheet('font-size:14px;font-weight:700;')
        self.connection_hint=label('Для доставки дождись подтверждения второго устройства · v'+CLIENT_VERSION)
        info.addWidget(self.peer_name);info.addWidget(self.connection_hint)
        heading.addLayout(info,1)
        self.delivery_button=action('Очередь · 0',self.show_delivery_queue)
        heading.addWidget(self.delivery_button)
        heading.addWidget(tool('settings','Управление подключениями',lambda:self.set_page(1)))
        right.addWidget(bar)
        filters=QHBoxLayout();filters.setSpacing(5)
        self.channel=OrbitSelect();self.channel.setMaximumWidth(175)
        self.channel.addItem('Все сообщения','all')
        self.channel.addItem('Переписка','chat')
        self.channel.addItem('Только буфер и файлы','clipboard')
        self.channel.currentIndexChanged.connect(self.refresh_messages)
        filters.addWidget(self.channel)
        self.search_messages=QLineEdit()
        self.search_messages.setPlaceholderText('Поиск по переписке…')
        self.search_messages.setClearButtonEnabled(True)
        self.search_messages.textChanged.connect(self.refresh_messages)
        filters.addWidget(self.search_messages,1)
        right.addLayout(filters)
        self.msg_scroll=QScrollArea();self.msg_scroll.setWidgetResizable(True)
        self.msg_scroll.setObjectName('messageScroll')
        self.msg_scroll.setStyleSheet('QScrollArea#messageScroll{background:#14222D;border-radius:15px;border:0;}')
        self.msg_container=QWidget();self.msg_container.setStyleSheet('background:#14222D;')
        self.msg_layout=QVBoxLayout(self.msg_container)
        self.msg_layout.setContentsMargins(18,12,18,12);self.msg_layout.setSpacing(5)
        self.msg_scroll.setWidget(self.msg_container);right.addWidget(self.msg_scroll,1)
        self.reply_bar=QFrame();self.reply_bar.setObjectName('card')
        reply_layout=QHBoxLayout(self.reply_bar);reply_layout.setContentsMargins(10,5,6,5)
        self.reply_label=label('')
        reply_layout.addWidget(self.reply_label,1)
        reply_layout.addWidget(tool('close','Отменить ответ',self.cancel_reply))
        self.reply_bar.hide();right.addWidget(self.reply_bar)
        composer=QFrame();composer.setObjectName('chatComposer')
        compose_row=QHBoxLayout(composer);compose_row.setContentsMargins(10,8,10,8);compose_row.setSpacing(8)
        compose_row.addWidget(tool('document','Прикрепить файл (до 40 МБ)',self.send_file))
        compose_row.addWidget(tool('clipboard','Отправить содержимое буфера',self.send_clipboard))
        self.compose=ChatComposer(self.send_text,file_callback=self.send_files)
        self.compose.setObjectName('chatInput')
        self.compose.setPlaceholderText('Написать сообщение…  ·  Перетащи файлы сюда')
        self.compose.setFixedHeight(58)
        self.compose.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        compose_row.addWidget(self.compose,1)
        compose_row.addWidget(tool('favorite','Эмодзи',self.open_emoji))
        self.send_button=action('➤',self.send_text,primary=True)
        self.send_button.setFixedSize(44,43)
        compose_row.addWidget(self.send_button)
        right.addWidget(composer)
        footer=label('🔒 Шифрованный обмен · Перетащи файл в окно переписки · До 3 МБ на файл')
        right.addWidget(footer)
        outer.addLayout(right,1)
        self.pages.addWidget(page)

    def open_emoji(self):
        menu=QMenu(self)
        for token in ('🙂','👍','❤️','😂','🙏','👀','✅','🎉','🔥','✨','👋','🤝'):
            menu.addAction(token,lambda checked=False,ch=token:self.compose.insertPlainText(ch))
        menu.exec(QCursor.pos())

    def choose_dialog(self,item,previous=None):
        if item is None:return
        peer=item.data(Qt.UserRole)
        if not peer or peer==self.app.selected_peer:return
        self.app.selected_peer=peer
        self.app.save_settings()
        self.cancel_reply()
        self.mark_conversation_read()
        self.refresh_messages()

    def mark_conversation_read(self):
        peer=self.app.selected_peer
        if self.isVisible() and self.pages.currentIndex()==0 and peer:
            self.app.clear_unread(peer)

    def refresh_dialog_list(self,*_):
        if not hasattr(self,'dialog_list'):return
        currently=self.app.selected_peer
        needle=self.sidebar_search.text().strip().casefold()
        self.dialog_list.blockSignals(True)
        self.dialog_list.clear()
        entries=[(p,k.get('name') or p[:12]) for p,k in self.app.identity.trusted.items()]
        if self.app.remote_config:entries.append(('legacy','Старая пара · PIN'))
        for peer,name in entries:
            if needle and needle not in name.casefold():continue
            if peer=='legacy':
                place=self.app.cursor_place;secret=self.app.remote_pair
            else:
                _,place,secret=self.app.peer_channel(peer)
            last=self.app.store.fetch(place,1) if place else []
            snippet='Нет сообщений'
            if last:
                try:
                    payload=decrypt_message(last[0]['payload'],secret)
                    snippet=('📎 '+str(payload.get('name','Файл'))) if payload.get('kind') in ('file','file_ref') else truncate(payload.get('text',''),38)
                except Exception:snippet='Зашифрованное сообщение'
            online=peer in {p.get('id') for p in self.app.online_devices}
            status='●' if online else '○'
            unread=self.app.unread_peers.get(peer,0)
            count=('   ● '+str(unread)) if unread else ''
            item=QListWidgetItem(f'{status}  {name}{count}\n     {truncate(snippet,42)}')
            item.setData(Qt.UserRole,peer)
            item.setToolTip(name)
            item.setSizeHint(QSize(245,66))
            self.dialog_list.addItem(item)
            if peer==currently:self.dialog_list.setCurrentItem(item)
        self.dialog_list.blockSignals(False)
        self.update_conversation_heading()

    def update_conversation_heading(self):
        if not hasattr(self,'peer_name'):return
        peer=self.app.selected_peer
        contact=self.app.identity.trusted.get(peer)
        name=(contact or {}).get('name') or ('Старая пара · PIN' if peer=='legacy' else 'Нет выбранного устройства')
        self.peer_name.setText(name)
        self.avatar.setText(name[:1].upper() if name else '◉')
        peers={p.get('id') for p in self.app.online_devices}
        text='● В сети' if peer in peers else ('○ Ожидаем подключения' if peer else 'Открой подключение, чтобы добавить устройство')
        if self.app.offline:text='○ Режим оффлайн'
        self.connection_hint.setText(text)

    def build_connect(self):
        """Simple two-column navigation: overview / devices / pairing / server."""
        page=QWidget();outer=QHBoxLayout(page)
        outer.setContentsMargins(5,5,5,5);outer.setSpacing(12)
        side=QFrame();side.setObjectName('side');side.setFixedWidth(172)
        nav=QVBoxLayout(side);nav.setContentsMargins(8,12,8,10);nav.setSpacing(6)
        nav.addWidget(label('ПОДКЛЮЧЕНИЕ'))
        self.connect_nav={}
        for index,text,icon_name in [(0,'Обзор','clipboard'),(1,'Устройства','remote'),
                                      (2,'По PIN','hotkey'),(3,'Сервер','settings')]:
            b=action(text,lambda checked=False,k=index:self.set_connect_section(k),icon_name=icon_name)
            b.setObjectName('nav');nav.addWidget(b);self.connect_nav[index]=b
        nav.addStretch()
        nav.addWidget(label('v'+CLIENT_VERSION))
        outer.addWidget(side)
        self.connect_stack=QStackedWidget();outer.addWidget(self.connect_stack,1)
        def section(title,subtitle):
            host=QWidget();layout=QVBoxLayout(host)
            layout.setContentsMargins(15,14,15,15);layout.setSpacing(12)
            name=QLabel(title);name.setObjectName('heading');layout.addWidget(name)
            hint=label(subtitle);hint.setWordWrap(True);layout.addWidget(hint)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(host)
            self.connect_stack.addWidget(scroll)
            return layout

        overview=section('Подключение','Твой компьютер и состояние защищённого обмена.')
        overview.addWidget(label('ПСЕВДОНИМ КОМПЬЮТЕРА'))
        name_row=QHBoxLayout()
        self.nickname=QLineEdit(self.app.identity.name);self.nickname.setPlaceholderText('Псевдоним обязателен')
        name_row.addWidget(self.nickname,1);name_row.addWidget(action('Сохранить',self.save_nickname))
        overview.addLayout(name_row)
        overview.addWidget(label('ID: '+self.app.identity.id[:20]+'…'))
        self.version=label('Клиент '+CLIENT_VERSION+' · Сервер: ожидание')
        overview.addWidget(self.version)
        overview.addWidget(action('Смотреть устройства онлайн →',lambda:self.set_connect_section(1),primary=True))
        overview.addWidget(label('Чтобы пригласить компьютер, найди его в списке онлайн.\nPIN нужен только для первого подключения без токена.'))
        overview.addStretch()

        devices=section('Устройства онлайн','Выбери компьютер, затем отправь запрос. Получатель должен его одобрить.')
        devices.addWidget(action('Открыть каталог устройств ↗',self.app.open_online,icon_name='remote'))
        self.online_list=QListWidget();self.online_list.setMinimumHeight(220)
        devices.addWidget(self.online_list,1)
        devices.addWidget(action('Запросить сопряжение',self.request_selected_peer,primary=True))
        self.directory_info=label('Список обновляется примерно раз в 10 секунд')
        self.directory_info.setWordWrap(True);devices.addWidget(self.directory_info)

        pairing=section('Подключение по PIN','Используй этот способ, если второй компьютер ещё не знает секрет сервера.')
        self.pin_label=QLabel('— — — — — —')
        self.pin_label.setStyleSheet('font-size:28px;letter-spacing:4px;font-weight:700;color:#F7AC95')
        pairing.addWidget(self.pin_label)
        row=QHBoxLayout()
        row.addWidget(action('Создать PIN',self.create_pin,primary=True))
        row.addWidget(action('Копировать приглашение',self.copy_invite))
        pairing.addLayout(row)
        self.pin_input=QLineEdit();self.pin_input.setMaxLength(500)
        self.pin_input.setPlaceholderText('6 цифр или ссылка-приглашение')
        pairing.addWidget(self.pin_input)
        pairing.addWidget(action('Подключиться по PIN',self.join_pin))
        self.fingerprint=label('');self.fingerprint.setWordWrap(True);pairing.addWidget(self.fingerprint)
        self.approve=action('Разрешить это устройство',self.approve_pair,primary=True)
        self.approve.hide();pairing.addWidget(self.approve)
        pairing.addStretch()

        server=section('Сервер · дополнительно','Для обычного использования менять эти поля не нужно.')
        self.url=QLineEdit(self.app.url);self.url.setPlaceholderText('Адрес HTTPS-сервера')
        self.token=QLineEdit(self.app.token);self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText('Токен сервера')
        server.addWidget(label('АДРЕС'));server.addWidget(self.url)
        server.addWidget(label('ТОКЕН'));server.addWidget(self.token)
        buttons=QHBoxLayout()
        buttons.addWidget(action('Сохранить',self.save_server,primary=True))
        buttons.addWidget(action('Проверить соединение',self.app.check_server_async))
        server.addLayout(buttons)
        server.addWidget(label('Токен хранится на твоём компьютере. Не пересылай его посторонним.'))
        server.addStretch()
        self.pages.addWidget(page)
        self.set_connect_section(0)

    def set_connect_section(self,index):
        if not hasattr(self,'connect_stack'):return
        self.connect_stack.setCurrentIndex(index)
        for k,b in self.connect_nav.items():
            b.setProperty('chosen','true' if k==index else 'false')
            b.style().unpolish(b);b.style().polish(b)

    def save_nickname(self):
        try:self.app.identity.rename(self.nickname.text())
        except ValueError as ex:return error(self,ex)
        self.app.toast.pop('Псевдоним устройства сохранён')
        self.app.save_settings()

    def refresh_online_list(self,online):
        current=self.online_list.currentItem()
        old=current.data(Qt.UserRole) if current else None
        self.online_list.clear()
        for item in online:
            did=item.get('id','')
            peer=self.app.identity.trusted.get(did)
            flag=' · связано' if peer else ' · можно подключить'
            entry=QListWidgetItem('●  '+item.get('name','Устройство')+flag+' · '+did[:8])
            entry.setData(Qt.UserRole,did);entry.setIcon(icon('remote'))
            self.online_list.addItem(entry)
            if did==old:self.online_list.setCurrentItem(entry)
        self.directory_info.setText('Онлайн: '+str(len(online))+' · отображаются устройства с тем же токеном Render')

    def refresh_peers(self):
        """The visible dialog list is the only recipient selector."""
        connected=list(self.app.identity.trusted)
        if self.app.remote_config:connected.append('legacy')
        if self.app.selected_peer not in connected:
            self.app.selected_peer=connected[0] if connected else ''
        self.refresh_dialog_list()
        if self.pages.currentIndex()==0:self.refresh_messages()

    def request_selected_peer(self):
        if self.app.offline:return error(self,'Выключи режим оффлайн в настройках')
        item=self.online_list.currentItem()
        if not item:return error(self,'Выбери устройство из списка')
        if not self.app.token:return error(self,'Сначала настрой токен сервера')
        did=item.data(Qt.UserRole)
        if did in self.app.identity.trusted:return error(self,'Это устройство уже подключено')
        self.app.directory.request(did)
        self.directory_info.setText('Запрос отправляется…')

    def set_page(self,n):
        self.pages.setCurrentIndex(n)
        self.chat_tab.setObjectName('primary' if n==0 else '')
        self.connect_tab.setObjectName('primary' if n==1 else '')
        for b in (self.chat_tab,self.connect_tab):b.style().unpolish(b);b.style().polish(b)
        if n==0:
            self.mark_conversation_read()
            self.refresh_dialog_list()
            self.refresh_messages()

    def save_server(self):
        url=self.url.text().strip().rstrip('/')
        token=self.token.text().strip()
        try:
            from kinetic_pairing import parse_relay
            parse_relay(url)
            if len(token)<16:raise ValueError('Укажи токен сервера (минимум 16 символов)')
        except ValueError as ex:
            error(self,ex);return False
        self.app.url=url;self.app.token=token
        self.app.settings.update(remote_url=url,https_url=url,remote_token=token,https_token=token)
        self.app.save_settings()
        self.app.check_server_async()
        self.app.toast.pop('Настройки подключения сохранены')
        return True

    def create_pin(self):
        if self.app.offline:return error(self,'Выключи режим оффлайн в настройках')
        if not self.save_server():return
        if not self.app.remote_pair:self.app.remote_pair=make_pair_code()
        try:cfg=validate_config(self.app.url,self.app.token,self.app.remote_pair,self.app.tls_pin)
        except ValueError as ex:return error(self,ex)
        self.app.apply_remote(cfg)
        self.app.pair_role='owner';self.app.pair_bridge.create(cfg['url'],cfg['token'],cfg)
        self.fingerprint.setText('Создаём PIN…')

    def join_pin(self):
        if self.app.offline:return error(self,'Выключи режим оффлайн в настройках')
        # Joining by PIN does not require the relay token on this device.
        # The approved owner sends the token encrypted as part of pairing.
        self.app.url=self.url.text().strip().rstrip('/') or DEFAULT_RELAY_URL
        text=self.pin_input.text().strip()
        if not text:return error(self,'Введи PIN из шести цифр')
        self.app.pair_role='joiner';self.app.pair_bridge.join(text,self.url.text().strip() or DEFAULT_RELAY_URL)
        self.fingerprint.setText('Ожидаем подтверждение на первом компьютере…')

    def copy_invite(self):
        if self.app.pair_invite:self.app.copy_text(self.app.pair_invite)
        else:error(self,'Сначала создай PIN')

    def approve_pair(self):
        if self.app.offline:return error(self,'Выключи режим оффлайн в настройках')
        self.app.pair_bridge.approve();self.approve.hide()
        self.fingerprint.setText('Сопряжение разрешено. Второе устройство подключается…')

    def pair_event(self,event):
        name=event[0]
        if name=='pair_created':
            self.app.pair_invite=event[2]
            self.pin_label.setText('  '.join(event[1]))
            self.fingerprint.setText('Введи PIN на другом устройстве (действует 2:30).')
        elif name=='pair_joined':
            self.fingerprint.setText('Новое устройство ожидает разрешения. Код проверки: '+event[1])
            self.approve.show()
        elif name=='pair_fingerprint':self.fingerprint.setText('Код проверки: '+event[1]+' · ожидаем разрешение')
        elif name=='pair_ready':
            try:self.app.apply_remote(validate_config(event[1]['url'],event[1]['token'],event[1]['pair'],event[1].get('tls_pin','')))
            except (ValueError,KeyError) as ex:return error(self,ex)
            self.url.setText(self.app.url);self.token.setText(self.app.token)
            self.fingerprint.setText('Устройства сопряжены. Код проверки: '+event[2])
            self.set_page(0)
        elif name=='pair_error':self.fingerprint.setText('Ошибка: '+event[1])
        elif name=='pair_info':self.fingerprint.setText(event[1])

    def refresh_messages(self,*_):
        if not hasattr(self,'msg_layout'):return
        bar=self.msg_scroll.verticalScrollBar()
        old_pos=bar.value();stick_to_bottom=bar.maximum()-old_pos<55
        while self.msg_layout.count():
            child=self.msg_layout.takeAt(0)
            if child.widget():child.widget().deleteLater()
            if child.layout():child.layout().deleteLater()
        cfg,place,secret=self.app.active_channel()
        self.update_conversation_heading()
        if not cfg:
            empty=label('Нет подключённого устройства.\nОткрой «Устройства и подключение» для создания пары.')
            empty.setAlignment(Qt.AlignCenter);self.msg_layout.addWidget(empty)
            self.msg_layout.addStretch();return
        messages=self.app.store.fetch(place,100)
        current_date=None;found=0
        previous_direction=None;previous_ts=0
        needle=self.search_messages.text().strip().casefold()
        channel=self.channel.currentData() or 'all'
        for record in sorted(messages,key=lambda r:(float(r.get('ts',0)),int(r.get('id',0)))):
            try:content=decrypt_message(record['payload'],secret)
            except Exception:content={'kind':'text','text':'Не удалось расшифровать'}
            if (content.get('kind')=='file' and record.get('direction')=='in'
                    and not record.get('saved_path')):
                saved=self.app.save_incoming_attachment(place,record,content)
                if saved:record['saved_path']=str(saved)
            if record.get('delivery_id'):
                content['_delivered']=bool(record.get('delivered'))
            origin=content.get('origin','clipboard' if content.get('kind') in ('file','file_ref') else 'chat')
            if channel!='all' and channel!=origin:continue
            if needle and needle not in (str(content.get('text',''))+' '+str(content.get('name',''))).casefold():continue
            day=datetime.fromtimestamp(record['ts']).strftime('%d.%m.%Y')
            if day!=current_date:
                day_lbl=QLabel(day);day_lbl.setAlignment(Qt.AlignCenter)
                day_lbl.setStyleSheet('color:#8DA6B4;font-size:10px;margin:7px 0 5px;')
                self.msg_layout.addWidget(day_lbl);current_date=day
            own=record.get('direction')=='out'
            direction=record.get('direction')
            grouped=(previous_direction==direction and
                     float(record['ts'])-previous_ts<=300 and
                     float(record['ts'])>=previous_ts)
            previous_direction=direction
            previous_ts=float(record['ts'])
            wrap=QHBoxLayout();wrap.setSpacing(0)
            if own:wrap.addStretch(1)
            sender=(self.app.identity.trusted.get(self.app.selected_peer,{}).get('name','Устройство') if not own else '')
            bubble=MessageBubble(self.app,content,own,datetime.fromtimestamp(record['ts']).strftime('%H:%M'),
                                 saved_path=record.get('saved_path',''),sender=sender,
                                 on_reply=self.reply_to_message,on_forward=self.forward_message,
                                 on_delete=lambda loc=place,mid=record['id']:self.delete_message(loc,mid),
                                 grouped=grouped)
            wrap.addWidget(bubble)
            if not own:wrap.addStretch(1)
            row=QWidget();row.setLayout(wrap)
            self.msg_layout.addWidget(row);found+=1
        if not found:
            empty=label('По этому запросу сообщений нет' if needle else 'Пока нет сообщений · напиши первым')
            empty.setAlignment(Qt.AlignCenter)
            self.msg_layout.addWidget(empty)
        self.msg_layout.addStretch()
        if stick_to_bottom and not needle:
            QTimer.singleShot(35,lambda:bar.setValue(bar.maximum()))
        else:
            QTimer.singleShot(35,lambda pos=old_pos:bar.setValue(min(pos,bar.maximum())))

    def reply_to_message(self,content,own):
        text=content.get('text') if content.get('kind') not in ('file','file_ref') else '📎 '+str(content.get('name','Файл'))
        self.reply_to={'own':bool(own),'text':truncate(str(text or ''),130)}
        self.reply_label.setText('Ответ на '+('своё сообщение' if own else 'сообщение собеседника')+': '+truncate(str(text or ''),72))
        self.reply_bar.show();self.compose.setFocus()

    def cancel_reply(self):
        self.reply_to=None
        if hasattr(self,'reply_bar'):self.reply_bar.hide()

    def delete_message(self,place,message_id):
        if QMessageBox.question(self,'Удаление сообщения','Удалить сообщение только из локальной истории?')!=QMessageBox.Yes:return
        self.app.store.delete(place,message_id)
        self.refresh_messages();self.refresh_dialog_list()

    def forward_message(self,content):
        if content.get('kind')=='file_ref':
            return error(self,'Для пересылки большого файла выбери его заново через прикрепление.')
        choices=[(record.get('name',p[:10]),p) for p,record in self.app.identity.trusted.items()]
        if self.app.remote_config:choices.append(('Старая пара · PIN','legacy'))
        if not choices:return error(self,'Нет подключённых устройств')
        names=[f'{name} · {p[:8]}' for name,p in choices]
        selected,ok=QInputDialog.getItem(self,'Переслать сообщение','Получатель:',names,0,False)
        if not ok:return
        peer=choices[names.index(selected)][1]
        payload=dict(content);payload.pop('reply_to',None)
        if payload.get('kind')=='text':payload['origin']='chat'
        if self.app.send_to_peer(peer,payload):self.app.toast.pop('Пересылаем выбранному устройству…')
        else:error(self,'Не удалось выбрать подключённое устройство')

    def show_delivery_queue(self):
        rows=self.app.delivery_outbox.list()
        if not rows:
            return QMessageBox.information(self,'Очередь доставки',
                'Недоставленных текстовых сообщений нет.')
        names=[]
        for item in rows:
            target=self.app.identity.trusted.get(item['peer'],{}).get('name','Другая пара')
            state=('Ожидает подтверждения' if item['state']=='awaiting_receipt'
                   else 'Ожидает отправки')
            names.append(f"{target} · {state} · попыток: {item['attempts']} · {item['id'][:8]}")
        choice,ok=QInputDialog.getItem(self,'Очередь доставки',
            'Выбери сообщение. Отмена удаляет его только из исходящей очереди:',
            names,0,False)
        if not ok:return
        item=rows[names.index(choice)]
        if QMessageBox.question(self,'Отмена доставки',
            'Удалить выбранную недоставленную отправку из очереди?')==QMessageBox.Yes:
            self.app.delivery_outbox.cancel(item['id'])
            self.update_delivery_count()

    def update_delivery_count(self):
        count=self.app.delivery_outbox.pending_count()
        self.delivery_button.setText(f'Очередь · {count}')

    def send_text(self):
        text=self.compose.toPlainText().strip()
        if not text:return
        if not self.app.active_channel()[0]:return error(self,'Выбери подключённое устройство')
        payload={'kind':'text','text':text,'origin':'chat'}
        if self.reply_to:payload['reply_to']=self.reply_to.copy()
        if self.app.send_to_active(payload):
            self.compose.clear();self.cancel_reply()

    def send_clipboard(self):
        value=self.app.clipboard.text()
        if not value:return error(self,'Буфер пуст')
        if not self.app.active_channel()[0]:return error(self,'Выбери получателя')
        self.app.send_to_active({'kind':'text','text':value,'origin':'clipboard'})

    def send_file(self):
        file,_=QFileDialog.getOpenFileName(self,'Отправить файл (до 40 МБ)')
        if file:self.send_files([file])

    def send_files(self,paths):
        if self.app.offline:return error(self,'В настройках включён режим оффлайн')
        if not self.app.active_channel()[0]:return error(self,'Сначала выбери получателя')
        valid,rejected=validate_dropped_files(paths)
        if not valid:
            return error(self,'Нет подходящих файлов. Максимальный размер каждого — 40 МБ.')
        review=FileReviewDialog(valid,rejected,self)
        if review.exec()!=QDialog.Accepted:
            return
        sent=0
        for file,_ in valid:
            try:
                # Revalidate after confirmation, before reading changed files.
                if not file.is_file() or file.stat().st_size>MAX_FILE_SIZE:
                    error(self,f'«{file.name}»: файл изменён или слишком велик')
                    continue
                # Never read the entire 40 MiB into Qt's UI thread.
                size=file.stat().st_size
                if size>LEGACY_FILE_SIZE:
                    raw=None
                else:
                    raw=file.read_bytes()
                    if len(raw)>MAX_FILE_SIZE:continue
            except OSError as exc:
                error(self,f'Не удалось прочитать «{file.name}»: {exc}')
                continue
            if size>LEGACY_FILE_SIZE:
                try:
                    self.app.send_large_file(file)
                    ok=True
                except (OSError,ValueError) as exc:
                    error(self,'Не удалось отправить большой файл: '+str(exc))
                    ok=False
            else:
                ok=self.app.send_to_active({
                    'kind':'file','origin':'clipboard','name':file.name,
                    'bytes':base64.b64encode(raw).decode('ascii')})
            if not ok:break
            sent+=1
        if sent:self.app.toast.pop(f'Отправлено в очередь передачи: {sent}')

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:super().dragEnterEvent(event)

    def dragMoveEvent(self,event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:super().dragMoveEvent(event)

    def dropEvent(self,event):
        if event.mimeData().hasUrls():
            paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.send_files(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)






class OnlineWindow(QWidget):
    """Read-only live online roster with identities and current connection status."""
    def __init__(self,app):
        super().__init__(None)
        self.app=app
        self.setWindowTitle('ORBITclip · Устройства онлайн')
        self.setWindowIcon(QIcon(str(ASSETS/'orbit_icon.png')))
        self.resize(495,455)
        layout=QVBoxLayout(self);layout.setContentsMargins(17,17,17,17);layout.setSpacing(10)
        self.header=QLabel('Устройства онлайн');self.header.setObjectName('heading');layout.addWidget(self.header)
        self.me=QLabel();self.me.setWordWrap(True);layout.addWidget(self.me)
        self.status=label('Обновляется каждые 10 секунд');layout.addWidget(self.status)
        self.list=QListWidget();self.list.setMinimumHeight(210);layout.addWidget(self.list,1)
        self.info=label('');self.info.setWordWrap(True);layout.addWidget(self.info)
        bar=QHBoxLayout();layout.addLayout(bar)
        bar.addWidget(action('Обновить',self.refresh,icon_name='history'))
        bar.addWidget(action('Запросить пару',self.request_selected,primary=True))
        bar.addWidget(action('Открыть связь',self.app.open_chat));bar.addStretch()
        self.refresh()

    def refresh(self):
        device=self.app.identity
        self.me.setText('Мой клиент: '+device.name+' · '+device.id[:12]+' · v'+QT_CLIENT_VERSION)
        selected=self.list.currentItem()
        keep=selected.data(Qt.UserRole) if selected else None
        self.list.clear()
        records=sorted(self.app.online_devices,key=lambda p:p.get('name','').casefold())
        for p in records:
            uid=p.get('id','')
            is_trusted=uid in device.trusted
            name=p.get('name') or 'Без имени'
            text='●  '+name+'    ·  '+uid[:12]+'    ·  v'+str(p.get('version','?'))
            text+='    ✓ Связано' if is_trusted else '    Не сопряжено'
            item=QListWidgetItem(text);item.setData(Qt.UserRole,uid)
            item.setIcon(icon('remote'));self.list.addItem(item)
            if keep==uid:self.list.setCurrentItem(item)
        self.status.setText('Онлайн: '+str(len(records))+' · '+self.app.network_status)
        if records:
            self.info.setText('Отображаются устройства с тем же токеном сервера. Адрес IP не является идентификатором.')
        else:
            self.info.setText('Пока нет других клиентов. Устройства должны быть запущены и авторизованы на одном сервере. Пустой список возможен при старой версии сервера.')

    def request_selected(self):
        if self.app.offline:return error(self,'Выключи режим оффлайн в настройках')
        item=self.list.currentItem()
        if item is None:return error(self,'Выбери устройство в списке.')
        peer_id=item.data(Qt.UserRole)
        if peer_id in self.app.identity.trusted:return error(self,'Пара с этим устройством уже установлена.')
        self.app.directory.request(peer_id)
        self.info.setText('Запрос отправляется…')

class LocalWheelFilter(QObject):
    """Ctrl+wheel fallback for focused ORBITclip windows without system permissions."""
    def __init__(self,app):
        super().__init__();self.app=app

    def eventFilter(self,obj,event):
        if (event.type()==QEvent.Wheel and event.modifiers() & Qt.ControlModifier
                and (self.app.wheel_activation_mode == 'wheel' or self.app.wheel._selected)):
            # Do not echo events consumed by the native hook.
            if time.monotonic()-self.app.wheel.last_move>0.09:
                dy=event.angleDelta().y() / 120.0
                if not dy:
                    dy=event.pixelDelta().y()/50.0
                if dy:self.app.wheel.local_scroll(dy)
            return True
        if event.type()==QEvent.KeyRelease and event.key()==Qt.Key_Control:
            with self.app.wheel._lock:self.app.wheel._commit_locked()
        return super().eventFilter(obj,event)


class PreferencesWindow(QWidget):
    """Connectivity and clipboard selector preferences, persisted locally."""
    def __init__(self,app):
        super().__init__(None)
        self.app=app
        self.setWindowTitle('ORBITclip · Настройки · v'+CLIENT_VERSION)
        self.setWindowIcon(QIcon(str(ASSETS/'orbit_icon.png')))
        self.setMinimumWidth(450)
        self.resize(565,655)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8,8,8,8)
        content_scroll = QScrollArea(self)
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.NoFrame)
        content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QWidget()
        lay=QVBoxLayout(panel);lay.setContentsMargins(18,16,18,18);lay.setSpacing(11)
        content_scroll.setWidget(panel)
        outer.addWidget(content_scroll)
        heading=QLabel('Настройки');heading.setObjectName('heading')
        lay.addWidget(heading)
        lay.addWidget(label('ORBITclip v'+CLIENT_VERSION+' · протокол '+str(__import__('orbit_version').PROTOCOL_VERSION)))
        self.offline=QCheckBox('Быть оффлайн')
        self.offline.setChecked(app.offline)
        lay.addWidget(self.offline)
        off_info=label('Отключить обмен с сервером, поиск устройств, запросы пар и фоновый пинг.')
        off_info.setWordWrap(True)
        lay.addWidget(off_info)
        self.paste=QCheckBox('Сразу вставлять')
        self.paste.setChecked(app.paste_on_release)
        lay.addWidget(self.paste)
        paste_info=label('Когда отпускаешь Ctrl после выбора через колесо: скопировать и вставить в активное приложение (Ctrl+V / Cmd+V).')
        paste_info.setWordWrap(True)
        lay.addWidget(paste_info)
        lay.addWidget(label('Цветовая тема'))
        self.themes=OrbitSelect()
        for key,item in THEMES.items():self.themes.addItem(item['name'],key)
        self.themes.setCurrentIndex(max(0,self.themes.findData(app.appearance_theme)))
        lay.addWidget(self.themes)
        self.themes.currentIndexChanged.connect(lambda *_:app.set_theme(self.themes.currentData()))
        lay.addWidget(label('Способ вызова истории буфера'))
        self.activation=OrbitSelect()
        self.activation.addItem('Ctrl + колесо', 'wheel')
        self.activation.addItem('Удерживать Ctrl → однократно Alt', 'ctrl_alt')
        self.activation.setCurrentIndex(max(0,self.activation.findData(app.wheel_activation_mode)))
        self.activation.currentIndexChanged.connect(
            lambda *_: app.set_wheel_activation_mode(self.activation.currentData()))
        lay.addWidget(self.activation)
        lay.addWidget(label('Представление истории буфера'))
        self.wheel_view=OrbitSelect();self.wheel_view.addItem('Компактное окно','compact')
        self.wheel_view.addItem('Объёмный барабан · плавное вращение','drum')
        self.wheel_view.setCurrentIndex(1 if app.wheel_view=='drum' else 0)
        lay.addWidget(self.wheel_view)
        self.wheel_view.currentIndexChanged.connect(lambda *_:app.set_wheel_view(self.wheel_view.currentData()))
        lay.addWidget(label('Материал барабана'))
        self.drum_skin=OrbitSelect()
        for key,entry in DRUM_STYLES.items():
            self.drum_skin.addItem(entry['name'],key)
        self.drum_skin.setCurrentIndex(max(0,self.drum_skin.findData(app.drum_style)))
        self.drum_skin.setEnabled(app.wheel_view=='drum')
        lay.addWidget(self.drum_skin)
        self.drum_skin.currentIndexChanged.connect(
            lambda *_:app.set_drum_style(self.drum_skin.currentData()))
        self.wheel_view.currentIndexChanged.connect(
            lambda *_:self.drum_skin.setEnabled(self.wheel_view.currentData()=='drum'))
        self.drum_motion=QCheckBox('Анимировать смену категорий')
        self.drum_motion.setChecked(app.animate_drum_categories)
        self.drum_motion.setEnabled(app.wheel_view=='drum')
        self.drum_motion.toggled.connect(app.set_animate_drum_categories)
        self.wheel_view.currentIndexChanged.connect(
            lambda *_:self.drum_motion.setEnabled(self.wheel_view.currentData()=='drum'))
        lay.addWidget(self.drum_motion)
        lay.addWidget(label('Компоновка барабана'))
        self.drum_shape=OrbitSelect()
        for key,(name,dimensions) in SHAPES.items():
            self.drum_shape.addItem(f'{name} · {dimensions[0]}×{dimensions[1]}',key)
        self.drum_shape.setCurrentIndex(max(0,self.drum_shape.findData(app.drum_options['shape'])))
        lay.addWidget(self.drum_shape)
        self.drum_shape.currentIndexChanged.connect(
            lambda *_:app.set_drum_option('shape',self.drum_shape.currentData()))
        lay.addWidget(label('Где показывать барабан'))
        self.drum_position=OrbitSelect()
        for key,name in POSITIONS.items():self.drum_position.addItem(name,key)
        self.drum_position.setCurrentIndex(max(0,self.drum_position.findData(app.drum_options['position'])))
        lay.addWidget(self.drum_position)
        self.drum_position.currentIndexChanged.connect(
            lambda *_:app.set_drum_option('position',self.drum_position.currentData()))
        lay.addWidget(label('Заголовок'))
        header_row=QHBoxLayout()
        self.drum_header=OrbitSelect()
        for key,name in HEADERS.items():self.drum_header.addItem(name,key)
        self.drum_header.setCurrentIndex(max(0,self.drum_header.findData(app.drum_options['header'])))
        self.drum_header.currentIndexChanged.connect(
            lambda *_:app.set_drum_option('header',self.drum_header.currentData()))
        header_row.addWidget(self.drum_header,2)
        self.drum_header_place=OrbitSelect()
        for key,name in HEADER_POSITIONS.items():self.drum_header_place.addItem(name,key)
        self.drum_header_place.setCurrentIndex(max(0,self.drum_header_place.findData(app.drum_options['header_position'])))
        self.drum_header_place.currentIndexChanged.connect(
            lambda *_:app.set_drum_option('header_position',self.drum_header_place.currentData()))
        header_row.addWidget(self.drum_header_place,1)
        lay.addLayout(header_row)
        self.drum_index=QCheckBox('Показывать позицию записи (3 / 12)')
        self.drum_index.setChecked(app.drum_options['show_index'])
        self.drum_index.toggled.connect(lambda x:app.set_drum_option('show_index',x))
        lay.addWidget(self.drum_index)

        self.drum_sliders=[]
        self.drum_sliders_by_key={}
        def drum_slider(caption,key,low,high,suffix=''):
            line=QHBoxLayout()
            label_text=QLabel(caption)
            label_text.setMinimumWidth(160)
            line.addWidget(label_text)
            slider=QSlider(Qt.Horizontal)
            slider.setRange(low,high)
            slider.setValue(app.drum_options[key])
            line.addWidget(slider,1)
            value=QLabel(str(slider.value())+suffix)
            value.setMinimumWidth(42)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            line.addWidget(value)
            slider.valueChanged.connect(
                lambda n,k=key,v=value,unit=suffix:(v.setText(str(n)+unit),app.set_drum_option(k,n)))
            lay.addLayout(line)
            self.drum_sliders.append(slider)
            self.drum_sliders_by_key[key]=(slider,value,suffix)
        drum_slider('Прозрачность барабана','opacity',35,100,'%')
        drum_slider('Видимость соседей','neighbor_opacity',5,100,'%')
        drum_slider('Боковой отступ соседей','neighbor_gap',0,65,' px')
        drum_slider('Соседей с каждой стороны','neighbors',1,4)
        self.drum_controls=[self.drum_shape,self.drum_position,self.drum_header,
                            self.drum_header_place,self.drum_index,*self.drum_sliders]
        def sync_drum_controls(*_):
            active=self.wheel_view.currentData()=='drum'
            for widget in self.drum_controls:widget.setEnabled(active)
        self.wheel_view.currentIndexChanged.connect(sync_drum_controls)
        sync_drum_controls()
        lay.addWidget(label('Визуальная настройка барабана'))
        self.drum_live=DrumLivePreview(app,self)
        lay.addWidget(self.drum_live)
        preview_buttons=QHBoxLayout()
        preview_buttons.addWidget(action('Вернуть настройки барабана',self.reset_drum_settings))
        preview_buttons.addStretch(1)
        lay.addLayout(preview_buttons)
        lay.addWidget(label('Приватность буфера'))
        self.exclusions=QLineEdit(', '.join(app.excluded_apps))
        self.exclusions.setPlaceholderText('Приложения: 1Password, KeePassXC, …')
        self.exclusions.setToolTip('Точные названия процессов на Windows или приложений на macOS; через запятую')
        lay.addWidget(self.exclusions)
        lay.addWidget(action('Сохранить исключения',lambda:app.set_excluded_apps(self.exclusions.text())))
        row_private=QHBoxLayout()
        for minutes in (5,15,60):
            row_private.addWidget(action(f'Пауза {minutes} мин',lambda checked=False,n=minutes:app.pause_capture_for(n)))
        lay.addLayout(row_private)
        lay.addWidget(action('Снять временную паузу',lambda:app.pause_capture_for(0)))
        self.hide_clock=None
        if platform.system() in ('Windows','Darwin'):
            self.hide_clock=QCheckBox('Скрывать виджет часов (оставить системные значки)')
            self.hide_clock.setChecked(app.hide_clock_windows)
            lay.addWidget(self.hide_clock)
            info=label('История, переписка и настройки остаются доступны из системного трея Windows или верхней панели macOS.')
            info.setWordWrap(True)
            lay.addWidget(info)
            self.hide_clock.toggled.connect(app.set_clock_hidden_windows)
        shortcuts=QHBoxLayout()
        shortcuts.addWidget(action('Уведомления…',app.open_notification_center))
        shortcuts.addWidget(action('Моя аналитика…',app.open_analytics))
        shortcuts.addWidget(action('Обновления…',app.open_updates))
        lay.addLayout(shortcuts)
        self.status=label('')
        lay.addWidget(self.status)
        row=QHBoxLayout();row.addStretch()
        row.addWidget(action('Готово',self.close,primary=True))
        lay.addLayout(row)
        self.offline.toggled.connect(app.set_offline)
        self.paste.toggled.connect(app.set_paste_on_release)
        self.refresh_status()

    def refresh_drum_preview(self):
        if hasattr(self,'drum_live'):
            self.drum_live.repaint_example()

    def reset_drum_settings(self):
        from orbit_drum_styles import normalize_drum_style
        from orbit_drum_layout import DEFAULTS
        self.app.drum_options=dict(DEFAULTS)
        self.app.set_drum_style('minimal')
        if isinstance(self.app.bubble,DrumBubble):
            self.app.bubble.set_options(self.app.drum_options)
        self.drum_shape.blockSignals(True)
        self.drum_shape.setCurrentIndex(self.drum_shape.findData(DEFAULTS['shape']))
        self.drum_shape.blockSignals(False)
        self.drum_position.blockSignals(True)
        self.drum_position.setCurrentIndex(self.drum_position.findData(DEFAULTS['position']))
        self.drum_position.blockSignals(False)
        self.drum_header.blockSignals(True)
        self.drum_header.setCurrentIndex(self.drum_header.findData(DEFAULTS['header']))
        self.drum_header.blockSignals(False)
        self.drum_header_place.blockSignals(True)
        self.drum_header_place.setCurrentIndex(self.drum_header_place.findData(DEFAULTS['header_position']))
        self.drum_header_place.blockSignals(False)
        self.drum_index.blockSignals(True)
        self.drum_index.setChecked(DEFAULTS['show_index'])
        self.drum_index.blockSignals(False)
        self.drum_skin.blockSignals(True)
        self.drum_skin.setCurrentIndex(self.drum_skin.findData('minimal'))
        self.drum_skin.blockSignals(False)
        for key,(slider,value,suffix) in self.drum_sliders_by_key.items():
            slider.blockSignals(True)
            slider.setValue(DEFAULTS[key])
            slider.blockSignals(False)
            value.setText(str(DEFAULTS[key])+suffix)
        self.app.save_settings()
        self.refresh_drum_preview()

    def refresh_status(self):
        network='Сеть отключена' if self.app.offline else 'Сеть включена'
        remaining=max(0,round((self.app.private_until-time.monotonic())/60))
        self.status.setText(network+(f' · Буфер на паузе ~{remaining} мин' if remaining else ''))

class OrbitApp:
    def __init__(self):
        self.qt=QApplication.instance() or QApplication(sys.argv)
        self.qt.setApplicationName(APP_NAME)
        self.qt.setWindowIcon(QIcon(str(ASSETS/'orbit_icon.png')))
        self.qt.setQuitOnLastWindowClosed(False)
        self.settings=read_settings()
        self.appearance_theme=normalize_theme(self.settings.get('appearance_theme','midnight'))
        self.palette=palette(self.appearance_theme)
        self.qt.setProperty('orbit_theme',self.appearance_theme)
        self.qt.setStyleSheet(stylesheet(STYLE,self.appearance_theme))
        self.notifications=NotificationStore()
        self.analytics=AnalyticsStore(enabled=self.settings.get('analytics_enabled',True))
        self.hide_clock_windows=bool(self.settings.get('hide_clock_windows',False)) if platform.system() in ('Windows','Darwin') else False
        self.tray_icon=None;self.tray_menu=None;self.tray_clock_action=None;self.chat_status_icon=None
        self._popup_notification=None
        self.offline=bool(self.settings.get('offline_mode',False))
        self.paste_on_release=bool(self.settings.get('paste_on_release',False))
        self.excluded_apps=normalize_exclusions(self.settings.get('excluded_apps',[]))
        self.private_until=0.0
        self.paste_queue=PasteQueue()
        self.queue_presets=QueuePresets()
        self.queue_wheel_mode=False
        self.queue_window=None
        self.vault=ClipboardVault()
        self.categories=CategoryModel(self.settings.get('orbit_categories'))
        self.categories.normalize_item_categories(self.vault)
        self.store=MessageStore()
        self.delivery_outbox=DurableOutbox()
        self.delivery_capabilities={}
        self.delivery_probe_at={}
        self.attachment_errors=[]
        self.file_sender=FileSender()
        receive_root=QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        self.file_receiver=FileReceiver((Path(receive_root) if receive_root else Path.home()/'Downloads')/'ORBITclip')
        self.url,self.token=resolve_connection_settings(self.settings,ROOT/'client_defaults.json',DEFAULT_RELAY_URL)
        self.tls_pin=str(self.settings.get('https_tls_pin') or self.settings.get('remote_tls_pin') or '')
        self.remote_pair=str(self.settings.get('remote_pair') or self.settings.get('https_pair') or '')
        self.device=str(self.settings.get('remote_device') or secrets.token_hex(16))
        self.identity=DeviceIdentity()
        self.workspaces=Workspaces(self.identity)
        self.ensure_nickname()
        self.selected_peer=str(self.settings.get('selected_peer',''))
        self.peer_bridges={}
        self.peer_cursors=self.settings.get('peer_cursors',{}) if isinstance(self.settings.get('peer_cursors'),dict) else {}
        self.online_devices=[]
        self.directory=PeerDirectory(self.identity,self.directory_config,QT_CLIENT_VERSION)
        self.cursor=int(self.settings.get('remote_cursor',0) or 0)
        self.cursor_place=str(self.settings.get('remote_cursor_place',''))
        self.remote_config=None
        self.pair_role='';self.pair_invite='';self.pair_bridge=PairingBridge()
        self.pair_bridge.set_online(not self.offline)
        self.bridge=RemoteBridge()
        self.bridge.set_online(not self.offline)
        self.hotkeys=Hotkeys();self.wheel=ClipboardWheel()
        self.flow_hotkeys=FlowShortcuts()
        self.flow_hotkeys.start()
        self.wheel_activation_mode=str(self.settings.get('wheel_activation_mode','wheel'))
        self.wheel.set_activation_mode(self.wheel_activation_mode)
        self.hotkeys.configure(self.vault.items)
        self.wheel.start()
        self.local_wheel_filter=LocalWheelFilter(self)
        self.qt.installEventFilter(self.local_wheel_filter)
        self.paused=bool(self.settings.get('recording_paused',False))
        self.wheel_limit=max(1,min(100,int(self.settings.get('wheel_limit',20))))
        self.priority_limit=max(0,min(self.wheel_limit,int(self.settings.get('wheel_priority_limit',5))))
        self.wheel_queue=WheelQueue(self.settings.get('wheel_manual_by_category') or self.settings.get('wheel_manual_order'),self.wheel_limit)
        self.switch_categories=[(c['id'],c['name']) for c in self.categories.wheel_categories()]
        self.switch_category=0;self.switch_index=0;self.switch_active=False
        self._last_clip=''
        self.clipboard=self.qt.clipboard();self.clipboard.dataChanged.connect(self.on_clipboard)
        self.toast=FloatingToast()
        self._last_update_status=consume_status()
        if self._last_update_status:
            # The previous 7.7.0 updater had no journal yet. Record its first
            # upgrade result on launch, but do not duplicate newer entries.
            try:
                previous=read_history(1)
                status_event='success' if self._last_update_status.get('ok') else 'failure'
                if not previous or previous[-1].get('event')!=status_event:
                    log_update(status_event,
                               'Предыдущее обновление завершено' if status_event=='success'
                               else 'Предыдущее обновление завершилось с ошибкой')
            except OSError:
                pass
        self.wheel_view=str(self.settings.get('wheel_view','compact'))
        self.drum_style=normalize_drum_style(self.settings.get('drum_style','minimal'))
        self.drum_options=normalize_drum_options(self.settings.get('drum_options'))
        self.animate_drum_categories=bool(self.settings.get('animate_drum_categories',True))
        self.bubble=DrumBubble(self) if self.wheel_view=='drum' else ScrollBubble()
        self.flow_palette=None
        self.history=None;self.chat=None;self.online_window=None;self.preferences=None;self.update_window=None;self.workspace_window=None;self.sql_explorer=None;self.capture_window=None;self.screenshot_editor=None;self.notification_window=None;self.analytics_window=None
        self.tour_seen=bool(self.settings.get('tour_seen',False))
        raw_unread=self.settings.get('unread_peers',{})
        self.unread_peers={str(k):max(0,int(v)) for k,v in raw_unread.items() if isinstance(k,str) and isinstance(v,int) and not isinstance(v,bool)} if isinstance(raw_unread,dict) else {}
        self.clock=OrbitPill(self)
        self.clock.setToolTip('ORBITclip v'+CLIENT_VERSION)
        if platform.system()=='Windows':
            self.create_windows_tray()
        elif platform.system()=='Darwin':
            self.create_macos_status_icons()
        if not self.hide_clock_windows or self.tray_icon is None:
            self.clock.show()
        if platform.system()=='Darwin' and not self.wheel.backend.startswith('macOS CoreGraphics'):
            QTimer.singleShot(1400,lambda:self.toast.pop(
                'Глобальная прокрутка не активна. Разреши Python/Terminal: Мониторинг ввода и Универсальный доступ.'))
        self.network_status='○ Оффлайн' if self.offline else '● Сервер не проверен';self.server_version='?'
        self.last_network_error=''
        self.keepalive_events=queue.Queue();self.keepalive_stop=threading.Event()
        self.keepalive_thread=threading.Thread(target=self.keepalive,daemon=True,name='orbit-qt-heartbeat')
        self.keepalive_thread.start()
        self.events=QTimer();self.events.timeout.connect(self.pump_events);self.events.start(130)
        self.qt.applicationStateChanged.connect(self.on_application_state)
        self.restore_remote()
        self.start_peer_bridges()
        self.save_settings()
        if self._last_update_status:
            result=self._last_update_status
            QTimer.singleShot(1300,lambda:self.toast.pop(result['message']))

    def ensure_nickname(self):
        if self.identity.name_confirmed and self.identity.name.strip():
            return
        while True:
            nick,ok=QInputDialog.getText(
                None,'ORBITclip · Имя устройства',
                'Как назвать этот компьютер? Псевдоним обязателен для онлайн-каталога.\n'
                'Например: Рабочий ПК или MacBook:',text=self.identity.name)
            if not ok:
                raise SystemExit('Для работы ORBITclip укажи псевдоним устройства.')
            try:
                self.identity.rename(nick)
                break
            except ValueError as exc:
                QMessageBox.warning(None,'Псевдоним обязателен',str(exc))

    def set_wheel_activation_mode(self, mode):
        self.wheel_activation_mode='ctrl_alt' if mode=='ctrl_alt' else 'wheel'
        self.wheel.set_activation_mode(self.wheel_activation_mode)
        self.settings['wheel_activation_mode']=self.wheel_activation_mode
        self.save_settings()

    def set_wheel_view(self, mode):
        mode='drum' if mode=='drum' else 'compact'
        if self.wheel_view==mode:return
        self.bubble.hide();self.bubble.deleteLater()
        self.wheel_view=mode
        self.bubble=DrumBubble(self) if mode=='drum' else ScrollBubble()
        self.settings['wheel_view']=mode;self.save_settings()

    def set_drum_option(self,key,value):
        updated=dict(self.drum_options)
        updated[key]=value
        validated=normalize_drum_options(updated)
        if validated==self.drum_options:return
        self.drum_options=validated
        if isinstance(self.bubble,DrumBubble):
            self.bubble.set_options(validated)
        self.save_settings()
        if self.preferences:self.preferences.refresh_drum_preview()

    def set_drum_style(self,style):
        value=normalize_drum_style(style)
        if self.drum_style==value:return
        self.drum_style=value
        if isinstance(self.bubble,DrumBubble):self.bubble.set_style(value)
        self.save_settings()
        if self.preferences:self.preferences.refresh_drum_preview()

    def set_animate_drum_categories(self,enabled):
        self.animate_drum_categories=bool(enabled)
        if isinstance(self.bubble,DrumBubble):
            self.bubble.set_category_animation(self.animate_drum_categories)
        self.save_settings()

    def set_theme(self,theme):
        value=normalize_theme(theme)
        if self.appearance_theme==value:return
        self.appearance_theme=value
        self.palette=palette(value)
        self.qt.setProperty('orbit_theme',value)
        self.qt.setStyleSheet(stylesheet(STYLE,value))
        for widget in self.qt.allWidgets():
            if isinstance(widget,OrbitSelect):widget.set_theme(value)
        if isinstance(self.bubble,DrumBubble):self.bubble.update()
        if self.preferences:self.preferences.refresh_drum_preview()
        if self.chat:
            self.chat.apply_theme()
            if self.chat.isVisible() and self.chat.pages.currentIndex()==0:
                self.chat.refresh_messages()
        self.settings['appearance_theme']=value
        self.save_settings()
        self.clock.update()
        if self.analytics_window:self.analytics_window.chart.update()

    def create_macos_status_icons(self):
        """Two dedicated icons in the macOS menu bar: clipboard and messenger."""
        if platform.system()!='Darwin' or not QSystemTrayIcon.isSystemTrayAvailable():
            self.hide_clock_windows=False
            return
        history=QSystemTrayIcon(self.qt)
        history.setIcon(icon('clipboard'))
        history.setToolTip('ORBITclip · Буфер обмена')
        hm=QMenu()
        hm.addAction('Открыть историю',lambda checked=False:self.open_history())
        hm.addAction('⌕ Быстрый поиск',lambda checked=False:self.open_palette())
        hm.addAction('Вставить следующий',lambda checked=False:self.paste_next_from_queue())
        hm.addAction('Очередь вставки…',lambda checked=False:self.open_queue())
        hm.addAction('Пространства',lambda checked=False:self.open_workspaces())
        hm.addAction('Уведомления',lambda checked=False:self.open_notification_center())
        hm.addAction('Моя аналитика',lambda checked=False:self.open_analytics())
        hm.addSeparator()
        hm.addAction('Настройки…',lambda checked=False:self.open_settings())
        hm.addAction('Обновления…',lambda checked=False:self.open_updates())
        self.tray_clock_action=hm.addAction('Скрыть виджет часов',lambda checked=False:self.set_clock_hidden_windows(not self.hide_clock_windows))
        hm.addSeparator()
        hm.addAction('Завершить ORBITclip',lambda checked=False:self.shutdown())
        history.setContextMenu(hm)
        history.activated.connect(lambda reason:self.open_history() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        history.show()
        if hasattr(history,'messageClicked'):history.messageClicked.connect(self.open_popup_notification)
        self.tray_icon=history;self.tray_menu=hm
        messenger=QSystemTrayIcon(self.qt)
        messenger.setIcon(icon('send'))
        messenger.setToolTip('ORBITclip · Переписка')
        cm=QMenu()
        cm.addAction('Открыть мессенджер',lambda checked=False:self.open_chat())
        cm.addAction('Непрочитанные уведомления',lambda checked=False:self.open_notification_center())
        cm.addAction('Устройства онлайн',lambda checked=False:self.open_online())
        messenger.setContextMenu(cm)
        messenger.activated.connect(lambda reason:self.open_chat() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        messenger.show()
        self.chat_status_icon=messenger
        self.refresh_tray_menu()

    def update_notification_badge(self):
        n=self.notifications.unread()
        if self.tray_icon:self.tray_icon.setToolTip(f'ORBITclip · {n} непрочитанных' if n else 'ORBITclip · Буфер обмена')
        if self.chat_status_icon:self.chat_status_icon.setToolTip(f'ORBITclip · {n} уведомлений' if n else 'ORBITclip · Переписка')
        # The inbox controls its own selection; avoid resetting it mid-click.

    def notify(self,kind,title,description='',target='',dedupe='',show_popup=True):
        item=self.notifications.push(kind,title,description,target,dedupe)
        if item is None:return
        self.update_notification_badge()
        if self.notification_window and self.notification_window.isVisible():self.notification_window.refresh()
        # QSystemTrayIcon requests native notifications; fallback only if absent.
        if not show_popup:return
        if (self.tray_icon is not None and QSystemTrayIcon.supportsMessages()):
            self._popup_notification=(kind,target,item)
            self.tray_icon.showMessage(title,description or title,QSystemTrayIcon.Information,5000)
        else:
            self.toast.pop(title if not description else title+' · '+description)

    def open_popup_notification(self):
        pending=self._popup_notification
        self._popup_notification=None
        if pending is None:
            self.open_notification_center()
            return
        kind,target,identifier=pending
        self.notifications.mark_read(identifier)
        self.update_notification_badge()
        if kind=='messages':
            if target in self.identity.trusted:
                self.selected_peer=target
            self.open_chat()
        elif kind in ('files','spaces'):
            self.open_workspaces()
        else:
            self.open_notification_center()

    def open_notification_center(self):
        if self.notification_window is None:self.notification_window=NotificationCenterWindow(self)
        self.notification_window.refresh()
        self.notification_window.show();self.notification_window.raise_();self.notification_window.activateWindow()
        self.analytics.record('notification_open')

    def open_analytics(self):
        if self.analytics_window is None:self.analytics_window=AnalyticsWindow(self)
        self.analytics_window.refresh()
        self.analytics_window.show();self.analytics_window.raise_();self.analytics_window.activateWindow()

    def open_updates(self):
        if self.update_window is None:
            self.update_window=UpdateWindow(self)
        self.update_window.show()
        self.update_window.raise_()
        self.update_window.activateWindow()

    def open_settings(self):
        if self.preferences is None:self.preferences=PreferencesWindow(self)
        self.preferences.exclusions.setText(', '.join(self.excluded_apps))
        self.preferences.offline.blockSignals(True)
        self.preferences.paste.blockSignals(True)
        self.preferences.offline.setChecked(self.offline)
        self.preferences.paste.setChecked(self.paste_on_release)
        self.preferences.offline.blockSignals(False)
        self.preferences.paste.blockSignals(False)
        if self.preferences.hide_clock is not None:
            self.preferences.hide_clock.blockSignals(True)
            self.preferences.hide_clock.setChecked(self.hide_clock_windows)
            self.preferences.hide_clock.blockSignals(False)
        self.preferences.refresh_status()
        self.preferences.refresh_drum_preview()
        self.preferences.show();self.preferences.raise_();self.preferences.activateWindow()

    def create_windows_tray(self):
        """Keep the application reachable when the floating clock is hidden."""
        if platform.system()!='Windows':return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            # Explorer/shell has no notification area: never strand the client.
            self.hide_clock_windows=False
            return
        tray=QSystemTrayIcon(self.qt)
        tray.setIcon(QIcon(str(ASSETS/'orbit_icon.png')))
        tray.setToolTip('ORBITclip · История и обмен')
        menu=QMenu()
        menu.addAction('История буфера',lambda checked=False:self.open_history())
        menu.addAction('⌕ Быстрый поиск',lambda checked=False:self.open_palette())
        menu.addAction('Вставить следующий',lambda checked=False:self.paste_next_from_queue())
        menu.addAction('Очередь вставки…',lambda checked=False:self.open_queue())
        menu.addAction('Переписка',lambda checked=False:self.open_chat())
        menu.addAction('Устройства онлайн',lambda checked=False:self.open_online())
        menu.addAction('Общие пространства',lambda checked=False:self.open_workspaces())
        menu.addAction('Уведомления',lambda checked=False:self.open_notification_center())
        menu.addAction('Моя аналитика',lambda checked=False:self.open_analytics())
        menu.addSeparator()
        menu.addAction('SQL Explorer…',lambda checked=False:self.open_sql_explorer())
        menu.addAction('Настройки…',lambda checked=False:self.open_settings())
        menu.addAction('Проверить обновления…',lambda checked=False:self.open_updates())
        self.tray_clock_action=menu.addAction('Показать виджет часов',lambda checked=False:self.set_clock_hidden_windows(not self.hide_clock_windows))
        menu.addSeparator()
        menu.addAction('Завершить ORBITclip',lambda checked=False:self.shutdown())
        tray.setContextMenu(menu)
        tray.activated.connect(self.tray_activated)
        if hasattr(tray,'messageClicked'):tray.messageClicked.connect(self.open_popup_notification)
        self.tray_icon=tray;self.tray_menu=menu
        self.refresh_tray_menu()
        tray.show()

    def tray_activated(self,reason):
        if reason==QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_history()

    def refresh_tray_menu(self):
        if self.tray_clock_action is not None:
            self.tray_clock_action.setText('Показать виджет часов' if self.hide_clock_windows else 'Скрыть виджет часов')

    def set_clock_hidden_windows(self,hidden):
        """Windows-only: hide the pill, not the app, clipboard capture or networking."""
        if platform.system() not in ('Windows','Darwin'):return
        hidden=bool(hidden)
        if hidden and (self.tray_icon is None or not QSystemTrayIcon.isSystemTrayAvailable()):
            QMessageBox.warning(self.preferences or self.clock,'ORBITclip · Трей недоступен',
                'Системная область значков недоступна. Виджет часов оставлен видимым, чтобы не потерять доступ к приложению.')
            hidden=False
        self.hide_clock_windows=hidden
        if hidden:
            self.clock.collapse()
            self.clock.hide()
        else:
            self.clock.show()
        self.refresh_tray_menu()
        if self.preferences and self.preferences.hide_clock is not None:
            toggle=self.preferences.hide_clock
            toggle.blockSignals(True);toggle.setChecked(hidden);toggle.blockSignals(False)
        self.save_settings()

    def set_offline(self, offline):
        offline=bool(offline)
        if self.offline==offline:return
        self.offline=offline
        self.bridge.set_online(not offline)
        self.pair_bridge.set_online(not offline)
        for bridge in self.peer_bridges.values():bridge.set_online(not offline)
        if offline:
            self.online_devices=[]
            self.network_status='○ Оффлайн (в настройках)'
            self.server_version='—'
            self.directory.discard_pending()
            if self.online_window:self.online_window.refresh()
            if self.chat:
                self.chat.online.setText(self.network_status)
                self.chat.refresh_online_list([])
                self.chat.connection_hint.setText('Режим оффлайн: отправка и приём отключены')
        else:
            self.network_status='● Проверяем соединение…'
            self.check_server_async()
        self.save_settings()
        self.clock.update()
        if self.preferences:self.preferences.refresh_status()

    def set_paste_on_release(self, enabled):
        self.paste_on_release=bool(enabled)
        self.save_settings()

    def open_online(self):
        if self.online_window is None:self.online_window=OnlineWindow(self)
        self.online_window.refresh()
        self.online_window.show();self.online_window.raise_();self.online_window.activateWindow()

    def save_settings(self):
        self.settings.update(drum_options=self.drum_options,drum_style=self.drum_style,animate_drum_categories=self.animate_drum_categories,wheel_activation_mode=self.wheel_activation_mode,wheel_view=self.wheel_view,appearance_theme=self.appearance_theme,analytics_enabled=self.analytics.enabled,remote_url=self.url,https_url=self.url,remote_token=self.token,https_token=self.token,
                             remote_pair=self.remote_pair,https_pair=self.remote_pair,remote_device=self.device,
                             remote_tls_pin=self.tls_pin,https_tls_pin=self.tls_pin,
                             remote_cursor=self.cursor,remote_cursor_place=self.cursor_place,
                             wheel_limit=self.wheel_limit,wheel_priority_limit=self.priority_limit,recording_paused=self.paused,
                             wheel_manual_order=self.wheel_queue.manual,wheel_manual_by_category=self.wheel_queue.manual_map,orbit_categories=self.categories.categories,
                             selected_peer=self.selected_peer,peer_cursors=self.peer_cursors,
                             offline_mode=self.offline,paste_on_release=self.paste_on_release,
                             excluded_apps=self.excluded_apps,
                             hide_clock_windows=self.hide_clock_windows,unread_peers=self.unread_peers,tour_seen=self.tour_seen)
        private_write(SETTINGS_FILE,self.settings)

    def copy_text(self,value):
        if not value:return
        self.clipboard.setText(str(value));self.add_to_history(str(value),force=True);self.clock.flash()

    def on_clipboard(self):
        if self.paused or time.monotonic() < self.private_until:return
        source=foreground_app()
        if is_excluded(source,self.excluded_apps):return
        try:content=self.clipboard.text()
        except Exception:return
        if content and content != self._last_clip:
            self._last_clip=content;self.vault.add(content,source_app=source);self.clock.flash()
            if self.history and self.history.isVisible():self.history.refresh()
            self.analytics.record('clip_capture',source)
            self.analytics.record_text(content)

    def add_to_history(self,value,force=False):
        if not value or (self.paused and not force):return
        self.vault.add(value,source_app=foreground_app())
        if self.history and self.history.isVisible():self.history.refresh()

    def set_excluded_apps(self,names):
        value=[x.strip() for x in names.split(',')] if isinstance(names,str) else names
        self.excluded_apps=normalize_exclusions(value)
        self.save_settings()
        self.toast.pop(f'Приложений в исключениях: {len(self.excluded_apps)}')

    def pause_capture_for(self,minutes):
        duration=max(0,min(1440,int(minutes)))
        self.private_until=time.monotonic()+duration*60 if duration else 0.0
        self.toast.pop(f'Запись буфера приостановлена на {duration} минут' if duration else 'Запись возобновлена')
        if self.preferences:self.preferences.refresh_status()

    def open_palette(self):
        if self.flow_palette is None:self.flow_palette=CommandPalette(self)
        self.flow_palette.open_palette()

    def open_queue(self):
        if self.queue_window is None:
            self.queue_window=PasteQueueWindow(self)
        self.queue_window.refresh()
        self.queue_window.show()
        self.queue_window.raise_()
        self.queue_window.activateWindow()

    def queue_changed(self):
        if self.queue_window is not None and self.queue_window.isVisible():
            self.queue_window.refresh()
        if self.flow_palette is not None:
            self.flow_palette.refresh()
        # A persistent active wheel mode has no separate source of truth.
        # The next wheel movement uses fresh queue state via candidates().
        if self.switch_active and self.queue_wheel_mode:
            self.draw_bubble()

    def set_queue_wheel_mode(self,enabled):
        enabled=bool(enabled)
        if enabled and self.wheel_view!='drum':
            self.set_wheel_view('drum')
        if enabled==self.queue_wheel_mode:
            return
        self.switch_active=False
        self.bubble.hide()
        self.queue_wheel_mode=enabled
        self.switch_index=0
        self.queue_changed()

    def enqueue_item(self,ident):
        item=self.vault.find(ident)
        if not item or item.get('encrypted'):return
        if self.paste_queue.push(item.get('text',''),
                                 item.get('title') or item.get('kind','Фрагмент'),
                                 source_id=ident):
            self.toast.pop(f'В очереди: {len(self.paste_queue)}')
            self.queue_changed()
        else:self.toast.pop('Очередь заполнена или запись пуста')

    def clear_paste_queue(self):
        self.paste_queue.clear()
        self.queue_changed()
        self.toast.pop('Очередь вставки очищена')

    def paste_next_from_queue(self):
        value=self.paste_queue.pop()
        if value is None:
            self.toast.pop('Очередь вставки пуста')
            return
        self.copy_text(value)
        self.queue_changed()
        QTimer.singleShot(190,lambda:self.try_paste())

    def open_sql_explorer(self):
        # DB connection lives in its independent UI; no database password in settings.
        from orbit_sql_ui import SQLExplorer
        if self.sql_explorer is None:self.sql_explorer=SQLExplorer()
        self.sql_explorer.show();self.sql_explorer.raise_();self.sql_explorer.activateWindow()
        self.analytics.record('sql_open')

    def open_workspaces(self):
        self.analytics.record('space_open')
        if self.workspace_window is None:self.workspace_window=WorkspaceWindow(self)
        self.workspace_window.refresh()
        self.workspace_window.show();self.workspace_window.raise_();self.workspace_window.activateWindow()

    def broadcast_workspace(self,wid,envelope,exclude=None):
        """Hub-and-spoke via pairwise AES-GCM channels; owner relays to member devices."""
        space=self.workspaces.spaces.get(wid)
        if not space:return
        owner=space['owner']
        recipients=self.workspaces.accepted(space)
        if self.identity.id!=owner:
            recipients=[owner] if owner in self.identity.trusted else []
        for pid in recipients:
            if pid!=exclude:self.send_to_peer(pid,envelope)

    def handle_workspace_message(self,peerid,packet):
        body=packet.get('workspace',{})
        if not isinstance(body,dict):return
        wid=body.get('id')
        status=self.workspaces.receive(peerid,packet)
        if status=='ignored':return
        if status=='invite':
            dialog=QMessageBox(QMessageBox.Question,'ORBITclip · Приглашение в пространство',
                f"{self.identity.trusted[peerid]['name']} приглашает тебя в «{body.get('name','Пространство')}».\nПрисоединиться?",
                QMessageBox.Yes|QMessageBox.No,None)
            dialog.setWindowFlag(Qt.WindowStaysOnTopHint,True)
            accepted=dialog.exec()==QMessageBox.Yes
            reply=self.workspaces.decide(wid,accepted)
            self.send_to_peer(peerid,reply)
            self.notify('spaces','Приглашение в пространство',
                        'Принято' if accepted else 'Отклонено',target=wid,dedupe='invite-'+wid)
        elif status=='joined':
            s=self.workspaces.spaces[wid]
            roster=self.workspaces.envelope(wid,'roster',members=s['members'])
            self.broadcast_workspace(wid,roster)
            self.notify('spaces','Новый участник пространства',
                        self.identity.trusted[peerid]['name'],target=wid,dedupe='joined-'+wid+'-'+peerid)
        elif status=='update':
            s=self.workspaces.spaces[wid]
            if s['owner']==self.identity.id and body.get('event') in ('chat','clip'):
                relayed=dict(packet)
                relayed['workspace']=dict(body,relay=True)
                self.broadcast_workspace(wid,relayed,exclude=peerid)
            if body.get('event') in ('chat','clip'):
                event_kind=body.get('event')
                if event_kind=='clip':
                    self.analytics.record('space_clip_in')
                    label='Новая запись в пространстве'
                    # A clipboard publication may be a file reference; no data preview.
                    entry=body.get('entry') or {}
                    kind='files' if entry.get('kind')=='file' else 'spaces'
                else:
                    self.analytics.record('space_chat_in')
                    label='Новое сообщение в пространстве'
                    kind='spaces'
                self.notify(kind,label,s['name'],target=wid,
                            dedupe='space-'+wid+'-'+str((body.get('entry') or {}).get('id','')))
        if self.workspace_window and self.workspace_window.isVisible():self.workspace_window.refresh(wid)
        if self.history and self.history.isVisible() and self.history.space_mode=='shared':self.history.refresh()

    def open_history(self):
        self.analytics.record('history_open')
        if self.history is None:self.history=VaultWindow(self)
        self.history.refresh()
        self.history.show();self.history.raise_();self.history.activateWindow()

    def open_chat(self):
        self.analytics.record('chat_open')
        if self.chat is None:self.chat=ChatWindow(self)
        self.chat.show();self.chat.raise_();self.chat.activateWindow()
        if self.chat.pages.currentIndex()==0:self.chat.mark_conversation_read()

    def open_tour(self):
        # Animated tutorials have been retired; no obsolete GIF assets are loaded.
        return

    def note_incoming(self,peer_id,kind='text'):
        if not peer_id:return
        visible=(self.chat is not None and self.chat.isVisible() and
                 self.chat.pages.currentIndex()==0 and self.selected_peer==peer_id and
                 self.chat.windowState()!=Qt.WindowMinimized)
        if not visible:
            self.unread_peers[peer_id]=min(999,int(self.unread_peers.get(peer_id,0))+1)
            self.save_settings()
        if self.chat:self.chat.refresh_dialog_list()
        self.analytics.record('chat_in')
        title='Получен файл' if kind=='file' else 'Новое сообщение'
        peer=self.identity.trusted.get(peer_id,{}).get('name','Другое устройство')
        self.notify('files' if kind=='file' else 'messages',title,peer,
                    target=peer_id,dedupe='peer-'+str(peer_id)+'-'+str(time.monotonic_ns()//5000000000),show_popup=not visible)

    def clear_unread(self,peer_id):
        if peer_id and self.unread_peers.get(peer_id,0):
            self.unread_peers.pop(peer_id,None)
            self.save_settings()
        if self.chat:self.chat.refresh_dialog_list()

    def on_application_state(self,state):
        if state==Qt.ApplicationInactive:
            # History and messenger are independent normal windows, never auto-hide.
            # Global Ctrl+wheel is intentionally used over OTHER applications.
            # Never hide its selection bubble merely because Qt loses focus.
            if not self.switch_active:self.bubble.hide()
        # Connection/chat stays open by design.

    def wheel_diagnostics(self):
        backend=self.wheel.backend or 'не запущен'
        state='Активен' if self.wheel.enabled else 'Недоступен'
        problem=self.wheel.error or 'Ошибок запуска не зарегистрировано'
        hint=('macOS: Системные настройки → Конфиденциальность и безопасность → '
              'Универсальный доступ и Мониторинг ввода. Разреши Terminal/iTerm или '
              'Python, через который запущен ORBITclip; полностью перезапусти их.'
              if platform.system()=='Darwin' else
              'На Windows проверь права фонового приложения и программы, которые перехватывают колесо.')
        values=self.wheel.diagnostics()
        detail=(f'Получено событий колеса: {values["raw_wheel"]}\n'
                f'Из них с Ctrl: {values["ctrl_wheel"]}\n'
                f'Выборов записей: {values["moves"]}\n'
                f'macOS tap: {values.get("mac_global_tap", "—")} · '
                f'включён={values.get("mac_tap_enabled", False)} · '
                f'событий={values.get("mac_events", 0)}\n'
                f'Ошибка обработчика: {values["native_error"] or "нет"}')
        answer=QMessageBox.question(self.clock,'Проверка Ctrl + колесо',
            f'Статус: {state}\nСпособ: {backend}\nПодробности: {problem}\n\n{detail}\n\n{hint}\n\n'
            'Показать тестовое облачко? Оно не требует системного перехвата.',
            QMessageBox.Yes|QMessageBox.No)
        if answer==QMessageBox.Yes:
            self.wheel.simulate_one_step()

    def open_mac_input_permissions(self):
        """Direct users to the OS permissions required for cross-application taps."""
        if platform.system()!='Darwin':return
        QMessageBox.information(self.clock,'Доступ к глобальной прокрутке',
            'ORBITclip должен получать события от других программ. В macOS разреши '
            'Python (или Terminal/iTerm, из которого он запущен) в двух разделах: '
            'Конфиденциальность и безопасность → Мониторинг ввода, '
            'а также → Универсальный доступ. Затем полностью закрой терминал, '
            'запусти его заново и перезапусти ORBITclip.')
        QDesktopServices.openUrl(QUrl('x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent'))

    def restart_wheel(self):
        self.wheel.start()
        self.toast.pop('Перехват перезапущен: '+(self.wheel.backend or self.wheel.error)[:70])

    def persist_categories(self):
        self.switch_categories=[(c['id'],c['name']) for c in self.categories.wheel_categories()]
        self.switch_category=0
        self.save_settings()

    def edit_scroll_settings(self):
        WheelEditor(self,self.history or self.clock).exec()

    def reset_hotkeys(self):self.hotkeys.configure(self.vault.items)

    def directory_config(self):
        if self.offline:return None
        if not self.url or len(self.token)<16:return None
        return {'url':self.url,'token':self.token,'tls_pin':self.tls_pin}

    def peer_channel(self,peerid):
        entry=self.identity.trusted.get(peerid)
        if not entry:return (None,'','')
        try:cfg=validate_config(self.url,self.token,entry['pair'],self.tls_pin)
        except ValueError:return (None,'','')
        place=hashlib.sha256((self.url+'|'+cfg['room']).encode()).hexdigest()
        return (cfg,place,entry['pair'])

    def active_channel(self):
        if self.selected_peer in self.identity.trusted:
            return self.peer_channel(self.selected_peer)
        if self.remote_config:
            return self.remote_config,self.cursor_place,self.remote_pair
        return None,'',''

    def start_peer_bridges(self):
        for ident in self.identity.trusted:
            if ident in self.peer_bridges:continue
            cfg,place,_=self.peer_channel(ident)
            if cfg:
                bridge=RemoteBridge()
                bridge.set_online(not self.offline)
                bridge.configure(cfg,self.device,int(self.peer_cursors.get(ident,0)))
                self.peer_bridges[ident]=bridge
        if not self.selected_peer and self.identity.trusted:
            self.selected_peer=next(iter(self.identity.trusted))

    def send_large_file(self,path):
        """Queue a streaming transfer; never encode large files on Qt thread."""
        if self.offline:
            raise ValueError('Приложение работает оффлайн')
        cfg,place,secret=self.active_channel()
        if not cfg:
            raise ValueError('Сначала выбери подключённое устройство')
        bridge=(self.peer_bridges.get(self.selected_peer)
                if self.selected_peer in self.peer_bridges else self.bridge)
        tid=self.file_sender.start(path,bridge.send,
               {'place':place,'secret':secret})
        self.toast.pop('Файл передаётся частями; получатель должен быть онлайн')
        return tid

    def process_delivery_packet(self,decoded,record,direction,bridge,place,secret,peer_id='legacy'):
        kind=decoded.get('kind')
        if kind=='delivery_ack':
            if direction=='in' and decoded.get('mode')=='probe':
                self.delivery_capabilities[place]=time.monotonic()+30
                return True
            if direction=='in':
                uid=decoded['delivery_id']
                self.delivery_outbox.acknowledge(place,uid)
                self.store.mark_delivered(place,uid)
                if self.chat:
                    self.chat.update_delivery_count()
                    if self.chat.isVisible():
                        self.chat.refresh_messages()
            return True
        if kind!='delivery_text':
            return False
        uid=decoded['delivery_id']
        # Normalize transport envelope into legacy user-facing chat text.
        content=dict(decoded)
        content['kind']='text'
        local=dict(record)
        local['payload']=encrypt_message(content,secret)
        if self.store.put(place,local,direction,delivery_id=uid):
            if direction=='in':
                self.note_incoming(peer_id,'text')
            if self.chat and self.chat.isVisible():
                self.chat.refresh_dialog_list()
                self.chat.refresh_messages()
        if direction=='in':
            # A duplicate retry must also receive its acknowledgement.
            bridge.send({'kind':'delivery_ack','delivery_id':uid})
        elif direction=='out':
            self.delivery_outbox.submitted(uid)
        return True

    def drain_delivery_outbox(self):
        if self.offline:
            return
        for item in self.delivery_outbox.due(limit=2):
            peer=item['peer']
            if peer=='legacy':
                bridge=self.bridge if self.remote_config and self.cursor_place==item['place'] else None
            else:
                cfg,place,_=self.peer_channel(peer)
                bridge=self.peer_bridges.get(peer) if cfg and place==item['place'] else None
            if bridge is None:
                continue
            now=time.monotonic()
            if self.delivery_capabilities.get(item['place'],0)<=now:
                if self.delivery_probe_at.get(item['place'],0)<=now:
                    self.delivery_probe_at[item['place']]=now+10
                    # 7.8.x understands file_probe and does not put it into
                    # chat history. Only 7.9+ returns the additional proof.
                    bridge.send({'kind':'file_probe','transfer_id':item['id'],
                                 'delivery_capability':'v1'})
                continue
            self.delivery_outbox.mark_attempt(item['id'])
            bridge.send_encrypted(item['ciphertext'])
        if self.chat:
            self.chat.update_delivery_count()

    def queue_reliable_text(self,peer,payload):
        if not isinstance(payload,dict) or payload.get('kind')!='text':
            return False
        if peer=='legacy':
            if not self.remote_config:return False
            place=self.cursor_place
            secret=self.remote_pair
        else:
            cfg,place,secret=self.peer_channel(peer)
            if not cfg:return False
        try:
            self.delivery_outbox.enqueue(place,peer,secret,payload)
        except ValueError as exc:
            self.toast.pop('Очередь доставки: '+str(exc)[:100])
            return False
        if self.chat:
            self.chat.update_delivery_count()
        self.toast.pop('В очереди · ждём подтверждения второго устройства')
        return True

    def process_file_packet(self,decoded,record,direction,bridge,place,secret):
        """Consume transport control packets; do not cache chunks in history."""
        kind=decoded.get('kind')
        if kind=='file_probe':
            if direction=='in':
                if decoded.get('delivery_capability')=='v1':
                    bridge.send({'kind':'delivery_ack',
                                 'delivery_id':decoded['transfer_id'],
                                 'mode':'probe'})
                else:
                    bridge.send({'kind':'file_ack','transfer_id':decoded['transfer_id'],
                                 'index':-1})
            return True
        if kind=='file_ack':
            if direction=='in':
                try:self.file_sender.acknowledge(decoded,record)
                except ValueError:pass
            return True
        if kind!='file_chunk':
            return False
        if direction=='out':
            return True
        try:
            saved,created=self.file_receiver.accept(decoded)
            if saved is not None and created:
                reference={'kind':'file_ref','name':decoded['name'],
                           'size':decoded['size'],
                           'transfer_id':decoded['transfer_id'],
                           'origin':'chat'}
                entry={'id':record['id'],'ts':record['ts'],
                       'device':record['device'],
                       'payload':encrypt_message(reference,secret)}
                if self.store.put(place,entry,'in'):
                    self.store.set_saved_path(place,entry['id'],str(saved))
                    self.note_incoming('peer','file')
                    if self.chat and self.chat.isVisible():
                        self.chat.refresh_messages()
                        self.chat.refresh_dialog_list()
            # Final ACK is allowed only if the full SHA-256 verified file
            # already exists; prevents false success after receiver restart.
            if (decoded['index'] < decoded['total']-1
                    or self.file_receiver.is_completed(decoded['transfer_id'])):
                bridge.send({'kind':'file_ack','transfer_id':decoded['transfer_id'],
                             'index':decoded['index']})
        except (OSError,ValueError) as exc:
            self.attachment_errors.append((place,int(record['id']),str(exc)))
            if self.chat:
                self.chat.connection_hint.setText('Передача файла: '+truncate(str(exc),100))
        return True

    def process_file_sender_events(self):
        for _ in range(30):
            try:event=self.file_sender.events.get_nowait()
            except queue.Empty:break
            kind=event[0]
            if kind=='progress':
                _,tid,name,done,total=event
                if self.chat:
                    self.chat.connection_hint.setText(
                        f'Передача {truncate(name,45)}: {done}/{total} частей')
            elif kind=='error':
                _,tid,name,message=event
                self.toast.pop('Передача не завершена: '+truncate(message,85))
                if self.chat:self.chat.connection_hint.setText(
                    'Ошибка передачи '+truncate(name,30)+': '+truncate(message,80))
            elif kind=='complete':
                _,tid,path,size,receipt,context=event
                if receipt and context:
                    message={'kind':'file_ref','name':path.name,'size':size,
                             'transfer_id':tid,'origin':'chat'}
                    entry={'id':receipt['id'],'ts':time.time(),
                           'device':self.device,
                           'payload':encrypt_message(message,context['secret'])}
                    if self.store.put(context['place'],entry,'out'):
                        self.store.set_saved_path(context['place'],entry['id'],str(path))
                self.toast.pop('Файл доставлен: '+path.name)
                if self.chat and self.chat.isVisible():
                    self.chat.refresh_messages()
                    self.chat.refresh_dialog_list()

    def send_to_peer(self,peer,payload):
        if payload.get('kind')=='text' and payload.get('origin')!='workspace':
            return self.queue_reliable_text(peer,payload)
        if self.offline:return False
        if payload.get('origin')!='workspace':self.analytics.record('file_out' if payload.get('kind')=='file' else 'chat_out')
        if peer=='legacy' and self.remote_config:
            self.bridge.send(payload);return True
        bridge=self.peer_bridges.get(peer)
        if not bridge:return False
        bridge.send(payload);return True

    def send_to_active(self,payload):
        if payload.get('kind')=='text' and payload.get('origin')!='workspace':
            peer=self.selected_peer if self.selected_peer in self.identity.trusted else 'legacy'
            return self.queue_reliable_text(peer,payload)
        if not self.offline:self.analytics.record('file_out' if payload.get('kind')=='file' else 'chat_out')
        if self.offline:
            self.toast.pop('Оффлайн: отправка отключена')
            return False
        cfg,_,_=self.active_channel()
        if not cfg:return False
        if self.selected_peer in self.peer_bridges:
            self.peer_bridges[self.selected_peer].send(payload)
        else:self.bridge.send(payload)
        return True

    def send_clip_item(self,ident):
        item=self.vault.find(ident)
        if not item:return
        if item.get('encrypted'):
            return error(self.history,'Сначала расшифруй и скопируй защищённую запись.')
        if not self.active_channel()[0]:return error(self.history,'Нет подключённого получателя')
        self.send_to_active({'kind':'text','text':item.get('text',''),'origin':'clipboard'})
        self.toast.pop('Отправляем фрагмент…')

    def pump_directory(self):
        if self.offline:
            while not self.directory.events.empty():
                try:self.directory.events.get_nowait()
                except queue.Empty:break
            return
        for _ in range(20):
            try:ev=self.directory.events.get_nowait()
            except queue.Empty:break
            typ=ev[0]
            if typ=='roster':
                self.online_devices=ev[1]
                if self.chat:
                    self.chat.refresh_online_list(ev[1])
                    self.chat.refresh_dialog_list()
                if self.online_window and self.online_window.isVisible():self.online_window.refresh()
            elif typ=='request':
                req=ev[1]
                name=req.get('name') or req.get('from','')[:9]
                dialog=QMessageBox(QMessageBox.Question,'ORBITclip · Запрос пары',
                    f'Компьютер «{name}» хочет подключиться к тебе.\nРазрешить постоянную защищённую пару?',
                    QMessageBox.Yes|QMessageBox.No,None)
                dialog.setWindowFlag(Qt.WindowStaysOnTopHint,True)
                accepted=dialog.exec()==QMessageBox.Yes
                self.directory.respond(req['id'],accepted)
                if accepted:self.toast.pop('Подтверждение отправляется…')
            elif typ=='accepted':
                req=ev[1]
                if req.get('from')==self.identity.id:
                    did=req.get('to');pub=req.get('to_public')
                else:did=req.get('from');pub=req.get('from_public')
                if did not in self.identity.trusted:
                    record=next((x for x in self.online_devices if x.get('id')==did),{})
                    nickname=record.get('name') or req.get('name') or did[:9]
                    try:self.identity.pair(did,nickname,pub)
                    except Exception as ex:error(self.chat or self.clock,str(ex));continue
                    self.start_peer_bridges()
                    self.toast.pop('Новая пара: '+nickname)
                    if self.chat:self.chat.refresh_peers()
            elif typ=='declined':
                self.toast.pop('Запрос на сопряжение отклонён')
            elif typ=='response_sent':
                if self.chat and ev[2]:self.chat.directory_info.setText('Запрос одобрен. Устанавливаем защищённую пару…')
            elif typ=='requested':
                if self.chat:self.chat.directory_info.setText('Ожидаем подтверждение на втором компьютере')
            elif typ=='error':
                if self.chat and self.chat.pages.currentIndex()==1:
                    self.chat.directory_info.setText('Каталог устройств: '+truncate(ev[1],100))

    def process_peer_events(self):
        if self.offline:
            for bridge in self.peer_bridges.values():
                while not bridge.events.empty():
                    try:bridge.events.get_nowait()
                    except queue.Empty:break
            return
        refresh=False
        for ident,bridge in list(self.peer_bridges.items()):
            cfg,place,key=self.peer_channel(ident)
            for _ in range(20):
                try:ev=bridge.events.get_nowait()
                except queue.Empty:break
                event=ev[0]
                if event in ('received','sent') and cfg:
                    record=ev[1]
                    direction='out' if record.get('device')==self.device else 'in'
                    try:decoded=decrypt_message(record['payload'],key)
                    except Exception:decoded={}
                    if decoded.get('origin')=='workspace':
                        if direction=='in':self.handle_workspace_message(ident,decoded)
                        continue
                    if self.process_delivery_packet(decoded,record,direction,bridge,place,key,ident):
                        continue
                    if self.process_file_packet(decoded,record,direction,bridge,place,key):
                        continue
                    if self.store.put(place,record,direction):
                        if ident==self.selected_peer:refresh=True
                        if direction=='in':
                            data={}
                            try:
                                data=decrypt_message(record['payload'],key)
                                if data.get('kind')=='file':
                                    saved=self.save_incoming_attachment(place,record,data)
                                    description=('Файл сохранён: ' if saved else 'Ошибка сохранения файла: ')+data.get('name','')
                                else:description=data.get('text','')
                            except Exception:description='Зашифрованное сообщение'
                            self.note_incoming(ident, 'file' if data.get('kind')=='file' else 'text')
                elif event=='cursor':
                    v=int(ev[1])
                    if v>int(self.peer_cursors.get(ident,0)):
                        self.peer_cursors[ident]=v;self.save_settings()
                elif event in ('status','error') and ident==self.selected_peer and self.chat:
                    self.chat.connection_hint.setText(ev[1])
        if refresh and self.chat and self.chat.isVisible() and self.chat.pages.currentIndex()==0:
            self.chat.refresh_dialog_list()
            self.chat.refresh_messages()

    def restore_remote(self):
        if not self.remote_pair or not self.token:return
        try:
            conf=validate_config(self.url,self.token,self.remote_pair,self.tls_pin)
            self.apply_remote(conf)
        except ValueError:return

    def apply_remote(self,conf):
        self.remote_config=conf
        self.url=conf['url'];self.token=conf['token'];self.remote_pair=conf['pair'];self.tls_pin=conf.get('tls_pin','')
        room=conf['room']
        place=hashlib.sha256((conf['url']+'|'+room).encode('utf-8')).hexdigest()
        if place!=self.cursor_place:
            self.cursor=0;self.cursor_place=place
        self.bridge.configure(conf,self.device,self.cursor)
        self.save_settings()
        if self.chat:self.chat.refresh_messages()

    def check_server_async(self):
        if self.offline:return
        # No GUI calls from background threads.
        url=self.url.rstrip('/');token=self.token;device=self.device
        def task():
            try:
                with public_urlopen(url+'/health',timeout=8) as resp:
                    response=json.loads(resp.read(4096))
                if len(token)>=16:
                    conf={'url':url,'token':token,'tls_pin':self.tls_pin}
                    try:
                        result=http_json(conf,'POST','/v1/heartbeat',{'device':device,'version':CLIENT_VERSION})
                        self.keepalive_events.put(('online','● Сервер доступен · авторизован',result.get('server_version','?')))
                    except urllib.error.HTTPError as ex:
                        if ex.code==404:
                            self.keepalive_events.put(('online','● HTTPS доступен · версия сервера устарела','старый сервер'))
                        elif ex.code==401:
                            self.keepalive_events.put(('offline','● Неверный токен сервера','?'))
                        else:raise
                else:self.keepalive_events.put(('online','● HTTPS доступен · нужен токен',response.get('server_version','?')))
            except Exception as ex:self.keepalive_events.put(('offline','● Ошибка: '+truncate(str(ex),66),'?'))
        threading.Thread(target=task,daemon=True).start()

    def keepalive(self):
        while not self.keepalive_stop.is_set():
            if not self.offline:self.check_server_async()
            self.keepalive_stop.wait(10)

    def pump_events(self):
        self.drain_delivery_outbox()
        self.process_file_sender_events()
        self.pump_directory()
        self.process_peer_events()
        for _ in range(20):
            try:tag,state,ver=self.keepalive_events.get_nowait()
            except queue.Empty:break
            if self.offline:continue
            self.network_status=state;self.server_version=ver
            if self.online_window and self.online_window.isVisible():self.online_window.refresh()
            if self.chat:
                self.chat.online.setText(state)
                self.chat.version.setText(f'Клиент {QT_CLIENT_VERSION} · Сервер {ver}')
        for _ in range(40):
            try:ev=self.pair_bridge.events.get_nowait()
            except queue.Empty:break
            if not self.offline and self.chat:self.chat.pair_event(ev)
        refresh=False
        for _ in range(80):
            try:ev=self.bridge.events.get_nowait()
            except queue.Empty:break
            if self.offline:continue
            event=ev[0]
            if event in ('received','sent') and self.remote_config:
                record=ev[1]
                room=ev[3] if event=='received' else ev[2]
                if room!=self.remote_config['room']:continue
                direction='out' if record.get('device')==self.device else 'in'
                try:decoded=decrypt_message(record['payload'],self.remote_pair)
                except Exception:decoded={}
                if self.process_delivery_packet(decoded,record,direction,
                                                self.bridge,self.cursor_place,self.remote_pair):
                    continue
                if self.process_file_packet(decoded,record,direction,
                                            self.bridge,self.cursor_place,self.remote_pair):
                    continue
                if self.store.put(self.cursor_place,record,direction):
                    refresh=True
                    if direction=='in':
                        data={}
                        try:
                            data=decrypt_message(record['payload'],self.remote_pair)
                            if data.get('kind')=='file':
                                saved=self.save_incoming_attachment(self.cursor_place,record,data)
                                excerpt=('Файл сохранён: ' if saved else 'Ошибка сохранения файла: ')+data.get('name','')
                            else:excerpt=data.get('text','')
                        except Exception:excerpt='Получено зашифрованное сообщение'
                        self.note_incoming('legacy','file' if data.get('kind')=='file' else 'text')
            elif event=='cursor':
                if ev[1]>self.cursor:
                    self.cursor=ev[1];self.save_settings()
            elif event=='status':
                if self.chat:self.chat.connection_hint.setText(ev[1])
            elif event=='error':
                if self.chat:self.chat.connection_hint.setText(ev[1])
                else:self.toast.pop(truncate(ev[1],100))
        if refresh and self.chat and self.chat.isVisible() and self.chat.pages.currentIndex()==0:
            self.chat.refresh_dialog_list()
            self.chat.refresh_messages()
        for _ in range(12):
            try:ident=self.hotkeys.events.get_nowait()
            except queue.Empty:break
            item=self.vault.find(ident)
            if item and item.get('pinned') and not item.get('encrypted'):
                self.copy_text(item.get('text',''))
                QTimer.singleShot(300,self.try_paste)
        for _ in range(8):
            try:flow=self.flow_hotkeys.events.get_nowait()
            except queue.Empty:break
            if flow=='palette':self.open_palette()
            elif flow=='queue_next':self.paste_next_from_queue()
        for _ in range(16):
            try:what,value=self.wheel.events.get_nowait()
            except queue.Empty:break
            if what=='move':
                if not self.switch_active:self.switch_active=True;self.switch_category=0;self.switch_index=0
                self.switch_index+=value
                self.draw_bubble(value)
            elif what=='category' and self.switch_active and self.switch_categories and not self.queue_wheel_mode:
                # Wrap over the end and skip empty categories without hiding the popup.
                self.switch_category=next_nonempty_category(
                    self.switch_categories,self.switch_category,
                    lambda cid:bool(self.wheel_queue.candidates(self.vault.items,self.categories,cid)))
                self.switch_index=0;self.draw_bubble()
            elif what=='commit' and self.switch_active:
                item=self.selected_switch()
                self.switch_active=False;self.bubble.hide()
                if item and not item.get('encrypted'):
                    if self.queue_wheel_mode:
                        consumed=self.paste_queue.take(item.get('id',''))
                        if consumed is None:
                            continue
                        self.copy_text(consumed)
                        self.queue_changed()
                    else:
                        self.copy_text(item.get('text',''))
                    self.analytics.record('wheel_commit')
                    if self.paste_on_release:
                        QTimer.singleShot(110,lambda:self.try_paste(0))
            elif what in ('cancel','pointer_down'):
                self.switch_active=False;self.bubble.hide()

    def candidates(self):
        if self.queue_wheel_mode:
            return [{'id':item['uid'],'text':item['text'],
                     'title':item['title']} for item in self.paste_queue.items()]
        if not self.switch_categories:return []
        category=self.switch_categories[self.switch_category%len(self.switch_categories)][0]
        return self.wheel_queue.candidates(self.vault.items,self.categories,category)

    def selected_switch(self):
        choices=self.candidates()
        return choices[self.switch_index%len(choices)] if choices else None

    def draw_bubble(self, wheel_step=0):
        choices=self.candidates()
        if not choices and self.queue_wheel_mode:
            self.bubble.show_empty('Очередь вставки')
            return
        if not choices:
            if self.switch_categories:
                self.bubble.show_empty(self.switch_categories[self.switch_category%len(self.switch_categories)][1])
            else:self.bubble.hide()
            return
        self.switch_index %= len(choices)
        cat_name=('Очередь вставки' if self.queue_wheel_mode else
                  self.switch_categories[self.switch_category%len(self.switch_categories)][1])
        if isinstance(self.bubble,DrumBubble):
            self.bubble.show_neighbors(choices,self.switch_index,cat_name,step_hint=wheel_step)
        else:
            self.bubble.show_item(choices[self.switch_index],cat_name,self.switch_index,len(choices))

    def try_paste(self,attempt=0):
        if self.hotkeys.modifiers_held():
            if attempt>=30:
                self.toast.pop('Не удалось вставить: Ctrl/Alt остаются нажатыми')
                return
            QTimer.singleShot(80,lambda:self.try_paste(attempt+1))
        else:self.hotkeys.paste()

    def save_incoming_attachment(self,place,record,payload):
        """Persist an incoming file immediately; keep only path metadata in history."""
        try:
            folder=QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
            target=Path(folder) if folder else Path.home()/'Downloads'
            saved=save_attachment(payload,target/'ORBITclip',MAX_FILE_SIZE)
            self.store.set_saved_path(place,record['id'],str(saved))
            self.analytics.record('file_in')
            return saved
        except (OSError,ValueError,TypeError) as exc:
            # Keep encrypted packet in local history; allow retry without another transfer.
            self.attachment_errors.append((place,int(record['id']),str(exc)))
            return None

    def shutdown(self):
        self.file_sender.stop()
        self.events.stop();self.keepalive_stop.set()
        self.qt.removeEventFilter(self.local_wheel_filter)
        self.directory.stop();self.pair_bridge.stop();self.bridge.stop()
        for bridge in self.peer_bridges.values():bridge.stop()
        self.wheel.stop();self.hotkeys.stop();self.flow_hotkeys.stop()
        if self.tray_icon is not None:self.tray_icon.hide()
        if self.chat_status_icon is not None:self.chat_status_icon.hide()
        self.paste_queue.clear()
        self.save_settings();self.store.close();self.notifications.close();self.analytics.close();self.qt.quit()

    def run(self):return self.qt.exec()


def main():
    client=OrbitApp()
    return client.run()

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        traceback_text=traceback.format_exc()
        destination=Path.home()/'.orbitclip_crash.log'
        try:
            with destination.open('a',encoding='utf-8') as file:
                file.write('\n'+datetime.now().isoformat()+'  ORBITclip '+QT_CLIENT_VERSION+'\n'+traceback_text+'\n')
        except OSError:pass
        print(traceback_text,file=sys.stderr,flush=True)
        try:
            qt=QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None,'ORBITclip · Ошибка запуска',
                'Приложение не смогло запуститься.\n\n'+truncate(traceback_text,1300)+
                '\n\nПолный журнал: '+str(destination))
        except Exception:pass
        raise SystemExit(1)

