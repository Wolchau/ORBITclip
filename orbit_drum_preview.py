"""Live QPainter preview of the same drum renderer as production.

Uses synthetic example entries only. Private clipboard data is never rendered
in the preferences dialog, logged, or sent anywhere.
"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy

from orbit_appearance import palette
from orbit_drum import DrumBubble


SAMPLES = [
    {"id":"demo1","text":"SELECT city, SUM(revenue) FROM sales GROUP BY city"},
    {"id":"demo2","text":"https://example.org/report/2026"},
    {"id":"demo3","text":"Текстовое сообщение — пример записи в буфере"},
    {"id":"demo4","text":"name, revenue, margin | Москва, 12000, 25%"},
    {"id":"demo5","text":"{\"name\": \"Orbit\", \"enabled\": true}"},
]


class DrumLivePreview(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app=app
        self.position=2
        self.demo=type("PreviewModel",(),{})()
        self.demo.palette=app.palette
        self.demo.drum_style=app.drum_style
        self.demo.drum_options=dict(app.drum_options)
        self.demo.animate_drum_categories=False
        self.engine=DrumBubble(self.demo)
        self.engine._entries=list(SAMPLES)
        self.engine.heading="Пример барабана"
        self.engine.position="3 / 5"
        self.engine._cursor=2.
        self.engine._static_mode=False
        self.engine._category_frame=None
        self.engine._category_progress=1.
        layout=QVBoxLayout(self);layout.setContentsMargins(3,5,3,5)
        header=QHBoxLayout()
        heading=QLabel('Предпросмотр · данные примера')
        heading.setStyleSheet('font-size:11px;font-weight:600')
        header.addWidget(heading);header.addStretch()
        previous=QPushButton('‹')
        previous.setToolTip('Предыдущая запись')
        previous.clicked.connect(lambda:self.turn(-1))
        next_button=QPushButton('›')
        next_button.setToolTip('Следующая запись')
        next_button.clicked.connect(lambda:self.turn(1))
        for control in (previous,next_button):
            control.setFixedSize(29,29)
            header.addWidget(control)
        layout.addLayout(header)
        self.picture=QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setMinimumHeight(220)
        self.picture.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        self.picture.setStyleSheet('background:transparent;border:0')
        layout.addWidget(self.picture)
        self.repaint_example()

    def turn(self,step):
        self.position=(self.position+step)%len(SAMPLES)
        self.repaint_example()

    def repaint_example(self):
        self.demo.palette=self.app.palette
        self.demo.drum_style=self.app.drum_style
        self.demo.drum_options=dict(self.app.drum_options)
        self.engine.set_style(self.demo.drum_style)
        self.engine.set_options(self.demo.drum_options)
        self.engine._entries=list(SAMPLES)
        self.engine.heading="Пример барабана"
        self.engine.position=f'{self.position+1} / {len(SAMPLES)}'
        self.engine._cursor=float(self.position)
        self.engine._static_mode=False
        output=self.engine.render_image()
        pixmap=QPixmap.fromImage(output)
        self.picture.setPixmap(pixmap.scaled(QSize(490,270),
                              Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.picture.setFixedHeight(min(280,max(210,round(output.height()*490/max(1,output.width()))+22)))

    def closeEvent(self,event):
        self.engine.close()
        super().closeEvent(event)
