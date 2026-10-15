"""Screen region capture, local OCR and simple screenshot annotation with Qt.

OCR requires an installed Tesseract executable; never uploads pixels.
"""
import io
from pathlib import Path
from PySide6.QtCore import Qt, QRect, QPoint, QBuffer, QIODevice
from PySide6.QtGui import QPainter, QPen, QColor, QPixmap, QImage
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QInputDialog,QFileDialog,QMessageBox, QApplication)


def recognize_png(png):
    """Pure bytes -> local Tesseract; safe to call from a background worker."""
    try:import pytesseract
    except ImportError:raise RuntimeError('Нужна библиотека pytesseract: pip install pytesseract')
    try:from PIL import Image
    except ImportError:raise RuntimeError('Для OCR требуется Pillow: pip install pillow')
    frame=Image.open(io.BytesIO(png))
    try:return pytesseract.image_to_string(frame,lang='rus+eng').strip()
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError('Установи Tesseract: macOS brew install tesseract tesseract-lang; Windows — Tesseract OCR и PATH')
    except pytesseract.TesseractError as exc:
        raise RuntimeError('Ошибка OCR: '+str(exc)[:180])

def recognize(pixmap):
    buf=QBuffer();buf.open(QIODevice.WriteOnly)
    pixmap.save(buf,'PNG')
    return recognize_png(bytes(buf.data()))

class RegionCapture(QWidget):
    def __init__(self,callback):
        super().__init__(None)
        self.callback=callback
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
        screen=QApplication.primaryScreen()
        self.capture=screen.grabWindow(0)
        self.setGeometry(screen.geometry())
        self.origin=None;self.end=None
        self.setCursor(Qt.CrossCursor)
        self.show();self.raise_();self.activateWindow()
    def paintEvent(self,_):
        p=QPainter(self)
        p.drawPixmap(self.rect(),self.capture)
        p.fillRect(self.rect(),QColor(0,0,0,85))
        if self.origin and self.end:
            rect=QRect(self.origin,self.end).normalized()
            if rect.width()>1 and rect.height()>1:
                p.drawPixmap(rect,self.capture,rect)
                p.setPen(QPen(QColor('#70DBDB'),2));p.drawRect(rect)
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton:self.origin=e.position().toPoint();self.end=self.origin;self.update()
    def mouseMoveEvent(self,e):
        if self.origin:self.end=e.position().toPoint();self.update()
    def mouseReleaseEvent(self,e):
        if e.button()!=Qt.LeftButton or not self.origin:return
        self.end=e.position().toPoint();rect=QRect(self.origin,self.end).normalized().intersected(self.rect())
        if rect.width()<8 or rect.height()<8:return
        # Qt automatically respects the QPixmap devicePixelRatio for high-DPI displays.
        dpr=self.capture.devicePixelRatioF()
        cropped=self.capture.copy(QRect(round(rect.x()*dpr),round(rect.y()*dpr),
                 round(rect.width()*dpr),round(rect.height()*dpr)))
        cropped.setDevicePixelRatio(dpr)
        self.close()
        self.callback(cropped)
    def keyPressEvent(self,e):
        if e.key()==Qt.Key_Escape:self.close()

class ScreenshotEditor(QDialog):
    def __init__(self,pixmap,on_ocr,on_copy=None):
        super().__init__(None)
        self.setWindowTitle('ORBITclip · Редактор снимка')
        self.setWindowFlag(Qt.Window,True)
        self.image=pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        self.undo_stack=[]
        self.on_ocr=on_ocr;self.on_copy=on_copy
        self.mode='pen';self.point=None
        self.resize(max(700,min(1120,self.image.width()+50)),max(480,min(790,self.image.height()+110)))
        lay=QVBoxLayout(self)
        bar=QHBoxLayout()
        for title,mode in [('Карандаш','pen'),('Прямоугольник','rect'),('Стрелка','arrow'),('Текст','text'),('Размытие','blur'),('Обрезка','crop')]:
            b=QPushButton(title);b.clicked.connect(lambda _=False,x=mode:self.set_mode(x));bar.addWidget(b)
        for title,cb in [('↶ Отмена',self.undo),('OCR',self.ocr),('Копировать',self.copy),('Сохранить…',self.save)]:
            b=QPushButton(title);b.clicked.connect(cb);bar.addWidget(b)
        lay.addLayout(bar)
        self.canvas=CaptureCanvas(self)
        lay.addWidget(self.canvas,1)
        lay.addWidget(QLabel('Выделение области уже выполнено · рисунок и надписи сохраняются поверх снимка · Esc закрывает редактор'))
    def set_mode(self,x):self.mode=x
    def snapshot(self):
        self.undo_stack.append(self.image.copy())
        self.undo_stack=self.undo_stack[-12:]
    def undo(self):
        if self.undo_stack:
            self.image=self.undo_stack.pop()
            self.canvas.update()
    def ocr(self):
        try:self.on_ocr(recognize(QPixmap.fromImage(self.image)))
        except Exception as ex:QMessageBox.warning(self,'OCR',str(ex))
    def copy(self):
        QApplication.clipboard().setPixmap(QPixmap.fromImage(self.image))
        if self.on_copy:self.on_copy()
    def save(self):
        target,_=QFileDialog.getSaveFileName(self,'Сохранить снимок',str(Path.home()/'Pictures'/'ORBITclip.png'),'PNG (*.png);;JPEG (*.jpg)')
        if target and not self.image.save(target):QMessageBox.warning(self,'Снимок','Не удалось сохранить файл')

