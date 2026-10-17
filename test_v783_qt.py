"""Headless Qt smoke: ORBIT Extract window only acts on explicit user commands."""
import os
import unittest
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,'PySide6 not installed')
class ExtractQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.qt=QApplication.instance() or QApplication([])

    def test_result_tabs_copy_and_no_implicit_clipboard_change(self):
        from orbit_extract_ui import ExtractDialog
        class App:
            def __init__(self):self.copied=[]
            def copy_text(self,value):self.copied.append(value)
        app=App()
        dialog=ExtractDialog(app,{'text':'City;Revenue\nMoscow;1200\nOmsk;900',
                                  'encrypted':False})
        try:
            self.assertEqual(dialog.tabs.count(),3)
            self.assertEqual(dialog.table.rowCount(),2)
            self.assertEqual(app.copied,[])
            dialog.copy_table()
            self.assertEqual(app.copied,['City\tRevenue\nMoscow\t1200\nOmsk\t900'])
            dialog.table.setCurrentCell(1,0)
            dialog.copy_cell()
            self.assertEqual(app.copied[-1],'Omsk')
        finally:
            dialog.close()
            dialog.deleteLater()
            self.qt.processEvents()

    def test_encrypted_record_must_not_initialize_extract(self):
        from orbit_extract_ui import ExtractDialog
        with self.assertRaises(ValueError):
            ExtractDialog(None,{'text':'private','encrypted':True})


if __name__=='__main__':unittest.main()
