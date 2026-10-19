"""Offscreen end-to-end Qt smoke for the bounded history widget."""
import os
import time
import unittest
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,"PySide6 unavailable")
class HistoryQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        cls.qt=QApplication.instance() or QApplication([])

    def test_search_is_debounced_and_large_history_is_paged(self):
        from orbitclip import VaultWindow, VaultRow
        from orbit_categories import CategoryModel
        from orbit_history_view import PAGE_SIZE
        class Vault:
            def __init__(self):
                now=time.time()
                self.items=[{"id":str(i),"text":"item "+str(i),
                             "title":"","category":"","kind":"text",
                             "source_app":"Browser" if i%2 else "Excel",
                             "ts":now-86400*8 if i<4 else now,
                             "pinned":False,"encrypted":None}
                            for i in range(145)]
            @property
            def favorite_count(self):return 0
        class Workspaces:spaces={}
        class Identity:
            id="local"
            trusted={}
        class App:
            vault=Vault()
            categories=CategoryModel()
            workspaces=Workspaces()
            identity=Identity()
            paused=False
            def __getattr__(self,name):
                return lambda *args,**kwargs:None
        window=VaultWindow(App())
        try:
            self.assertEqual(window.render_limit,PAGE_SIZE)
            rows=lambda:sum(isinstance(window.rows.itemAt(i).widget(),VaultRow)
                            for i in range(window.rows.count())
                            if window.rows.itemAt(i).widget() is not None)
            self.assertEqual(rows(),PAGE_SIZE)
            self.assertIn("40 из 145",window.counter.text())
            window.show_more()
            self.assertEqual(rows(),2*PAGE_SIZE)
            self.assertIn("80 из 145",window.counter.text())
            window.search.setText("item 144")
            self.assertTrue(window.search_timer.isActive())
            # Content is not rebuilt on every keystroke.
            self.assertEqual(rows(),80)
            window.search_timer.stop()
            window.refresh()
            self.assertEqual(rows(),1)
            self.assertEqual(window.render_limit,PAGE_SIZE)
            window.search.clear()
            window.search_timer.stop()
            window.refresh()
            window.period_combo.setCurrentIndex(2) # last seven days
            self.assertEqual(rows(),PAGE_SIZE)
            self.assertIn("40 из 141",window.counter.text())
            window.space_mode='apps';window.source_app='Excel'
            window.refresh()
            self.assertIn("из 71",window.counter.text())
            self.assertLessEqual(rows(),PAGE_SIZE)
        finally:
            window.close()
            window.deleteLater()
            self.qt.processEvents()

if __name__=="__main__":unittest.main()
