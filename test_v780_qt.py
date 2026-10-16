"""Offscreen queue editor smoke, including persistent selection and wheel mode."""
import os
import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,'Qt unavailable')
class QueueQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.qt=QApplication.instance() or QApplication([])

    def test_queue_editor_edit_and_preview_and_mode(self):
        from orbit_flow import PasteQueue,QueuePresets
        from orbit_queue_ui import PasteQueueWindow
        class App:
            def __init__(self,path):
                self.paste_queue=PasteQueue()
                self.paste_queue.push('First line','One')
                self.paste_queue.push('Second line','Two')
                self.paste_queue.push('Third line','Three')
                self.queue_presets=QueuePresets(path)
                self.queue_wheel_mode=False
                self.copied=[]
            def queue_changed(self):pass
            def set_queue_wheel_mode(self,value):self.queue_wheel_mode=bool(value)
            def copy_text(self,text):self.copied.append(text)
            def clear_paste_queue(self):self.paste_queue.clear()
        with tempfile.TemporaryDirectory() as td:
            app=App(Path(td)/'saved.json')
            window=PasteQueueWindow(app)
            try:
                self.assertEqual(window.list.count(),3)
                self.assertIn('First line',window.preview.toPlainText())
                window.shift(1)
                self.assertEqual(app.paste_queue.preview(),['Second line','First line','Third line'])
                window.drum_button.click()
                self.assertTrue(app.queue_wheel_mode)
                self.assertIn('очередь',window.drum_button.text())
                window.copy_next()
                self.assertEqual(app.copied,['Second line'])
                self.assertEqual(app.paste_queue.completed,1)
                self.assertEqual(window.list.count(),2)
                self.assertIn('1 / 3',window.counter.text())
                window.delete_selected()
                self.assertEqual(len(app.paste_queue),1)
            finally:
                window.close()
                window.deleteLater()
                self.qt.processEvents()


if __name__=='__main__':
    unittest.main()
