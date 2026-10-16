"""Quick, keyboard-first clipboard command palette. No extra dependencies."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QApplication, QMenu,
)

from orbit_flow import quick_actions
from orbit_appearance import palette


class CommandPalette(QWidget):
    def __init__(self, app):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.app = app
        self.setObjectName('flowPalette')
        self.setMinimumSize(530, 420)
        self.resize(610, 480)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.apply_theme()
        layout=QVBoxLayout(self);layout.setContentsMargins(16,14,16,15);layout.setSpacing(9)
        header=QHBoxLayout()
        title=QLabel('⌕  Найти и использовать');title.setStyleSheet('font-size:16px;font-weight:700;')
        header.addWidget(title,1)
        close=QPushButton('×');close.setFixedSize(32,30);close.clicked.connect(self.hide)
        header.addWidget(close);layout.addLayout(header)
        self.search=QLineEdit()
        self.search.setPlaceholderText('Поиск по тексту, избранному и командам…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.results=QListWidget()
        self.results.setUniformItemSizes(False)
        self.results.itemDoubleClicked.connect(self.copy_selected)
        layout.addWidget(self.results,1)
        actions=QHBoxLayout()
        copy=QPushButton('Копировать');copy.clicked.connect(self.copy_selected)
        paste=QPushButton('Копировать + вставить');paste.clicked.connect(self.paste_selected)
        enqueue=QPushButton('В очередь');enqueue.clicked.connect(self.queue_selected)
        smart=QPushButton('Действия ▾');smart.clicked.connect(self.show_smart)
        for button in (copy,paste,enqueue,smart):actions.addWidget(button)
        layout.addLayout(actions)
        self.hint=QLabel('Enter — копировать   ·   Ctrl+Enter — вставить   ·   Esc — закрыть')
        self.hint.setStyleSheet('font-size:10px;color:#94AAB7;')
        layout.addWidget(self.hint)
        QShortcut(QKeySequence('Return'),self,activated=self.copy_selected)
        QShortcut(QKeySequence('Ctrl+Return'),self,activated=self.paste_selected)
        QShortcut(QKeySequence('Escape'),self,activated=self.hide)

    def apply_theme(self):
        p=palette(getattr(self.app,'appearance_theme','midnight'))
        self.setStyleSheet(f"""
            QWidget#flowPalette{{background:{p['surface']};border:1px solid {p['border']};border-radius:15px;}}
            QListWidget{{background:transparent;color:{p['text']};border:0;outline:0;}}
            QListWidget::item{{padding:10px 12px;border-radius:8px;}}
            QListWidget::item:selected{{color:{p['text']};background:{p['hover']};}}
        """)

    def open_palette(self):
        self.apply_theme()
        self.refresh()
        screen=QApplication.screenAt(self.app.clock.frameGeometry().center()) or QApplication.primaryScreen()
        if screen:
            area=screen.availableGeometry()
            self.move(area.center().x()-self.width()//2,
                      area.top()+max(55,area.height()//5))
        self.show();self.raise_();self.activateWindow()
        self.search.setFocus();self.search.selectAll()

    def refresh(self,*_):
        needle=self.search.text().strip().casefold()
        previous=self.results.currentItem()
        selected=previous.data(Qt.UserRole) if previous else None
        self.results.clear()
        items=sorted(self.app.vault.items,key=lambda x:float(x.get('ts',0)),reverse=True)
        favs=[x for x in items if x.get('pinned')]
        regular=[x for x in items if not x.get('pinned')]
        ordered=favs+regular
        count=0
        for entry in ordered:
            ident=str(entry.get('id',''))
            encrypted=bool(entry.get('encrypted'))
            content='' if encrypted else str(entry.get('text',''))
            name=str(entry.get('title') or '')
            app=str(entry.get('source_app') or '')
            if needle and needle not in (' '.join((name,content,app,str(entry.get('kind',''))))).casefold():
                continue
            excerpt=name or ('🔒 Защищённая запись' if encrypted else content.replace('\n',' ↵ '))
            excerpt=excerpt[:92] or 'Без названия'
            badge='★ ' if entry.get('pinned') else ''
            line=QListWidgetItem(badge+excerpt+'\n    '+str(entry.get('kind','текст')).upper()+' · '+app[:28])
            line.setData(Qt.UserRole,('clip',ident))
            line.setSizeHint(QSize(500,52))
            self.results.addItem(line)
            count+=1
            if count>=80:break
        commands=[('Открыть историю','history'),('Открыть сообщения','chat'),
                  ('Настройки','settings'),('Вставить следующий из очереди','queue_next'),
                  ('Очистить очередь вставки','queue_clear')]
        for title,key in commands:
            if needle and needle not in title.casefold():continue
            row=QListWidgetItem('⌘  '+title)
            row.setData(Qt.UserRole,('command',key))
            row.setSizeHint(QSize(500,43))
            self.results.addItem(row)
        if self.results.count():
            match=next((i for i in range(self.results.count()) if self.results.item(i).data(Qt.UserRole)==selected),0)
            self.results.setCurrentRow(match)
        self.hint.setText(f'Найдено: {count} · Очередь: {len(self.app.paste_queue)} · Enter — копировать · Ctrl+Enter — вставить')

    def selected(self):
        row=self.results.currentItem()
        return row.data(Qt.UserRole) if row else None

    def _execute(self, paste=False, enqueue=False):
        selected=self.selected()
        if not selected:return
        typ,ident=selected
        if typ=='command':
            self.hide()
            actions={'history':self.app.open_history,'chat':self.app.open_chat,
                     'settings':self.app.open_settings,'queue_next':self.app.paste_next_from_queue,
                     'queue_clear':self.app.clear_paste_queue}
            actions[ident]()
            return
        entry=self.app.vault.find(ident)
        if not entry:return
        if entry.get('encrypted'):
            self.hide();self.app.open_history()
            self.app.toast.pop('Расшифруй защищённую запись в истории')
            return
        value=str(entry.get('text') or '')
        if enqueue:
            if not self.app.paste_queue.push(value):
                self.app.toast.pop('Очередь заполнена или текст пуст')
            self.refresh()
            return
        self.hide()
        self.app.copy_text(value)
        if paste:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(220,lambda:self.app.try_paste())

    def copy_selected(self):self._execute()
    def paste_selected(self):self._execute(paste=True)
    def queue_selected(self):self._execute(enqueue=True)

    def show_smart(self):
        selected=self.selected()
        if not selected or selected[0]!='clip':return
        entry=self.app.vault.find(selected[1])
        if not entry or entry.get('encrypted'):return
        actions=quick_actions(entry.get('text',''),entry.get('kind','text'))
        if not actions:
            self.app.toast.pop('Для этой записи нет подходящих преобразований')
            return
        menu=QMenu(self)
        for action in actions:
            menu.addAction(action['title'],lambda checked=False,result=action['result']:self._apply(result))
        menu.exec(self.mapToGlobal(self.rect().bottomRight()))

    def _apply(self,result):
        self.hide()
        self.app.copy_text(str(result))
        self.app.toast.pop('Результат преобразования скопирован')
