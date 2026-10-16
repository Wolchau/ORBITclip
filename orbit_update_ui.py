"""Qt frontend for local, user-confirmed ORBITclip upgrades.

No update checks without explicit user action. Network work is off the Qt
thread; downloaded ZIPs are validated by the stdlib updater before restart.
"""
import queue
import threading
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QFileDialog, QMessageBox, QLineEdit,
                              QProgressBar, QPlainTextEdit)
from PySide6.QtGui import QDesktopServices

from orbit_version import CLIENT_VERSION
from orbit_update import (UpdateError, stage_archive, launch_after_exit,
                          backup_location, log_update, read_history, version_tuple)
from orbit_update_chain import (list_releases, download_and_prepare,
                                launch_chain_after_exit)


class UpdateWindow(QWidget):
    def __init__(self, app):
        super().__init__(None, Qt.Window)
        self.app=app
        self.releases=[]
        self.prepared=None
        self.events=queue.Queue()
        self.busy=False
        self.setWindowTitle('ORBITclip · Обновления')
        self.resize(550, 565)
        self.setMinimumWidth(470)
        lay=QVBoxLayout(self);lay.setContentsMargins(23,23,23,20);lay.setSpacing(13)
        title=QLabel('Обновления ORBITclip')
        title.setStyleSheet('font-size:19px;font-weight:700')
        lay.addWidget(title)
        self.info=QLabel('Установлена версия '+CLIENT_VERSION)
        lay.addWidget(self.info)
        self.status=QLabel('Нажми «Проверить», чтобы узнать о новой версии на GitHub.')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(42)
        lay.addWidget(self.status)
        self.progress=QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        self.progress.setFormat('Ожидание')
        lay.addWidget(self.progress)
        warn=QLabel('Проверка запускается только по запросу. При недоступном приватном '
                    'репозитории можно выбрать скачанный ZIP вручную.')
        warn.setWordWrap(True)
        warn.setStyleSheet('font-size:11px;opacity:0.7')
        lay.addWidget(warn)
        self.auth=QLineEdit()
        self.auth.setEchoMode(QLineEdit.Password)
        self.auth.setPlaceholderText('Необязательно: GitHub-токен для приватного репозитория')
        self.auth.setToolTip('Токен используется только для этой проверки и не сохраняется в настройках.')
        lay.addWidget(self.auth)
        row=QHBoxLayout()
        self.check_button=QPushButton('Проверить')
        self.check_button.clicked.connect(self.check_updates)
        row.addWidget(self.check_button)
        self.download_button=QPushButton('Скачать и проверить')
        self.download_button.clicked.connect(self.fetch_update)
        self.download_button.setEnabled(False)
        row.addWidget(self.download_button)
        lay.addLayout(row)
        row2=QHBoxLayout()
        manual=QPushButton('Выбрать ZIP…')
        manual.clicked.connect(self.local_archive)
        row2.addWidget(manual)
        self.install_button=QPushButton('Установить и перезапустить')
        self.install_button.clicked.connect(self.apply_update)
        self.install_button.setEnabled(False)
        row2.addWidget(self.install_button)
        lay.addLayout(row2)
        controls=QHBoxLayout()
        controls.addWidget(QLabel('История обновлений'))
        controls.addStretch()
        backups=QPushButton('Открыть резервные копии')
        backups.clicked.connect(self.open_backups)
        controls.addWidget(backups)
        lay.addLayout(controls)
        self.history=QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setFixedHeight(115)
        lay.addWidget(self.history)
        self.refresh_history()
        self.poller=QTimer(self);self.poller.timeout.connect(self._poll);self.poller.start(110)

    def _start(self, fn, *args):
        if self.busy:
            return
        self.busy=True
        self.check_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.status.setText('Проверяем…')
        self.progress.setRange(0,0) # Busy, not a fabricated percentage
        def run():
            try:
                result=fn(*args)
                self.events.put(('ok',result))
            except Exception as exc:
                self.events.put(('error',str(exc)))
        threading.Thread(target=run,daemon=True,name='orbit-update-check').start()

    def check_updates(self):
        self.releases=[]
        self.prepared=None
        token=self.auth.text().strip()
        self._start(lambda:('releases',list_releases(CLIENT_VERSION,token=token)))

    def fetch_update(self):
        if not self.releases:
            return
        token=self.auth.text().strip()
        self._start(self._download_job,list(self.releases),token)

    def _download_job(self,releases,token):
        def progress(index,count,done,total):
            self.events.put(('chain_progress',(index,count,done,total)))
        plan,manifests=download_and_prepare(releases,self.app_root,token=token,
                                           progress=progress)
        return ('prepared_chain',(plan,manifests))

    @property
    def app_root(self):
        return Path(__file__).resolve().parent

    def local_archive(self):
        path,_=QFileDialog.getOpenFileName(self,'Открыть патч ORBITclip','','ZIP (*.zip)')
        if path:
            self.releases=[]
            self._start(lambda:('prepared',stage_archive(Path(path),self.app_root)))

    def _poll(self):
        try:
            kind,value=self.events.get_nowait()
        except queue.Empty:
            return
        if kind=='chain_progress':
            index,count,done,total=value
            if count>0:
                portion=done/total if total>0 else 0
                self.progress.setRange(0,100)
                self.progress.setValue(min(100,round((index+portion)*100/count)))
                self.progress.setFormat(f'Загрузка {min(index+1,count)} / {count} · %p%')
            return
        self.busy=False
        self.check_button.setEnabled(True)
        if kind=='error':
            self.progress.setRange(0,100)
            self.progress.setValue(0)
            self.progress.setFormat('Ошибка')
            self.status.setText('Не удалось подготовить обновление.\n'+str(value)[:500])
            log_update('failure','Не удалось проверить или подготовить патч')
            self.refresh_history()
            return
        self.progress.setRange(0,100)
        self.progress.setValue(100)
        self.progress.setFormat('Готово')
        result, payload=value
        if result=='releases':
            self.releases=payload
            if not payload:
                self.status.setText('Установлена последняя доступная версия.')
                log_update('check','Новых версий не найдено')
            else:
                target=max(payload,key=lambda release:version_tuple(release['version']))['version']
                self.status.setText(
                    f"Доступна {target}. Найдено {len(payload)} более новых релизов. "
                    "Приложение самостоятельно найдёт цепочку совместимых патчей, "
                    "скачает их и проверит на временной копии до установки.")
                self.download_button.setEnabled(True)
                log_update('check','Доступен релиз '+target)
        elif result=='prepared_chain':
            plan,manifests=payload
            self.prepared=('chain',plan,manifests)
            target=manifests[-1]['to_version']
            self.info.setText(f"Установлена {CLIENT_VERSION} → подготовлена {target}")
            route=' → '.join([manifests[0]['from_version']]+[
                manifest['to_version'] for manifest in manifests])
            self.status.setText(f'Проверено {len(manifests)} патчей: {route}. '
                                'После выхода установка выполнится одной транзакцией '
                                'с откатом всей цепочки при ошибке.')
            self.install_button.setEnabled(True)
            log_update('validated',f'Полная цепочка проверена: {len(manifests)} этапов',
                       old_version=manifests[0]['from_version'],new_version=target)
        elif result=='prepared':
            stage,manifest=payload
            self.prepared=('single',stage,[manifest])
            self.info.setText(f"Установлена {CLIENT_VERSION} → подготовлена {manifest['to_version']}")
            self.status.setText('Один патч проверен: версии, исходные файлы и ZIP. '
                                'Установка начнётся только после закрытия приложения.')
            self.install_button.setEnabled(True)
            log_update('validated','Один патч проверен',old_version=manifest['from_version'],
                       new_version=manifest['to_version'])
        self.refresh_history()

    def refresh_history(self):
        lines=[]
        for event in reversed(read_history(20)):
            timestamp=datetime.fromtimestamp(event['time']).strftime('%d.%m %H:%M')
            description=event.get('message','')
            versions=(' '+event.get('from_version','')+' → '+event.get('to_version','')
                      if event.get('to_version') else '')
            lines.append(f'{timestamp}  {description}{versions}')
        self.history.setPlainText('\n'.join(lines) if lines else 'Пока нет операций обновления')

    def open_backups(self):
        folder=backup_location(self.app_root)
        if not folder.is_dir():
            QMessageBox.information(self,'Резервные копии',
                'Резервных копий пока нет. Они появятся после первого обновления.')
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(self,'Резервные копии',
                'Не удалось открыть каталог: '+str(folder))

    def apply_update(self):
        if not self.prepared:return
        mode,stage,manifests=self.prepared
        manifest={'from_version':manifests[0]['from_version'],
                  'to_version':manifests[-1]['to_version']}
        text=(f"Обновить ORBITclip {CLIENT_VERSION} → {manifest['to_version']} "
              f"({len(manifests)} патчей)?\n\n"
              "Все окна закроются. После успешной установки программа "
              "автоматически запустится. При ошибке исходные файлы восстанавливаются.")
        if QMessageBox.question(self,'Подтвердить установку',text,
                                QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
        try:
            import os
            if mode=='chain':
                launch_chain_after_exit(stage,self.app_root,os.getpid())
            else:
                launch_after_exit(stage,self.app_root,os.getpid())
        except (OSError,UpdateError) as exc:
            QMessageBox.critical(self,'Обновление не запущено',str(exc))
            return
        self.status.setText('Закрываем приложение. Дальнейшая установка и откат '
                            'выполнятся отдельно; результат появится при следующем запуске.')
        self.progress.setRange(0,0)
        log_update('waiting','Установка подтверждена; завершение приложения',
                   old_version=manifest['from_version'],
                   new_version=manifest['to_version'])
        self.refresh_history()
        self.install_button.setEnabled(False)
        QTimer.singleShot(160,self.app.shutdown)
