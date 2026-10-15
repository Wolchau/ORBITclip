"""Qt workspace surface: opt-in shares, group messages and invitations."""
from datetime import datetime
from orbit_version import CLIENT_VERSION
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QHBoxLayout,QVBoxLayout,QLabel,QLineEdit,QListWidget,
    QListWidgetItem,QPushButton,QPlainTextEdit,QDialog,QCheckBox,QDialogButtonBox,QMessageBox)

class WorkspaceWindow(QWidget):
    def __init__(self,app):
        super().__init__(None)
        self.app=app;self.setWindowFlag(Qt.Window,True)
        self.setWindowTitle('ORBITclip · Пространства · v'+CLIENT_VERSION);self.resize(980,680)
        self.setMinimumSize(650,440)
        root=QHBoxLayout(self)
        side=QVBoxLayout();root.addLayout(side,1)
        side.addWidget(QLabel('ПРОСТРАНСТВА'))
        side.addWidget(QLabel('Личные коллекции и совместные группы'))
        self.list=QListWidget();self.list.currentItemChanged.connect(self.update_view);side.addWidget(self.list,1)
        create=QPushButton('＋ Создать пространство');create.clicked.connect(self.create);side.addWidget(create)
        add=QPushButton('Пригласить ещё…');add.clicked.connect(self.add_member);side.addWidget(add)
        resend=QPushButton('Повторить приглашения');resend.clicked.connect(self.resend_invites);side.addWidget(resend)
        join=QPushButton('Принять приглашение');join.clicked.connect(lambda checked=False:self.decide(True));side.addWidget(join)
        refuse=QPushButton('Отклонить приглашение');refuse.clicked.connect(lambda checked=False:self.decide(False));side.addWidget(refuse)
        self.join_button=join;self.refuse_button=refuse
        side.addWidget(QLabel('Новые копирования всегда личные.\nПубликация в группе — только вручную.'))
        right=QVBoxLayout();root.addLayout(right,3)
        self.heading=QLabel('Выбери пространство');self.heading.setStyleSheet('font-size:18px;font-weight:700;')
        right.addWidget(self.heading)
        self.status=QLabel('');right.addWidget(self.status)
        self.messages=QListWidget();self.chat_heading=QLabel('Групповой чат');right.addWidget(self.chat_heading);right.addWidget(self.messages,2)
        self.compose=QPlainTextEdit();self.compose.setPlaceholderText('Сообщение группе…');self.compose.setMaximumHeight(75)
        right.addWidget(self.compose)
        send=QPushButton('Отправить сообщение');send.clicked.connect(self.send);right.addWidget(send);self.send_button=send
        self.clips_heading=QLabel('Опубликованные фрагменты');right.addWidget(self.clips_heading)
        self.clips=QListWidget();self.clips.itemDoubleClicked.connect(self.copy_item);right.addWidget(self.clips,2)
        self.open_context=QPushButton('Открыть коллекцию в библиотеке →');self.open_context.clicked.connect(self.open_personal_context)
        right.addWidget(self.open_context);self.open_context.hide()
        right.addWidget(QLabel('Двойной клик по фрагменту — скопировать'))
        self.refresh()
    def selected(self):
        item=self.list.currentItem()
        data=item.data(Qt.UserRole) if item else None
        return data if isinstance(data,str) and data in self.app.workspaces.spaces else None

    def current_app(self):
        item=self.list.currentItem()
        value=item.data(Qt.UserRole) if item else None
        return value[1] if isinstance(value,tuple) and len(value)==2 and value[0]=='app' else None

    def refresh(self,select=None):
        current=self.list.currentItem()
        chosen_key=select or (current.data(Qt.UserRole) if current else None)
        self.list.blockSignals(True);self.list.clear();choose=None
        def add(text,key,enabled=True):
            nonlocal choose
            entry=QListWidgetItem(text)
            entry.setData(Qt.UserRole,key)
            if not enabled:entry.setFlags(entry.flags() & ~Qt.ItemIsEnabled)
            self.list.addItem(entry)
            if key==chosen_key:choose=entry
        add('  ЛИЧНЫЕ КОЛЛЕКЦИИ',None,False)
        add('◉  Вся личная история',('app',''))
        names=sorted({str(x.get('source_app') or 'Неизвестно') for x in self.app.vault.items},key=str.casefold)
        for name in names:
            count=sum((x.get('source_app') or 'Неизвестно')==name for x in self.app.vault.items)
            add(f'   ▸  {name}  · {count}',('app',name))
        add('  СОВМЕСТНЫЕ',None,False)
        for wid,space in self.app.workspaces.spaces.items():
            status=space['members'].get(self.app.identity.id)
            if status=='declined':continue
            add(('◌ ' if status=='pending' else '◎ ')+space['name'],wid)
        if choose:self.list.setCurrentItem(choose)
        else:
            first=next((self.list.item(i) for i in range(self.list.count())
                        if self.list.item(i).data(Qt.UserRole)==('app','')),None)
            if first:self.list.setCurrentItem(first)
        self.list.blockSignals(False);self.update_view()

    def open_personal_context(self):
        app=self.current_app()
        if app is None:return
        self.app.open_history()
        self.app.history.change_source(app)
        self.app.history.raise_()

    def update_view(self,*_):
        self.messages.clear();self.clips.clear()
        app_name=self.current_app()
        is_personal=app_name is not None
        self.open_context.setVisible(is_personal)
        for widget in (self.chat_heading,self.messages,self.compose,self.send_button):
            widget.setVisible(not is_personal)
        if is_personal:
            self.join_button.hide();self.refuse_button.hide()
            self.heading.setText('Личное · '+(app_name or 'Вся история'))
            self.status.setText('Фрагменты хранятся только на твоём компьютере. Другие участники их не видят.')
            self.clips_heading.setText('История приложения' if app_name else 'Личная история')
            entries=[x for x in self.app.vault.items if not app_name or (x.get('source_app') or 'Неизвестно')==app_name]
            for entry in reversed(entries[-100:]):
                text='🔒 Защищённая запись' if entry.get('encrypted') else (entry.get('text') or '')[:170]
                row=QListWidgetItem((entry.get('title') or entry.get('kind','Текст'))+'  ·  '+text)
                row.setData(Qt.UserRole,'' if entry.get('encrypted') else entry.get('text',''))
                self.clips.addItem(row)
            return
        self.clips_heading.setText('Опубликованные фрагменты')
        wid=self.selected()
        if not wid or wid not in self.app.workspaces.spaces:
            self.join_button.hide();self.refuse_button.hide()
            self.heading.setText('Выбери пространство')
            self.status.setText('Создай общую группу или открой личную коллекцию слева.')
            return
        space=self.app.workspaces.spaces[wid]
        self.heading.setText(space['name'])
        member_status=space['members'].get(self.app.identity.id,'pending')
        self.join_button.setVisible(member_status=='pending')
        self.refuse_button.setVisible(member_status=='pending')
        names=[]
        for pid,status in space['members'].items():
            person=('Я' if pid==self.app.identity.id else self.app.identity.trusted.get(pid,{}).get('name',pid[:8]))
            names.append(person+(' (ожидаем)' if status=='pending' else ''))
        self.status.setText(('Ожидание подтверждения · ' if member_status!='accepted' else 'Участники: ')+', '.join(names))
        for msg in space['messages']:
            sender=('Я' if msg.get('sender')==self.app.identity.id else self.app.identity.trusted.get(msg.get('sender'),{}).get('name',str(msg.get('sender'))[:8]))
            self.messages.addItem(f"{datetime.fromtimestamp(msg['ts']).strftime('%H:%M')}  {sender}:  {msg['text'][:130]}")
        self.messages.scrollToBottom()
        for entry in space['clips']:
            sender=('Я' if entry.get('sender')==self.app.identity.id else self.app.identity.trusted.get(entry.get('sender'),{}).get('name',str(entry.get('sender'))[:8]))
            row=QListWidgetItem(f"▦ {entry.get('title') or entry.get('kind','Текст')} · {sender}\n{entry['text'][:180]}")
            row.setData(Qt.UserRole,entry['text']);self.clips.addItem(row)

    def copy_item(self,item):
        text=item.data(Qt.UserRole)
        if text:
            self.app.copy_text(text);self.app.toast.pop('Фрагмент скопирован')
    def create(self):
        if self.app.offline:return QMessageBox.warning(self,'Оффлайн','Приглашения требуют подключения к серверу')
        dialog=QDialog(self);dialog.setWindowTitle('Новое общее пространство')
        lay=QVBoxLayout(dialog);lay.addWidget(QLabel('Название пространства'))
        name=QLineEdit();name.setPlaceholderText('Например, Проект сайта');lay.addWidget(name)
        lay.addWidget(QLabel('Пригласить доверенные устройства:'))
        choices=[]
        for pid,record in self.app.identity.trusted.items():
            box=QCheckBox(record.get('name',pid[:8]));lay.addWidget(box);choices.append((pid,box))
        if not choices:lay.addWidget(QLabel('Сначала установи защищённую пару с устройствами.'))
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);lay.addWidget(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        try:s=self.app.workspaces.create(name.text(),[pid for pid,b in choices if b.isChecked()])
        except ValueError as ex:return QMessageBox.warning(self,'Пространство',str(ex))
        for pid,state in s['members'].items():
            if state=='pending':self.app.send_to_peer(pid,self.app.workspaces.invitation(s['id']))
        self.refresh(s['id'])
    def send(self):
        if self.app.offline:return QMessageBox.warning(self,'Оффлайн','Отключи режим «Быть оффлайн» для отправки')
        wid=self.selected()
        if not wid:return
        try:packet=self.app.workspaces.chat(wid,self.compose.toPlainText())
        except ValueError as ex:return QMessageBox.warning(self,'Сообщение',str(ex))
        self.app.broadcast_workspace(wid,packet);self.compose.clear();self.update_view()

    def add_member(self):
        wid=self.selected()
        if not wid:return
        if self.app.offline:return QMessageBox.warning(self,'Оффлайн','Новые приглашения доступны только онлайн')
        space=self.app.workspaces.spaces[wid]
        if space['owner']!=self.app.identity.id:
            return QMessageBox.information(self,'Участники','Участников приглашает создатель пространства')
        options=[(pid,rec) for pid,rec in self.app.identity.trusted.items() if pid not in space['members']]
        if not options:return QMessageBox.information(self,'Участники','Все доверенные устройства уже приглашены')
        dialog=QDialog(self);dialog.setWindowTitle('Пригласить в «'+space['name']+'»')
        lay=QVBoxLayout(dialog);lay.addWidget(QLabel('Выбери устройства (не будут получать личную историю):'))
        picks=[]
        for pid,rec in options:
            check=QCheckBox(rec.get('name',pid[:8]));lay.addWidget(check);picks.append((pid,check))
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);lay.addWidget(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        try:added=self.app.workspaces.invite_more(wid,[pid for pid,box in picks if box.isChecked()])
        except ValueError as exc:return QMessageBox.warning(self,'Участники',str(exc))
        for pid in added:self.app.send_to_peer(pid,self.app.workspaces.invitation(wid))
        self.refresh(wid)
        if added:self.app.toast.pop('Приглашения отправлены · устройства должны быть онлайн')

    def resend_invites(self):
        wid=self.selected()
        if not wid:return
        if self.app.offline:return QMessageBox.warning(self,'Оффлайн','Приглашения отправляются только онлайн')
        space=self.app.workspaces.spaces[wid]
        if space['owner']!=self.app.identity.id:
            return QMessageBox.information(self,'Участники','Повторить приглашение может создатель')
        pending=[pid for pid,state in space['members'].items() if state=='pending' and pid!=self.app.identity.id]
        for pid in pending:self.app.send_to_peer(pid,self.app.workspaces.invitation(wid))
        self.app.toast.pop('Повторено приглашений: '+str(len(pending)))

    def decide(self,accept):
        wid=self.selected()
        if not wid:return
        space=self.app.workspaces.spaces[wid]
        if space['members'].get(self.app.identity.id)!='pending':return
        try:reply=self.app.workspaces.decide(wid,accept)
        except ValueError as exc:return QMessageBox.warning(self,'Пространство',str(exc))
        if not self.app.send_to_peer(space['owner'],reply):
            QMessageBox.warning(self,'Подключение','Решение сохранено, но не отправлено. Подключись к серверу для синхронизации.')
        self.refresh(wid)
