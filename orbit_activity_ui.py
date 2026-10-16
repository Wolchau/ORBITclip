"""Desktop notification inbox and local analytics, both independent windows."""
from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QFrame, QComboBox, QMessageBox, QFileDialog, QCheckBox,
    QScrollArea, QSizePolicy
)
from orbit_appearance import palette


class NotificationCenterWindow(QWidget):
    GROUPS=[('Все',''),('Непрочитанные','unread'),('Сообщения','messages'),
            ('Файлы','files'),('Пространства','spaces'),('Система','system')]

    def __init__(self,app):
        super().__init__(None)
        self.app=app;self.rows=[]
        self.setWindowTitle('ORBITclip · Уведомления')
        self.resize(820,570)
        root=QHBoxLayout(self);root.setContentsMargins(14,14,14,14);root.setSpacing(12)
        nav=QFrame();nav.setObjectName('side');nav.setFixedWidth(178)
        left=QVBoxLayout(nav);left.setContentsMargins(10,15,10,12);left.setSpacing(8)
        header=QLabel('Уведомления');header.setObjectName('heading');left.addWidget(header)
        self.groups=QListWidget();self.groups.setObjectName('notification-filters')
        for title,_ in self.GROUPS:self.groups.addItem(title)
        self.groups.setCurrentRow(0);left.addWidget(self.groups,1)
        left.addWidget(QPushButton('Отметить все прочитанными',clicked=self.mark_all))
        left.addWidget(QPushButton('Очистить историю',clicked=self.clear_all))
        root.addWidget(nav)
        area=QVBoxLayout();root.addLayout(area,1)
        heading=QLabel('Центр уведомлений');heading.setObjectName('heading');area.addWidget(heading)
        hint=QLabel('События хранятся только на этом компьютере. Текст переписки не записывается.')
        hint.setObjectName('muted');hint.setWordWrap(True);area.addWidget(hint)
        self.items=QListWidget();area.addWidget(self.items,1)
        self.details=QLabel('Выбери событие для просмотра')
        self.details.setWordWrap(True);self.details.setMinimumHeight(56);self.details.setObjectName('muted')
        area.addWidget(self.details)
        buttons=QHBoxLayout();area.addLayout(buttons)
        self.open_button=QPushButton('Открыть',clicked=self.open_selected)
        buttons.addWidget(self.open_button);buttons.addStretch()
        buttons.addWidget(QPushButton('Закрыть',clicked=self.close))
        self.groups.currentRowChanged.connect(self.refresh)
        self.items.currentRowChanged.connect(self.select_row)
        self.items.itemDoubleClicked.connect(lambda *_: self.open_selected())
        self.refresh()

    def refresh(self,*_):
        idx=self.groups.currentRow()
        choice=self.GROUPS[idx][1] if 0<=idx<len(self.GROUPS) else ''
        self.rows=self.app.notifications.list(only_unread=choice=='unread',
                                               kind=choice if choice not in ('','unread') else None)
        self.items.blockSignals(True);self.items.clear()
        for record in self.rows:
            stamp=datetime.fromtimestamp(record['ts']).strftime('%d.%m  %H:%M')
            prefix='●  ' if not record['seen'] else '   '
            item=QListWidgetItem(f"{prefix}{record['title']}     ·     {stamp}")
            item.setToolTip(record['description'])
            self.items.addItem(item)
        self.items.blockSignals(False)
        self.details.setText(f'Событий: {len(self.rows)} · непрочитанных: {self.app.notifications.unread()}')
        self.open_button.setEnabled(False)

    def select_row(self,row):
        if not 0<=row<len(self.rows):return
        item=self.rows[row]
        self.details.setText(item['title']+'\n'+item['description'])
        self.open_button.setEnabled(item['kind'] in ('messages','spaces','files'))
        if not item['seen']:
            self.app.notifications.mark_read(item['id'])
            item['seen']=1
            self.app.update_notification_badge()

    def open_selected(self):
        index=self.items.currentRow()
        if index<0 or index>=len(self.rows):return
        item=self.rows[index]
        if item['kind']=='messages':
            if item.get('target') in self.app.identity.trusted:
                self.app.selected_peer=item['target']
            self.app.open_chat()
        elif item['kind'] in ('files','spaces'):self.app.open_workspaces()

    def mark_all(self):
        self.app.notifications.mark_read()
        self.app.update_notification_badge();self.refresh()

    def clear_all(self):
        if QMessageBox.question(self,'Очистить уведомления','Удалить всю локальную историю уведомлений?',
                                QMessageBox.Yes | QMessageBox.No)!=QMessageBox.Yes:return
        self.app.notifications.clear();self.app.update_notification_badge();self.refresh()


