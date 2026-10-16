"""7.7 real Qt smoke for live drum preview and update dialog (no network)."""
import os
import unittest

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,"PySide6 not available")
class ExperienceQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        cls.qt=QApplication.instance() or QApplication([])

    def test_drum_live_preview_uses_only_examples_and_reflects_style(self):
        from orbit_drum_preview import DrumLivePreview,SAMPLES
        from orbit_drum_layout import normalize_options
        from orbit_appearance import palette
        class App:pass
        app=App();app.palette=palette('midnight');app.drum_style='minimal'
        app.drum_options=normalize_options(None)
        widget=DrumLivePreview(app)
        try:
            self.assertEqual(widget.engine._entries,SAMPLES)
            self.assertFalse(widget.engine.isVisible())
            self.assertIsNotNone(widget.picture.pixmap())
            app.drum_options['shape']='ribbon'
            app.drum_options['header']='hidden'
            app.drum_style='glass'
            widget.repaint_example()
            self.assertEqual(widget.engine.width(),550)
            self.assertEqual(widget.engine.height(),186)
            self.assertEqual(widget.engine.style_name,'glass')
            widget.turn(1)
            self.assertEqual(widget.position,3)
        finally:
            widget.close()
            widget.deleteLater()
            self.qt.processEvents()

    def test_update_dialog_does_not_contact_network_on_construction(self):
        from orbit_update_ui import UpdateWindow
        class App:pass
        widget=UpdateWindow(App())
        try:
            self.assertFalse(widget.busy)
            self.assertFalse(widget.download_button.isEnabled())
            self.assertFalse(widget.install_button.isEnabled())
            self.assertEqual(widget.releases,[])
        finally:
            widget.poller.stop()
            widget.close()
            widget.deleteLater()
            self.qt.processEvents()


if __name__=='__main__':unittest.main()
