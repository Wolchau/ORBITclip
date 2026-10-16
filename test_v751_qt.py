"""Qt offscreen regression for ORBITclip 7.5.1 popup models and drum variants."""
import os
import unittest

try:
    from PySide6.QtWidgets import QApplication, QListView, QWidget
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt, QAbstractAnimation
    from PySide6.QtTest import QTest
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, 'PySide6 not installed')
class SelectAndDrumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.qt=QApplication.instance() or QApplication([])
        cls.qt.setProperty('orbit_theme','midnight')

    def test_real_popup_has_options_and_selects_a_row(self):
        from orbit_select import OrbitSelect
        select=OrbitSelect()
        try:
            select.addItem('Первый пункт','one')
            select.addItem('Второй пункт','two')
            select.addItem('Третий пункт','three')
            select.resize(330,44)
            select.show()
            select.showPopup()
            self.qt.processEvents()
            self.assertIsInstance(select.view(),QListView)
            self.assertIs(select.view().model(),select.model())
            self.assertEqual(select.view().model().rowCount(),3)
            rect=select.view().visualRect(select.model().index(1,0))
            self.assertGreater(rect.height(),28)
            self.assertGreater(rect.width(),0)
            image=select.view().viewport().grab().toImage()
            self.assertGreater(image.width(),0)
            QTest.mouseClick(select.view().viewport(),Qt.LeftButton,pos=rect.center())
            self.qt.processEvents()
            self.assertEqual(select.currentData(),'two')
            # Verify restyling doesn't accidentally replace the model.
            select.set_theme('cream')
            self.assertEqual(select.count(),3)
            select.showPopup();self.qt.processEvents()
            self.assertEqual(select.view().model().rowCount(),3)
        finally:
            select.close()

    def test_material_presets_and_category_crossfade(self):
        from orbit_drum import DrumBubble
        from orbit_drum_styles import DRUM_STYLES
        from orbit_appearance import palette
        class App: pass
        app=App();app.clock=QWidget();app.clock.resize(140,48)
        app.clock.move(100,100);app.palette=palette('graphite')
        app.drum_style='minimal';app.animate_drum_categories=True
        drum=DrumBubble(app)
        data=[{'id':'a','text':'SELECT * FROM demo'},
              {'id':'b','text':'long descriptive preview'},
              {'id':'c','text':'another clipboard item'}]
        try:
            drum.show_neighbors(data,0,'Все записи')
            self.qt.processEvents()
            for style in DRUM_STYLES:
                drum.set_style(style)
                image=QImage(drum.size(),QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)
                painter=QPainter(image);drum.render(painter);painter.end()
                self.assertEqual(image.pixelColor(0,0).alpha(),0)
                self.assertGreater(image.pixelColor(195,155).alpha(),15)
            drum.show_neighbors(data,0,'Код')
            self.assertIsNotNone(drum._category_frame)
            self.assertNotEqual(drum._category_animation.state(),QAbstractAnimation.Stopped)
            drum._category_animation.setCurrentTime(110)
            self.qt.processEvents()
            self.assertGreater(drum._category_progress,0)
            self.assertLess(drum._category_progress,1)
            drum.set_category_animation(False)
            self.assertIsNone(drum._category_frame)
        finally:
            drum.close();app.clock.close()


if __name__=='__main__':unittest.main()
