"""Review-first ORBIT Extract dialog. Source text stays unchanged."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,QVBoxLayout,QHBoxLayout,QLabel,QTabWidget,QTableWidget,
    QTableWidgetItem,QHeaderView,QPushButton,QFileDialog,QMessageBox,
    QPlainTextEdit,QComboBox,
)
from orbit_extract import inspect,export_table,entity_rows


class ExtractDialog(QDialog):
    def __init__(self,app,item,parent=None):
        super().__init__(parent)
        if item.get('encrypted'):
            raise ValueError('Защищённые записи не анализируются')
        self.app=app
        self.source=str(item.get('text') or '')
        self.report=inspect(self.source)
        self.setWindowTitle('ORBITclip · Извлечение данных')
        self.resize(940,680)
        self.setMinimumSize(650,480)
        root=QVBoxLayout(self)
        root.setSpacing(10)
        title=QLabel('Извлечение данных · предпросмотр')
        title.setStyleSheet('font-size:18px;font-weight:700')
        root.addWidget(title)
        summary=QLabel(
            f"Распознано: {self.report['kind']} · "
            f"строк таблицы: {self.report['preview_rows']} · "
            f"найдено сущностей: {len(self.report['entities'])}"
        )
        root.addWidget(summary)
        hint=QLabel('Обработка только на этом компьютере. Все значения взяты из исходного '
                    'текста; найденные поля и форматы необходимо проверить перед использованием.')
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.tabs=QTabWidget()
        root.addWidget(self.tabs,1)
        self.table=self._grid(self.report['rows'] or [],empty='Не обнаружена структурированная таблица')
        self.tabs.addTab(self.table,'Таблица / поля')
        self.entities=self._grid(entity_rows(self.report['entities']),
                                 empty='Даты, суммы и идентификаторы не обнаружены')
        self.tabs.addTab(self.entities,'Сущности')
        self.original=QPlainTextEdit(self.source[:200000])
        self.original.setReadOnly(True)
        self.tabs.addTab(self.original,'Исходный текст')
        if self.report['warnings']:
            warning=QLabel(' · '.join(self.report['warnings']))
            warning.setWordWrap(True)
            root.addWidget(warning)
        actions=QHBoxLayout()
        self.format=QComboBox()
        self.format.addItem('TSV · Excel','tsv')
        self.format.addItem('CSV','csv')
        self.format.addItem('JSON','json')
        actions.addWidget(self.format)
        copy=QPushButton('Копировать таблицу')
        copy.clicked.connect(self.copy_table)
        actions.addWidget(copy)
        selected=QPushButton('Копировать ячейку')
        selected.clicked.connect(self.copy_cell)
        actions.addWidget(selected)
        export=QPushButton('Экспортировать…')
        export.clicked.connect(self.save_table)
        actions.addWidget(export)
        actions.addStretch()
        close=QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        root.addLayout(actions)

    def _grid(self,rows,empty):
        grid=QTableWidget()
        grid.setEditTriggers(QTableWidget.NoEditTriggers)
        grid.setAlternatingRowColors(True)
        grid.setSelectionBehavior(QTableWidget.SelectItems)
        if not rows:
            grid.setRowCount(0)
            grid.setColumnCount(1)
            grid.setHorizontalHeaderLabels([empty])
            return grid
        grid.setColumnCount(len(rows[0]))
        grid.setHorizontalHeaderLabels([str(x) for x in rows[0]])
        grid.setRowCount(len(rows)-1)
        for i,row in enumerate(rows[1:]):
            for j,value in enumerate(row):
                cell=QTableWidgetItem(str(value))
                cell.setToolTip(str(value)[:1000])
                grid.setItem(i,j,cell)
        grid.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        grid.horizontalHeader().setStretchLastSection(True)
        grid.verticalHeader().setDefaultSectionSize(26)
        return grid

    def _selected_rows(self):
        if self.tabs.currentWidget() is self.entities:
            return entity_rows(self.report['entities'])
        return self.report['rows']

    def copy_table(self):
        rows=self._selected_rows()
        if not rows or len(rows)<2:
            QMessageBox.information(self,'Извлечение','Данных для копирования нет')
            return
        self.app.copy_text(export_table(rows,self.format.currentData()))

    def copy_cell(self):
        grid=self.entities if self.tabs.currentWidget() is self.entities else self.table
        cell=grid.currentItem()
        if cell is None:
            QMessageBox.information(self,'Извлечение','Выбери ячейку в таблице')
            return
        self.app.copy_text(cell.text())

    def save_table(self):
        rows=self._selected_rows()
        if not rows or len(rows)<2:
            QMessageBox.information(self,'Извлечение','Данных для экспорта нет')
            return
        ext=self.format.currentData()
        name,_=QFileDialog.getSaveFileName(
            self,'Сохранить извлечённые данные',str(Path.home()/('orbit_extract.'+ext)))
        if not name:return
        try:
            Path(name).write_text(export_table(rows,ext),encoding='utf-8')
        except OSError as exc:
            QMessageBox.critical(self,'Ошибка экспорта',str(exc))
