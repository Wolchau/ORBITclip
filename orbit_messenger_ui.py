"""Attachment review before sending; avoids silent drag-and-drop uploads.

This dialog never opens or decodes file contents. It only checks filenames
and size; final send repeats those checks before reading each file.
"""
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QListWidget,QListWidgetItem
from orbit_messenger_logic import validate_dropped_files


class FileReviewDialog(QDialog):
    def __init__(self,files,rejected,parent=None):
        super().__init__(parent)
        self.setWindowTitle("ORBITclip · Отправка файлов")
        self.resize(490,380)
        layout=QVBoxLayout(self)
        title=QLabel(f"Отправить {len(files)} файлов?")
        title.setStyleSheet("font-weight:700;font-size:16px")
        layout.addWidget(title)
        total=sum(size for _,size in files)
        details=QLabel(f"Размер: {total/1024:.1f} КБ · каждому файлу установлен лимит 3 МБ. "
                       "Отправка выполняется только после подтверждения.")
        details.setWordWrap(True)
        layout.addWidget(details)
        listings=QListWidget()
        for path,size in files:
            listings.addItem(QListWidgetItem(f"📎  {path.name}    ·    {size/1024:.1f} КБ"))
        for name,reason in rejected:
            listings.addItem(QListWidgetItem(f"✕  {name}    ·    {reason}"))
        layout.addWidget(listings,1)
        buttons=QHBoxLayout()
        buttons.addStretch()
        no=QPushButton("Отмена");no.clicked.connect(self.reject)
        buttons.addWidget(no)
        yes=QPushButton("Отправить")
        yes.setEnabled(bool(files))
        yes.clicked.connect(self.accept)
        buttons.addWidget(yes)
        layout.addLayout(buttons)
