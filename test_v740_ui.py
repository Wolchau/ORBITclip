"""Lightweight real Qt smoke test in Linux CI (offscreen), skipped without PySide6."""
import os
import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None, 'PySide6 is not installed in the headless environment')
class UIFunctional740(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.qt=QApplication.instance() or QApplication([])

    def test_notification_center_and_analytics_window(self):
        from orbit_activity_ui import NotificationCenterWindow,AnalyticsWindow
        from orbit_analytics import AnalyticsStore
        from orbit_notifications import NotificationStore
        from orbit_appearance import palette
        with tempfile.TemporaryDirectory() as tmp:
            class FakeApp:
                def open_chat(self):pass
                def open_workspaces(self):pass
                def update_notification_badge(self):pass
                def save_settings(self):pass
            app=FakeApp();app.palette=palette('midnight');app.settings={}
            app.notifications=NotificationStore(Path(tmp)/'notifications.db')
            app.analytics=AnalyticsStore(Path(tmp)/'analytics.db')
            app.notifications.push('messages','Новый файл',description='От устройства')
            app.analytics.record('clip_capture','Editor')
            center=NotificationCenterWindow(app)
            stats=AnalyticsWindow(app)
            self.assertEqual(center.items.count(),1)
            self.assertGreaterEqual(stats.chart.minimumHeight(),100)
            center.select_row(0)
            self.assertEqual(app.notifications.unread(),0)
            stats.range.setCurrentIndex(0)
            stats.refresh()
            stats.close();center.close()
            app.notifications.close();app.analytics.close()

    def test_drum_preview_without_any_clipboard_access(self):
        from orbit_drum import DrumBubble
        from orbit_appearance import palette
        class FakeClock(QWidget):pass
        class FakeApp:pass
        app=FakeApp();app.palette=palette('graphite')
        app.clock=FakeClock();app.clock.move(150,120);app.clock.resize(166,47)
        drum=DrumBubble(app)
        drum.show_neighbors([{'text':'SELECT 1'}, {'text':'hello'}, {'text':'top secret','encrypted':True}],1,'Текст')
        self.assertEqual(drum.items[1],'hello')
        drum.hide();drum.close();app.clock.close()


if __name__=='__main__':unittest.main()
