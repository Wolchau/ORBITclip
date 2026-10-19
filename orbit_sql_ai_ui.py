"""User-requested local business text-to-SQL workspace, without automatic execution."""
from __future__ import annotations
import queue
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPlainTextEdit,
    QLineEdit, QPushButton, QMessageBox, QSplitter,
)
from orbit_sql_semantics import BusinessSemantics
from orbit_sql_planner import PlanError, SQLPlanner
from orbit_sql_ollama import local_plan


class LocalSQLWorkspace(QWidget):
    def __init__(self,project,catalog,columns,fks,parent=None):
        super().__init__(parent)
        self.planner=SQLPlanner(BusinessSemantics(project,catalog,columns),fks)
        self.events=queue.Queue()
        self.busy=False
        self.last_result=None
        self.question=""
        self.setObjectName("localBusinessSQLWorkspace")
        layout=QVBoxLayout(self)
        title=QLabel("Спросить данные · локальная Ollama")
        title.setStyleSheet("font-size:18px;font-weight:700")
        layout.addWidget(title)
        intro=QLabel(
            "Ollama получает только выбранные таблицы, поля и сохранённые бизнес-описания. "
            "Ни пароль PostgreSQL, ни строки таблиц, ни результаты запросов не передаются. "
            "Модель создаёт план; SQL компилируется после строгой проверки и НЕ выполняется.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form=QFormLayout()
        self.model=QLineEdit("qwen3:4b")
        self.model.setPlaceholderText("qwen3:4b или qwen3:8b")
        form.addRow("Модель Ollama",self.model)
        layout.addLayout(form)
        self.prompt=QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Например: Покажи выручку по клиентам с 1 января 2026, "
            "отсортируй по убыванию суммы.")
        self.prompt.setMaximumHeight(110)
        layout.addWidget(self.prompt)
        buttons=QHBoxLayout()
        self.ask=QPushButton("Сформировать SQL")
        self.ask.clicked.connect(self.ask_model)
        buttons.addWidget(self.ask)
        inspect=QPushButton("Проверить контекст")
        inspect.clicked.connect(self.inspect_context)
        buttons.addWidget(inspect)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.status=QLabel("Готово к запросу · локально")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        splitter=QSplitter(Qt.Vertical)
        self.explanation=QPlainTextEdit()
        self.explanation.setReadOnly(True)
        self.explanation.setPlaceholderText(
            "Здесь будут уточнения модели, допущения и ошибки проверки.")
        self.sql=QPlainTextEdit()
        self.sql.setReadOnly(True)
        self.sql.setPlaceholderText("SQL появится здесь только после проверки плана.")
        splitter.addWidget(self.explanation)
        splitter.addWidget(self.sql)
        splitter.setSizes([145,255])
        layout.addWidget(splitter,1)
        self.clarification=QLineEdit()
        self.clarification.setPlaceholderText("Ответ на уточнение модели, если оно требуется")
        layout.addWidget(self.clarification)
        bottom=QHBoxLayout()
        self.copy=QPushButton("Копировать SQL")
        self.copy.setEnabled(False)
        self.copy.clicked.connect(self.copy_sql)
        bottom.addWidget(self.copy)
        bottom.addStretch()
        layout.addLayout(bottom)
        foot=QLabel(
            "ЧЕРНОВИК: проверь связи, фильтры, определения и ограничения метрик "
            "до выполнения в SQL Studio или другом редакторе. "
            "Сложные CTE и оконные функции пока не поддерживаются.")
        foot.setWordWrap(True)
        layout.addWidget(foot)
        self.poller=QTimer(self)
        self.poller.timeout.connect(self._poll)
        self.poller.start(90)

    def inspect_context(self):
        try:
            context=self.planner.context()
            summary=(f"Таблиц: {len(context['tables'])}, "
                     f"метрик: {len(context['metrics'])}, "
                     f"FK: {len(context['fks'])}, "
                     f"ручных связей: {len(context['manual_joins'])}.")
            self.status.setText(summary)
            self.explanation.setPlainText(
                "Контекст построен из выбранных таблиц и сохранённой бизнес-семантики.\n"
                "Если недостаточно описаний, заполни раздел «Бизнес-семантика».")
        except PlanError as exc:
            self.status.setText(str(exc))

    def ask_model(self):
        if self.busy:return
        self.sql.clear()
        self.copy.setEnabled(False)
        self.last_result=None
        try:
            context=self.planner.context()
            from orbit_sql_ollama import make_request
            question=self.prompt.toPlainText().strip()
            model=self.model.text().strip()
            answer=self.clarification.text().strip()
            make_request(question,context,model,answer)
        except PlanError as exc:
            self.status.setText(str(exc))
            return
        self.busy=True
        self.ask.setEnabled(False)
        self.status.setText("Локальная Ollama строит план…")
        self.explanation.clear()
        def worker():
            try:
                plan=local_plan(question,context,model,answer)
                self.events.put(("plan",plan))
            except Exception as exc:
                self.events.put(("error",str(exc)[:500]))
        threading.Thread(target=worker,name="orbit-sql-local-ollama",daemon=True).start()

    def _poll(self):
        try:status,value=self.events.get_nowait()
        except queue.Empty:return
        self.busy=False
        self.ask.setEnabled(True)
        if status=="error":
            self.status.setText("Проверка не завершена")
            self.explanation.setPlainText(value)
            return
        try:
            result=self.planner.compile(value)
        except (PlanError,KeyError,TypeError,ValueError) as exc:
            self.status.setText("План отклонён — исправь формулировку или бизнес-описания")
            self.explanation.setPlainText(str(exc))
            return
        self.last_result=result
        if result["status"]=="clarify":
            self.status.setText("Модель просит уточнить вопрос")
            self.explanation.setPlainText(result["question"])
            return
        self.status.setText("SQL проверен и готов к ручной проверке (не выполнен)")
        self.sql.setPlainText(result["sql"])
        details=["Подключённые таблицы: "+", ".join(result["joined_tables"])]
        details+=["Допущения:"]+["• "+x for x in result["assumptions"]]
        details+=["Ограничения:"]+["• "+x for x in result["warnings"]]
        self.explanation.setPlainText("\n".join(details))
        self.copy.setEnabled(True)

    def copy_sql(self):
        if self.last_result is not None and self.last_result["status"]=="ready":
            QGuiApplication.clipboard().setText(self.last_result["sql"])
            self.status.setText("SQL скопирован. Исполнение остаётся за пользователем.")
