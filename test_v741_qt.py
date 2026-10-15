"""Optional Qt offscreen integration: real alpha and wheel animation."""
import os
import unittest

try:
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt, QAbstractAnimation
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, 'PySide6 is unavailable in this test environment')
class DrumQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.qt = QApplication.instance() or QApplication([])

    def test_transparent_window_and_progressive_rotation(self):
        from orbit_drum import DrumBubble
        from orbit_appearance import palette
        class FakeApp: pass
        app=FakeApp();app.clock=QWidget();app.clock.resize(140,48)
        app.clock.move(110,105);app.palette=palette('ice')
        drum=DrumBubble(app)
        try:
            self.assertTrue(bool(drum.windowFlags() & Qt.FramelessWindowHint))
            drum.show_neighbors([{'id':1,'text':'alpha'},{'id':2,'text':'bravo'},
                                 {'id':3,'text':'charlie'}],0,'Все')
            self.qt.processEvents()
            img=QImage(drum.size(),QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            painter=QPainter(img)
            drum.render(painter)
            painter.end()
            self.assertEqual(img.pixelColor(0,0).alpha(),0)
            self.assertGreater(img.pixelColor(195,155).alpha(),20)
            drum.show_neighbors([{'id':1,'text':'alpha'},{'id':2,'text':'bravo'},
                                 {'id':3,'text':'charlie'}],1,'Все',step_hint=1)
            self.assertEqual(drum._target,1)
            self.assertTrue(drum._animation.state()!=QAbstractAnimation.Stopped)
        finally:
            drum.close();app.clock.close()

if __name__=='__main__':unittest.main()
