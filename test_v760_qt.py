"""Real PySide6 offscreen smoke tests for Flow palette and distinct drum skins."""
import os
import unittest
try:
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,'PySide6 not available')
class QtFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.qt=QApplication.instance() or QApplication([])

    def test_command_palette_filters_and_queues(self):
        from orbit_palette import CommandPalette
        from orbit_flow import PasteQueue
        class V:
            items=[
                {'id':'a','text':'SELECT amount FROM sales','kind':'sql',
                 'source_app':'VS Code','ts':100,'pinned':True},
                {'id':'b','text':'Simple greeting','kind':'text',
                 'source_app':'Notes','ts':80,'pinned':False},
            ]
            def find(self,ident):
                return next((item for item in self.items if item['id']==ident),None)
        class App:
            def __init__(self):
                self.clock=QWidget();self.clock.resize(140,48)
                self.vault=V();self.paste_queue=PasteQueue();self.copied=[]
                self.toast=type('Toast',(),{'pop':lambda self,msg:None})()
            def copy_text(self,text):self.copied.append(text)
        app=App();w=CommandPalette(app)
        try:
            w.open_palette()
            self.qt.processEvents()
            w.search.setText('SELECT')
            self.qt.processEvents()
            self.assertEqual(w.results.count(),1)
            w.queue_selected()
            self.assertEqual(len(app.paste_queue),1)
            self.assertIn('SELECT',app.paste_queue.pop())
            w.copy_selected()
            self.assertIn('SELECT',app.copied[-1])
        finally:
            w.close();app.clock.close()

    def test_material_styles_really_change_pixels(self):
        from orbit_drum import DrumBubble
        from orbit_drum_styles import DRUM_STYLES
        from orbit_appearance import palette
        class App:pass
        app=App();app.clock=QWidget();app.clock.resize(135,47)
        app.clock.move(75,80);app.palette=palette('midnight')
        app.drum_style='minimal';app.animate_drum_categories=True
        drum=DrumBubble(app)
        entries=[{'id':i,'text':f'Item {i} clipboard'} for i in range(3)]
        signatures=[]
        try:
            drum.show_neighbors(entries,0,'Текст')
            self.qt.processEvents()
            for key in DRUM_STYLES:
                drum.set_style(key)
                picture=QImage(drum.size(),QImage.Format_ARGB32_Premultiplied)
                picture.fill(Qt.transparent)
                painter=QPainter(picture)
                drum.render(painter);painter.end()
                self.assertEqual(picture.pixelColor(0,0).alpha(),0)
                pixels=tuple(picture.pixelColor(x,y).name(QImagePixelName) if False else
                             picture.pixelColor(x,y).rgba()
                             for x,y in ((195,124),(195,158),(195,189),(50,158)))
                signatures.append(pixels)
            self.assertEqual(len(set(signatures)),len(DRUM_STYLES))
        finally:
            drum.close();app.clock.close()


if __name__=='__main__':unittest.main()