class CaptureCanvas(QWidget):
    def __init__(self,editor):
        super().__init__(editor);self.editor=editor;self.start=None;self.last=None;self.setCursor(Qt.CrossCursor)
    def transform_point(self,at):
        img=self.editor.image
        sx=img.width()/max(self.width(),1);sy=img.height()/max(self.height(),1)
        scale=min(self.width()/img.width(),self.height()/img.height())
        left=(self.width()-img.width()*scale)/2;top=(self.height()-img.height()*scale)/2
        return QPoint(max(0,min(img.width()-1,int((at.x()-left)/scale))),
                      max(0,min(img.height()-1,int((at.y()-top)/scale))))
    def paintEvent(self,e):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor('#10202A'))
        img=self.editor.image
        target=QRect(0,0,round(img.width()*min(self.width()/img.width(),self.height()/img.height())),
                          round(img.height()*min(self.width()/img.width(),self.height()/img.height())))
        target.moveCenter(self.rect().center())
        painter.drawImage(target,img)
    def mousePressEvent(self,e):
        if e.button()!=Qt.LeftButton:return
        self.editor.snapshot()
        self.start=self.transform_point(e.position().toPoint());self.last=self.start
    def mouseMoveEvent(self,e):
        if self.start is None or self.editor.mode!='pen':return
        current=self.transform_point(e.position().toPoint())
        p=QPainter(self.editor.image);p.setPen(QPen(QColor('#FF9F79'),4,Qt.SolidLine,Qt.RoundCap));p.drawLine(self.last,current);p.end()
        self.last=current;self.update()
    def mouseReleaseEvent(self,e):
        if self.start is None:return
        finish=self.transform_point(e.position().toPoint());mode=self.editor.mode
        img=self.editor.image
        p=QPainter(img);p.setPen(QPen(QColor('#FF9F79'),4,Qt.SolidLine,Qt.RoundCap));p.setBrush(Qt.NoBrush)
        if mode=='crop':
            region=QRect(self.start,finish).normalized().intersected(img.rect())
            if region.width()>8 and region.height()>8:
                p.end();self.editor.image=img.copy(region)
        elif mode=='rect':p.drawRect(QRect(self.start,finish).normalized())
        elif mode=='arrow':
            import math
            p.drawLine(self.start,finish)
            angle=math.atan2(finish.y()-self.start.y(),finish.x()-self.start.x())
            for sign in (-1,1):
                a=angle+math.pi+sign*.55
                p.drawLine(finish,QPoint(int(finish.x()+14*math.cos(a)),int(finish.y()+14*math.sin(a))))
        elif mode=='blur':
            p.end()
            try:
                from PIL import Image,ImageFilter
                buffer=QBuffer();buffer.open(QIODevice.WriteOnly);img.save(buffer,'PNG')
                photo=Image.open(io.BytesIO(bytes(buffer.data()))).convert('RGBA')
                region=QRect(self.start,finish).normalized().intersected(img.rect())
                if region.width()>1 and region.height()>1:
                    rectangle=(region.x(),region.y(),region.x()+region.width(),region.y()+region.height())
                    photo.paste(photo.crop(rectangle).filter(ImageFilter.GaussianBlur(14)),rectangle)
                    stream=io.BytesIO();photo.save(stream,format='PNG');img.loadFromData(stream.getvalue(),'PNG')
                    self.editor.image=img
            except ImportError:QMessageBox.warning(self.editor,'Размытие','Нужна библиотека Pillow')
        elif mode=='text':
            p.end();text,ok=QInputDialog.getText(self.editor,'Добавить надпись','Текст:')
            if ok and text:
                p=QPainter(img);p.setPen(QPen(QColor('#FF9F79'),2));font=p.font();font.setPointSize(17);font.setBold(True);p.setFont(font)
                p.drawText(self.start,text[:160]);p.end()
        if p.isActive():p.end()
        self.start=None;self.last=None;self.update()
