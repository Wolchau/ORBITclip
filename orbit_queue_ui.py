"""Visual Flow queue editor. Dedicated Qt window, no remote sync or autostorage.

Editing and browsing never paste into another application. The global
Ctrl+Alt+J shortcut still performs the actual paste through OrbitApp.
"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QPlainTextEdit, QListWidget, QListWidgetItem, QAbstractItemView,
    QInputDialog, QMessageBox, QComboBox, QFrame
)


class PasteQueueWindow(QWidget):
    def __init__(self,app):
        super().__init__(None, Qt.Window)
        self.app=app
        self._refreshing=False
        self.setWindowTitle('ORBITclip · Очередь вставки')
        self.resize(830,595)
        self.setMinimumSize(600,490)
        root=QVBoxLayout(self)
        root.setContentsMargins(20,18,20,18)
        root.setSpacing(10)
        heading=QHBoxLayout()
        name=QLabel('Очередь вставки')
        name.setStyleSheet('font-size:19px;font-weight:700')
        heading.addWidget(name)
        heading.addStretch()
        self.counter=QLabel()
        heading.addWidget(self.counter)
        root.addLayout(heading)
        hint=QLabel('Перетащи запись для изменения порядка · выдели несколько, чтобы объединить. '
                    'Ctrl+Alt+J вставляет следующий фрагмент в активное приложение.')
        hint.setWordWrap(True)
        root.addWidget(hint)
        columns=QHBoxLayout()
        self.list=QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setDragEnabled(True)
        self.list.setAcceptDrops(True)
        self.list.setDropIndicatorShown(True)
        self.list.setSpacing(5)
        self.list.setMinimumWidth(300)
        self.list.currentItemChanged.connect(self.update_preview)
        self.list.model().rowsMoved.connect(self._reordered)
        columns.addWidget(self.list,3)
        details=QVBoxLayout()
        details.addWidget(QLabel('Содержимое выбранного фрагмента'))
        self.preview=QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText('Выбери запись слева')
        details.addWidget(self.preview,1)
        self.note=QLabel()
        self.note.setWordWrap(True)
        details.addWidget(self.note)
        columns.addLayout(details,2)
        root.addLayout(columns,1)
        row=QHBoxLayout()
        self.merge_button=QPushButton('Объединить выделенные')
        self.merge_button.clicked.connect(self.merge_selected)
        row.addWidget(self.merge_button)
        for title,handler in [('↑',lambda:self.shift(-1)),('↓',lambda:self.shift(1)),
                              ('Удалить',self.delete_selected)]:
            button=QPushButton(title);button.clicked.connect(handler);row.addWidget(button)
        row.addStretch()
        root.addLayout(row)
        row2=QHBoxLayout()
        self.paste_button=QPushButton('Копировать следующий')
        self.paste_button.setToolTip('Только копирует, чтобы не вставлять в само окно очереди. '
                                     'Для вставки в другое приложение — Ctrl+Alt+J.')
        self.paste_button.clicked.connect(self.copy_next)
        row2.addWidget(self.paste_button)
        self.drum_button=QPushButton()
        self.drum_button.setCheckable(True)
        self.drum_button.toggled.connect(self.toggle_drum)
        row2.addWidget(self.drum_button)
        row2.addStretch()
        clear=QPushButton('Очистить')
        clear.clicked.connect(self.clear)
        row2.addWidget(clear)
        root.addLayout(row2)
        presets_row=QHBoxLayout()
        presets_row.addWidget(QLabel('Сохранённые наборы'))
        self.presets=QComboBox()
        self.presets.setMinimumWidth(205)
        presets_row.addWidget(self.presets,1)
        for title,handler in [('Загрузить',self.load_preset),
                              ('Сохранить как…',self.save_preset),
                              ('Удалить набор',self.delete_preset)]:
            button=QPushButton(title)
            button.clicked.connect(handler)
            presets_row.addWidget(button)
        root.addLayout(presets_row)
        foot=QLabel('Очередь хранится в памяти. Наборы сохраняются только по твоему '
                    'решению и содержат текст локально, без дополнительного шифрования.')
        foot.setWordWrap(True)
        foot.setStyleSheet('font-size:11px;')
        root.addWidget(foot)
        self.refresh_presets()
        self.refresh()

    def refresh_presets(self):
        old=self.presets.currentText()
        self.presets.clear()
        for name in sorted(self.app.queue_presets.all(),key=str.casefold):
            self.presets.addItem(name)
        if old:
            idx=self.presets.findText(old)
            if idx>=0:self.presets.setCurrentIndex(idx)

    def refresh(self,preferred=None):
        queue=self.app.paste_queue
        selected=preferred or (self.list.currentItem().data(Qt.UserRole)
                               if self.list.currentItem() else None)
        self._refreshing=True
        self.list.clear()
        for n,entry in enumerate(queue.items(),1):
            summary=' '.join(entry['text'].split())[:100]
            title=entry.get('title') or 'Фрагмент'
            item=QListWidgetItem(f'{n:02d}   {title[:55]}\n       {summary}')
            item.setData(Qt.UserRole,entry['uid'])
            item.setToolTip(title)
            item.setSizeHint(QSize(290,60))
            self.list.addItem(item)
            if entry['uid']==selected:self.list.setCurrentItem(item)
        if self.list.count() and self.list.currentRow()<0:
            self.list.setCurrentRow(0)
        self._refreshing=False
        self.update_preview()
        done=queue.completed
        total=queue.total
        self.counter.setText(f'{done} / {total} выполнено · осталось {len(queue)}')
        self.paste_button.setEnabled(bool(len(queue)))
        self.drum_button.blockSignals(True)
        self.drum_button.setChecked(self.app.queue_wheel_mode)
        self.drum_button.setText('Барабан: очередь' if self.app.queue_wheel_mode else 'Барабан: история')
        self.drum_button.blockSignals(False)

    def update_preview(self,*_):
        entry=self._current_entry()
        self.preview.setPlainText(entry['text'][:200_000] if entry else '')
        self.note.setText(f'Длина: {len(entry["text"])} символов'
                          if entry else 'Пустая очередь — добавь записи из истории или быстрого поиска')

    def _current_entry(self):
        item=self.list.currentItem()
        uid=item.data(Qt.UserRole) if item else None
        return next((x for x in self.app.paste_queue.items() if x['uid']==uid),None)

    def _reordered(self,*_):
        if self._refreshing:return
        ids=[self.list.item(n).data(Qt.UserRole) for n in range(self.list.count())]
        queue=self.app.paste_queue
        if set(ids)!={x['uid'] for x in queue.items()} or len(ids)!=len(queue):
            return
        for target,uid in enumerate(ids):
            queue.move(uid,target)
        self.app.queue_changed()
        self.refresh(preferred=ids[0] if ids else None)

    def shift(self,direction):
        entry=self._current_entry()
        if not entry:return
        old=self.list.currentRow()
        new=max(0,min(self.list.count()-1,old+direction))
        self.app.paste_queue.move(entry['uid'],new)
        self.app.queue_changed()
        self.refresh(preferred=entry['uid'])

    def delete_selected(self):
        ids=[item.data(Qt.UserRole) for item in self.list.selectedItems()]
        for uid in ids:
            self.app.paste_queue.remove(uid)
        if ids:self.app.queue_changed()
        self.refresh()

    def merge_selected(self):
        ids=[item.data(Qt.UserRole) for item in self.list.selectedItems()]
        if self.app.paste_queue.merge(ids):
            self.app.queue_changed()
            self.refresh()
        else:
            QMessageBox.information(self,'Объединение',
                'Выдели не менее двух записей. Итоговый текст не должен превышать 200 000 символов.')

    def copy_next(self):
        value=self.app.paste_queue.pop()
        if value is None:return
        self.app.copy_text(value)
        self.app.queue_changed()
        self.refresh()

    def clear(self):
        if not len(self.app.paste_queue):return
        if QMessageBox.question(self,'Очистить очередь',
                                 'Удалить все оставшиеся элементы очереди?')!=QMessageBox.Yes:return
        self.app.clear_paste_queue()
        self.refresh()

    def toggle_drum(self,value):
        self.app.set_queue_wheel_mode(value)
        self.refresh()

    def save_preset(self):
        if not len(self.app.paste_queue):
            return QMessageBox.information(self,'Сохранение','Очередь пуста')
        name,ok=QInputDialog.getText(self,'Сохранить набор','Название набора:')
        if not ok or not name.strip():return
        if QMessageBox.question(
                self,'Сохранить тексты локально?',
                'Сохранённый набор будет хранить полный текст фрагментов '
                'в локальном файле без дополнительного шифрования. Продолжить?')!=QMessageBox.Yes:
            return
        try:self.app.queue_presets.save(name,self.app.paste_queue)
        except ValueError as exc:
            return QMessageBox.warning(self,'Сохранение',str(exc))
        self.refresh_presets()
        idx=self.presets.findText(name.strip())
        if idx>=0:self.presets.setCurrentIndex(idx)

    def load_preset(self):
        name=self.presets.currentText()
        if not name:return
        if len(self.app.paste_queue) and QMessageBox.question(
            self,'Загрузить набор','Заменить текущие оставшиеся записи набором «'+name+'»?'
        )!=QMessageBox.Yes:return
        if self.app.queue_presets.load(name,self.app.paste_queue):
            self.app.queue_changed()
            self.refresh()
        else:QMessageBox.warning(self,'Загрузка','Набор не найден или повреждён')

    def delete_preset(self):
        name=self.presets.currentText()
        if not name:return
        if QMessageBox.question(self,'Удалить набор','Удалить «'+name+'»?')!=QMessageBox.Yes:return
        self.app.queue_presets.delete(name)
        self.refresh_presets()