class ActivityChart(QWidget):
    def __init__(self,app):
        super().__init__();self.app=app;self.series=[]
        self.setMinimumHeight(145)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)

    def set_data(self,summary):
        self.series=[summary['activity'].get(day,0) for day in summary['days']]
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        rect=self.rect().adjusted(12,9,-12,-20)
        if not self.series or rect.width()<5:return
        p.setPen(QPen(QColor(self.app.palette['border']),1))
        p.drawLine(rect.bottomLeft(),rect.bottomRight())
        maxvalue=max(1,max(self.series));bar_width=rect.width()/len(self.series)
        p.setPen(Qt.NoPen);p.setBrush(QColor(self.app.palette['accent']))
        for idx,value in enumerate(self.series):
            if not value:continue
            h=max(3, rect.height()*value/maxvalue)
            p.drawRoundedRect(QRectF(rect.left()+idx*bar_width+max(1,bar_width*.16),
                rect.bottom()-h,max(2,bar_width*.65),h),2,2)


class AnalyticsWindow(QWidget):
    METRICS=[('clip_capture','Новых записей'),('clip_copy','Повторных копирований'),
             ('chat_in','Получено сообщений'),('chat_out','Отправлено сообщений'),
             ('file_in','Получено файлов'),('space_clip_in','Записей из пространств'),
             ('ocr_run','Распознаваний OCR'),('screenshot','Снимков экрана'),
             ('wheel_commit','Выборов через прокрутку')]

    def __init__(self,app):
        super().__init__(None);self.app=app
        self.setWindowTitle('ORBITclip · Аналитика');self.resize(760,670)
        root=QVBoxLayout(self);root.setContentsMargins(24,20,24,20);root.setSpacing(14)
        header=QHBoxLayout();root.addLayout(header)
        title=QLabel('Моя активность');title.setObjectName('heading');header.addWidget(title)
        header.addStretch()
        self.range=QComboBox();self.range.addItem('7 дней',7);self.range.addItem('30 дней',30)
        self.range.addItem('90 дней',90);self.range.setCurrentIndex(1)
        self.range.currentIndexChanged.connect(self.refresh);header.addWidget(self.range)
        self.enabled=QCheckBox('Собирать статистику');self.enabled.setChecked(app.analytics.enabled)
        self.enabled.toggled.connect(self.set_enabled);root.addWidget(self.enabled)
        note=QLabel('Только агрегированные счётчики на этом устройстве. Содержимое буфера, SQL-запросы и сообщения не собираются.')
        note.setObjectName('muted');note.setWordWrap(True);root.addWidget(note)
        self.cards=QLabel();self.cards.setWordWrap(True);self.cards.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.cards.setMinimumHeight(120);root.addWidget(self.cards)
        root.addWidget(QLabel('Занимательная статистика текста'))
        self.fun=QLabel()
        self.fun.setWordWrap(True)
        self.fun.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.fun.setMinimumHeight(88)
        root.addWidget(self.fun)
        root.addWidget(QLabel('Активность по дням'))
        self.chart=ActivityChart(app);root.addWidget(self.chart,1)
        root.addWidget(QLabel('Источники копирований'))
        self.sources=QLabel();self.sources.setMinimumHeight(88);self.sources.setWordWrap(True)
        self.sources.setTextInteractionFlags(Qt.TextSelectableByMouse);root.addWidget(self.sources)
        buttons=QHBoxLayout();root.addLayout(buttons)
        buttons.addWidget(QPushButton('Экспорт CSV…',clicked=self.export_csv))
        buttons.addWidget(QPushButton('Сбросить данные',clicked=self.reset_data))
        buttons.addStretch();buttons.addWidget(QPushButton('Закрыть',clicked=self.close))
        self.refresh()

    def refresh(self,*_):
        stats=self.app.analytics.summary(self.range.currentData() or 30)
        totals=stats['totals']
        self.cards.setText('     '.join(f'{title}:  {totals.get(key,0)}' for key,title in self.METRICS))
        self.sources.setText('   ·   '.join(f'{name}: {count}' for name,count in stats['sources']) or 'Источников пока нет')
        self.chart.set_data(stats)
        insights=self.app.analytics.text_summary(self.range.currentData() or 30)
        t=insights['totals']
        today=insights['select_today']
        previous=insights['select_last_week']
        comparison=('на {:g}% {} прошлого такого же дня недели'.format(
            abs((today-previous)*100/previous),
            'больше, чем' if today>previous else 'меньше, чем')
            if previous and today!=previous else
            ('как и неделю назад' if previous else 'неделей ранее данных нет'))
        self.fun.setText(
            f"За период: {t.get('chars',0):,} символов, "
            f"{t.get('russian',0):,} русских букв, "
            f"{t.get('latin',0):,} латинских букв, "
            f"{t.get('digits',0):,} цифр, {t.get('symbols',0):,} спецсимволов.\n"
            f"Слово SELECT встречалось сегодня {today} раз — {comparison}.")

    def set_enabled(self,enabled):
        self.app.analytics.enabled=bool(enabled)
        self.app.settings['analytics_enabled']=bool(enabled);self.app.save_settings()
        self.refresh()

    def export_csv(self):
        path,_=QFileDialog.getSaveFileName(self,'Сохранить статистику','orbitclip_analytics.csv','CSV (*.csv)')
        if path:self.app.analytics.export_csv(path)

    def reset_data(self):
        if QMessageBox.question(self,'Сбросить статистику',
                'Удалить все локальные счётчики использования?',QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
        self.app.analytics.reset();self.refresh()
