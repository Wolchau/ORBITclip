"""Business semantics editor for SQL Explorer.

The business descriptions are local to the PostgreSQL connection profile and
are NOT written back to the database. Metric SQL is generated only from
verified table/column metadata; it is never executed automatically.
"""
from __future__ import annotations

import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QLineEdit, QPlainTextEdit, QListWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QMessageBox,
)
from orbit_sql_semantics import BusinessSemantics, AGGREGATIONS, FIELD_ROLES, CARDINALITIES


_ROLE_LABELS = {
    "": "Не задана", "dimension": "Измерение", "measure": "Показатель",
    "identifier": "Идентификатор", "date": "Дата/время",
    "currency": "Денежное поле", "status": "Статус",
}
_AGG_LABELS = {
    "SUM": "SUM · сумма", "AVG": "AVG · среднее",
    "MIN": "MIN · минимум", "MAX": "MAX · максимум",
    "COUNT": "COUNT · непустые", "COUNT_DISTINCT": "COUNT DISTINCT · уникальные",
    "COUNT_ROWS": "COUNT(*) · строки",
}


class BusinessSemanticsPanel(QWidget):
    def __init__(self, project, catalog, columns, fks, parent=None):
        super().__init__(parent)
        self.logic = BusinessSemantics(project, catalog, columns)
        self._fks = list(fks)
        self._loading = False
        self.setObjectName("businessSemanticsPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        heading = QLabel("Бизнес-семантика")
        heading.setStyleSheet("font-size:18px; font-weight:700;")
        root.addWidget(heading)
        note = QLabel(
            "Описания сохраняются локально для этого подключения PostgreSQL. "
            "Ничего не меняется в базе. Метрики используют только проверенные поля; "
            "SQL можно скопировать, но приложение не выполнит его автоматически.")
        note.setWordWrap(True)
        root.addWidget(note)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._init_tables()
        self._init_metrics()
        self._init_relations()
        self._init_glossary()
        footer = QHBoxLayout()
        footer.addStretch(1)
        export = QPushButton("Копировать бизнес-контекст (JSON)")
        export.setToolTip("Только схема, описания и определения метрик; без строк базы и паролей.")
        export.clicked.connect(self.copy_context)
        footer.addWidget(export)
        root.addLayout(footer)
        self.refresh_tables()
        self.refresh_metrics()
        self.refresh_relations()
        self.refresh_glossary()

    def _page(self, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.tabs.addTab(widget, title)
        return layout

    def _init_tables(self):
        area = self._page("Таблицы и поля")
        line = QHBoxLayout()
        line.addWidget(QLabel("Таблица:"))
        self.tables = QComboBox()
        self.tables.setMinimumWidth(270)
        self.tables.currentTextChanged.connect(self._load_table)
        line.addWidget(self.tables, 1)
        self.table_status = QLabel("")
        line.addWidget(self.table_status)
        area.addLayout(line)
        form = QFormLayout()
        self.table_title = QLineEdit()
        self.table_title.setPlaceholderText("Например: Перевозки / Заказы / Клиенты")
        self.table_description = QPlainTextEdit()
        self.table_description.setMaximumHeight(70)
        self.table_description.setPlaceholderText(
            "Что означает одна запись и как таблицу используют в аналитике")
        self.table_grain = QLineEdit()
        self.table_grain.setPlaceholderText(
            "Например: одна строка — один заказ; ключ заказа уникален")
        form.addRow("Название в бизнесе", self.table_title)
        form.addRow("Назначение", self.table_description)
        form.addRow("Детализация (зерно)", self.table_grain)
        area.addLayout(form)
        area.addWidget(QLabel("Поля · физическое имя / название / роль / единица / определение"))
        self.fields = QTableWidget(0, 5)
        self.fields.setHorizontalHeaderLabels([
            "Столбец БД", "Бизнес-название", "Роль", "Единица", "Бизнес-определение"])
        self.fields.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.fields.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive)
        self.fields.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self.fields.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        self.fields.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch)
        self.fields.setAlternatingRowColors(True)
        area.addWidget(self.fields, 1)
        actions = QHBoxLayout()
        self.save_table_button = QPushButton("Сохранить описания таблицы и полей")
        self.save_table_button.clicked.connect(self.save_table)
        actions.addWidget(self.save_table_button)
        actions.addStretch(1)
        area.addLayout(actions)

    def _init_metrics(self):
        area = self._page("Метрики → SQL")
        line = QHBoxLayout()
        self.metric_list = QListWidget()
        self.metric_list.setFixedWidth(205)
        self.metric_list.currentTextChanged.connect(self._load_metric)
        line.addWidget(self.metric_list)
        right = QVBoxLayout()
        line_form = QFormLayout()
        self.metric_name = QLineEdit()
        self.metric_name.setPlaceholderText("Выручка за перевозки")
        self.metric_table = QComboBox()
        self.metric_table.currentTextChanged.connect(self.refresh_metric_columns)
        self.metric_column = QComboBox()
        self.metric_agg = QComboBox()
        for value in AGGREGATIONS:
            self.metric_agg.addItem(_AGG_LABELS[value], value)
        self.metric_agg.currentIndexChanged.connect(self.refresh_metric_columns)
        self.metric_unit = QLineEdit()
        self.metric_unit.setPlaceholderText("₽, шт., %, дней")
        self.metric_description = QPlainTextEdit()
        self.metric_description.setMaximumHeight(72)
        self.metric_description.setPlaceholderText(
            "Что измеряем; какие статусы или исключения важно учитывать")
        self.metric_group = QComboBox()
        self.metric_group.addItem("Без группировки", "")
        line_form.addRow("Название", self.metric_name)
        line_form.addRow("Источник", self.metric_table)
        line_form.addRow("Поле", self.metric_column)
        line_form.addRow("Агрегация", self.metric_agg)
        line_form.addRow("Единица", self.metric_unit)
        line_form.addRow("Определение", self.metric_description)
        line_form.addRow("Разрез в SQL", self.metric_group)
        right.addLayout(line_form)
        tools = QHBoxLayout()
        for label, callback in (
            ("Сохранить метрику", self.save_metric),
            ("Новая", self.clear_metric),
            ("Удалить", self.remove_metric),
            ("Собрать SQL", self.make_metric_sql),
            ("Копировать SQL", self.copy_metric_sql),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            tools.addWidget(button)
        right.addLayout(tools)
        self.sql_preview = QPlainTextEdit()
        self.sql_preview.setReadOnly(True)
        self.sql_preview.setPlaceholderText(
            "После сохранения определения нажми «Собрать SQL». "
            "SQL формируется без неявных JOIN и неизвестных фильтров.")
        right.addWidget(self.sql_preview, 1)
        line.addLayout(right, 1)
        area.addLayout(line, 1)
        foot = QLabel(
            "Определения не превращаются в произвольный исполняемый SQL: "
            "генератор поддерживает только агрегацию по одной таблице. "
            "Если нужны фильтры или связи, дополни полученный запрос в SQL Studio.")
        foot.setWordWrap(True)
        area.addWidget(foot)

    def _init_relations(self):
        area = self._page("Связи")
        area.addWidget(QLabel("Существующие FK и ручные связи · аннотирование бизнес-смысла"))
        self.relation = QComboBox()
        self.relation.currentIndexChanged.connect(self._load_relation)
        area.addWidget(self.relation)
        form = QFormLayout()
        self.cardinality = QComboBox()
        self.cardinality.addItems(CARDINALITIES)
        self.relation_description = QPlainTextEdit()
        self.relation_description.setPlaceholderText(
            "Например: груз относится к городу отправления; "
            "направление 1:N может дублировать суммы при JOIN")
        form.addRow("Кардинальность", self.cardinality)
        form.addRow("Бизнес-смысл и риски JOIN", self.relation_description)
        area.addLayout(form)
        button = QPushButton("Сохранить бизнес-описание связи")
        button.clicked.connect(self.save_relation)
        area.addWidget(button)
        area.addStretch(1)

    def _init_glossary(self):
        area = self._page("Глоссарий")
        row = QHBoxLayout()
        self.terms = QListWidget()
        self.terms.setFixedWidth(205)
        self.terms.currentTextChanged.connect(self._load_term)
        row.addWidget(self.terms)
        form = QVBoxLayout()
        self.term = QLineEdit()
        self.term.setPlaceholderText("Клиент, отправка, заказ, активный пользователь…")
        self.term_description = QPlainTextEdit()
        self.term_description.setPlaceholderText(
            "Определение, синонимы, правила включения/исключения")
        form.addWidget(QLabel("Бизнес-термин"))
        form.addWidget(self.term)
        form.addWidget(QLabel("Определение"))
        form.addWidget(self.term_description)
        buttons = QHBoxLayout()
        for label, callback in (
            ("Сохранить термин", self.save_term),
            ("Новый", self.clear_term),
            ("Удалить", self.delete_term)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        form.addLayout(buttons)
        row.addLayout(form, 1)
        area.addLayout(row, 1)

    def refresh_tables(self):
        table = self.tables.currentText()
        self.tables.blockSignals(True)
        self.tables.clear()
        self.tables.addItems(self.logic.project.data.get("selected", []))
        if table and table in self.logic.project.data.get("selected", []):
            self.tables.setCurrentText(table)
        self.tables.blockSignals(False)
        self._load_table(self.tables.currentText())

    def _load_table(self, table):
        self._loading = True
        try:
            self.fields.setRowCount(0)
            self.save_table_button.setEnabled(bool(table))
            if not table:
                self.table_status.setText("Выбери рабочие таблицы на вкладке «Таблицы»")
                return
            data = self.logic.get_table(table)
            entry = self.logic._tables()[table]
            self.table_status.setText(entry.get("kind", "table"))
            self.table_title.setText(data.get("title", ""))
            self.table_description.setPlainText(
                data.get("description") or entry.get("comment", ""))
            self.table_grain.setText(data.get("grain", ""))
            columns = self.logic.columns.get(table, [])
            self.fields.setRowCount(len(columns))
            for row, column in enumerate(columns):
                name = column["name"]
                stored = self.logic.get_field(table, name)
                original = column.get("comment", "")
                values = (name, stored.get("title", ""),
                          "", stored.get("unit", ""),
                          stored.get("description") or original)
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(str(value))
                    if col == 0:
                        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.fields.setItem(row, col, cell)
                role = QComboBox()
                for key in FIELD_ROLES:
                    role.addItem(_ROLE_LABELS[key], key)
                role.setCurrentIndex(
                    max(0, role.findData(stored.get("role", ""))))
                self.fields.setCellWidget(row, 2, role)
                self.fields.item(row, 0).setToolTip(column.get("type", ""))
        finally:
            self._loading = False

    def save_table(self):
        table = self.tables.currentText()
        if not table:
            return
        try:
            self.logic.save_table(
                table, self.table_title.text(),
                self.table_description.toPlainText(), self.table_grain.text())
            for row, column in enumerate(self.logic.columns[table]):
                def value(col):
                    item = self.fields.item(row, col)
                    return item.text() if item else ""
                role = self.fields.cellWidget(row, 2).currentData()
                self.logic.save_field(
                    table, column["name"], value(1), value(4), role, value(3))
            self.table_status.setText("Сохранено локально")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Бизнес-семантика", str(exc))

    def refresh_metrics(self):
        active = self.metric_list.currentItem().text() if self.metric_list.currentItem() else ""
        self.metric_table.blockSignals(True)
        self.metric_table.clear()
        self.metric_table.addItems(self.logic.project.data.get("selected", []))
        self.metric_table.blockSignals(False)
        self.refresh_metric_columns()
        self.metric_list.blockSignals(True)
        self.metric_list.clear()
        self.metric_list.addItems(sorted(self.logic.data["metrics"]))
        if active:
            matches = self.metric_list.findItems(active, Qt.MatchFlag.MatchExactly)
            if matches:
                self.metric_list.setCurrentItem(matches[0])
        self.metric_list.blockSignals(False)
        if self.metric_list.currentItem():
            self._load_metric(active)

    def refresh_metric_columns(self, *_):
        table = self.metric_table.currentText()
        old = self.metric_column.currentText()
        group = self.metric_group.currentData() or ""
        self.metric_column.clear()
        self.metric_group.clear()
        self.metric_group.addItem("Без группировки", "")
        self.metric_column.addItems([x["name"] for x in self.logic.columns.get(table, [])])
        for col in self.logic.columns.get(table, []):
            label = col["name"]
            field = self.logic.get_field(table, label)
            if field.get("title"):
                label += " · " + field["title"]
            self.metric_group.addItem(label, col["name"])
        if old:
            self.metric_column.setCurrentText(old)
        if group:
            idx = self.metric_group.findData(group)
            if idx >= 0:
                self.metric_group.setCurrentIndex(idx)
        self.metric_column.setEnabled(self.metric_agg.currentData() != "COUNT_ROWS")

    def _load_metric(self, name):
        item = self.logic.data["metrics"].get(name)
        if not item:
            return
        self.metric_name.setText(name)
        self.metric_table.setCurrentText(item["table"])
        self.metric_agg.setCurrentIndex(self.metric_agg.findData(item["aggregation"]))
        self.metric_column.setCurrentText(item.get("column", ""))
        self.metric_description.setPlainText(item.get("description", ""))
        self.metric_unit.setText(item.get("unit", ""))
        self.sql_preview.clear()

    def clear_metric(self):
        self.metric_list.clearSelection()
        self.metric_list.setCurrentRow(-1)
        self.metric_name.clear()
        self.metric_description.clear()
        self.metric_unit.clear()
        self.sql_preview.clear()

    def save_metric(self):
        try:
            self.logic.save_metric(
                self.metric_name.text(), self.metric_table.currentText(),
                self.metric_column.currentText(), self.metric_agg.currentData(),
                self.metric_description.toPlainText(), self.metric_unit.text())
            self.refresh_metrics()
            name = self.metric_name.text().strip()
            matches = self.metric_list.findItems(name, Qt.MatchFlag.MatchExactly)
            if matches:
                self.metric_list.setCurrentItem(matches[0])
            self.make_metric_sql()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Бизнес-метрика", str(exc))

    def remove_metric(self):
        if self.logic.delete_metric(self.metric_name.text().strip()):
            self.clear_metric()
            self.refresh_metrics()

    def make_metric_sql(self):
        try:
            sql = self.logic.compile_metric(
                self.metric_name.text().strip(), self.metric_group.currentData())
            self.sql_preview.setPlainText(sql)
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Генерация SQL", str(exc))

    def copy_metric_sql(self):
        sql = self.sql_preview.toPlainText()
        if not sql:
            self.make_metric_sql()
            sql = self.sql_preview.toPlainText()
        if sql:
            QApplication.clipboard().setText(sql)

    def refresh_relations(self):
        old = self.relation.currentData()
        self.relation.blockSignals(True)
        self.relation.clear()
        selected = set(self.logic.project.data.get("selected", []))
        seen = set()
        for fk in self._fks:
            left = f"{fk['source_schema']}.{fk['source_table']}"
            right = f"{fk['target_schema']}.{fk['target_table']}"
            if left not in selected or right not in selected:
                continue
            cols = (left, fk["source_column"], right, fk["target_column"])
            if cols not in seen:
                seen.add(cols)
                self.relation.addItem(
                    f"{left}.{cols[1]} → {right}.{cols[3]} · FK", cols)
        for link in self.logic.project.data.get("joins", []):
            cols = (link["left"], link["left_column"],
                    link["right"], link["right_column"])
            if cols not in seen and cols[0] in selected and cols[2] in selected:
                seen.add(cols)
                self.relation.addItem(
                    f"{cols[0]}.{cols[1]} → {cols[2]}.{cols[3]} · ручная", cols)
        if old is not None:
            idx = self.relation.findData(old)
            if idx >= 0:
                self.relation.setCurrentIndex(idx)
        self.relation.blockSignals(False)
        self._load_relation()

    def _load_relation(self, *_):
        cols = self.relation.currentData()
        stored = {}
        if cols:
            try:
                key = self.logic.relation_key(*cols)
                stored = self.logic.data["relations"].get(key, {})
            except ValueError:
                pass
        self.relation_description.setPlainText(stored.get("description", ""))
        idx = self.cardinality.findText(stored.get("cardinality", "не задана"))
        self.cardinality.setCurrentIndex(max(0, idx))

    def save_relation(self):
        cols = self.relation.currentData()
        if not cols:
            return
        try:
            self.logic.save_relation(*cols, self.relation_description.toPlainText(),
                                     self.cardinality.currentText())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Бизнес-связи", str(exc))

    def refresh_glossary(self):
        previous = self.terms.currentItem().text() if self.terms.currentItem() else ""
        self.terms.blockSignals(True)
        self.terms.clear()
        self.terms.addItems(sorted(self.logic.data["glossary"]))
        if previous:
            match = self.terms.findItems(previous, Qt.MatchFlag.MatchExactly)
            if match:
                self.terms.setCurrentItem(match[0])
        self.terms.blockSignals(False)

    def _load_term(self, name):
        self.term.setText(name)
        self.term_description.setPlainText(self.logic.data["glossary"].get(name, ""))

    def clear_term(self):
        self.terms.setCurrentRow(-1)
        self.term.clear()
        self.term_description.clear()

    def save_term(self):
        try:
            name = self.term.text().strip()
            self.logic.save_glossary(name, self.term_description.toPlainText())
            self.refresh_glossary()
            matches = self.terms.findItems(name, Qt.MatchFlag.MatchExactly)
            if matches:
                self.terms.setCurrentItem(matches[0])
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Глоссарий", str(exc))

    def delete_term(self):
        if self.logic.delete_glossary(self.term.text()):
            self.clear_term()
            self.refresh_glossary()

    def copy_context(self):
        payload = self.logic.context()
        QApplication.clipboard().setText(
            json.dumps(payload, ensure_ascii=False, indent=2))
        QMessageBox.information(
            self, "Бизнес-контекст",
            "JSON со структурой, описаниями и метриками скопирован. "
            "Строки из PostgreSQL, пароли и значения результатов туда не входят.")
