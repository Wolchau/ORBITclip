"""Optional minimal three-face clipboard carousel; Qt only, no data persistence."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget


class DrumBubble(QWidget):
    """Renders previous/current/next clipboard entries as three drum facets."""
    def __init__(self, app):
        super().__init__(None)
        self.app=app
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating,True)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow,True)
        self.resize(372,220)
        self.items=['','',''];self.heading='Буфер обмена';self.position=''

    def show_neighbors(self, choices, index, category):
        if not choices:return self.show_empty(category)
        n=len(choices);self.position=f'{index+1} / {n}';self.heading=category
        self.items=[self._preview(choices[(index-1)%n]),
                    self._preview(choices[index]),self._preview(choices[(index+1)%n])]
        self._display()

    def _preview(self, item):
        if item.get('encrypted'):return '••• Защищённая запись'
        return ' '.join(str(item.get('text') or item.get('title') or '').split())[:190]

    def show_item(self, item, cat_label, index, total):
        self.heading=cat_label;self.position=f'{index+1} / {total}'
        self.items=['',self._preview(item),''];self._display()

    def show_empty(self, category):
        self.heading=category;self.position='0 / 0'
        self.items=['','Нет записей',''];self._display()

    def _display(self):
        screen=QApplication.screenAt(self.app.clock.frameGeometry().center()) or QApplication.primaryScreen()
        area=screen.availableGeometry()
        cx=max(area.left()+self.width()//2+10,min(area.right()-self.width()//2-10,
                  self.app.clock.frameGeometry().center().x()))
        y=max(area.top()+16,min(area.bottom()-self.height()-16,
              self.app.clock.y()+self.app.clock.height()+10))
        self.move(cx-self.width()//2,y)
        self.update();self.show();self.raise_()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        pal=self.app.palette
        p.setPen(QPen(QColor(pal['border']),1));p.setBrush(QColor(pal['surface']))
        p.drawRoundedRect(self.rect().adjusted(2,2,-3,-3),17,17)
        p.setPen(QColor(pal['muted']));p.setFont(QFont('Arial',9,QFont.DemiBold))
        p.drawText(QRectF(19,10,330,21),Qt.AlignVCenter|Qt.AlignLeft,self.heading)
        p.drawText(QRectF(19,10,330,21),Qt.AlignVCenter|Qt.AlignRight,self.position)
        # Three shallow facets: fore-shortened trapezoids give depth without noise.
        for idx,(y,h,inset) in enumerate(((38,47,15),(87,74,0),(164,43,15))):
            current=idx==1
            face=QPolygonF([QPointF(18+inset,y+7),QPointF(354-inset,y+7),
                            QPointF(354-inset+(9 if idx==0 else -9 if idx==2 else 0),y+h-5),
                            QPointF(18+inset-(9 if idx==0 else -9 if idx==2 else 0),y+h-5)])
            color=QColor(pal['raised'] if current else pal['bg'])
            color.setAlpha(255 if current else 177)
            p.setPen(QPen(QColor(pal['accent'] if current else pal['border']),
                          1.5 if current else 0.7))
            p.setBrush(color);p.drawPolygon(face)
            p.setPen(QColor(pal['text'] if current else pal['muted']))
            p.setFont(QFont('Arial',11 if current else 9,QFont.DemiBold if current else QFont.Normal))
            text=self.items[idx]
            max_char=45 if current else 56
            if len(text)>max_char:text=text[:max_char-1]+'…'
            p.drawText(QRectF(33+inset,y+10,306-2*inset,h-19),Qt.AlignVCenter|Qt.AlignLeft,text)
