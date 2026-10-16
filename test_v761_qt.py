"""Qt offscreen rendering smoke test for 7.6.1 shapes and translucency."""
import os
import unittest
try:
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,"PySide6 not installed")
class DrumShapeQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        cls.qt=QApplication.instance() or QApplication([])

    def test_four_shapes_and_no_header(self):
        from orbit_drum import DrumBubble
        from orbit_drum_layout import SHAPES, normalize_options
        from orbit_appearance import palette
        class App:pass
        app=App();app.clock=QWidget()
        app.clock.setGeometry(110,110,140,50)
        app.palette=palette("midnight")
        app.drum_style="minimal"
        app.animate_drum_categories=True
        app.drum_options=normalize_options({"header":"hidden"})
        wheel=DrumBubble(app)
        try:
            data=[{"id":n,"text":f"Clipboard entry {n}"} for n in range(12)]
            wheel.show_neighbors(data,2,"Текст")
            self.qt.processEvents()
            for shape,(name,size) in SHAPES.items():
                wheel.set_options({"shape":shape,"header":"hidden","neighbors":3,
                                   "opacity":93,"neighbor_opacity":65,"neighbor_gap":35})
                self.qt.processEvents()
                self.assertEqual((wheel.width(),wheel.height()),size)
                img=QImage(wheel.size(),QImage.Format_ARGB32_Premultiplied)
                img.fill(Qt.transparent)
                painter=QPainter(img);wheel.render(painter);painter.end()
                self.assertEqual(img.pixelColor(0,0).alpha(),0)
                self.assertGreater(img.pixelColor(size[0]//2,size[1]//2).alpha(),10)
            wheel.set_options({"shape":"classic","header":"minimal","opacity":35})
            self.qt.processEvents()
            img=QImage(wheel.size(),QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            painter=QPainter(img);wheel.render(painter);painter.end()
            self.assertLess(img.pixelColor(195,158).alpha(),150)
        finally:
            wheel.close();app.clock.close()


if __name__=="__main__":unittest.main()
