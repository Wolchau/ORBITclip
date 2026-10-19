"""ORBITclip 7.4 full release: local-first core, privacy, platform wiring."""
import ast
import tempfile
import unittest
from pathlib import Path
from orbit_version import CLIENT_VERSION
from orbit_appearance import THEMES, normalize_theme, stylesheet, palette
from orbit_notifications import NotificationStore
from orbit_analytics import AnalyticsStore

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'orbitclip.py').read_text('utf-8')
TREE=ast.parse(SRC)
CLASSES={n.name:n for n in TREE.body if isinstance(n,ast.ClassDef)}


def method(name, cls='OrbitApp'):
    obj=next(n for n in CLASSES[cls].body if isinstance(n,ast.FunctionDef) and n.name==name)
    return ast.get_source_segment(SRC,obj)


class Themes(unittest.TestCase):
    def test_palette_count(self):
        self.assertEqual(CLIENT_VERSION,'7.8.4')
        self.assertGreaterEqual(len(THEMES),5)
        self.assertIn('light', THEMES)
        self.assertEqual(normalize_theme('invalid'),'midnight')
    def test_color_substitution(self):
        self.assertEqual(stylesheet('color:#EAF1F5;background:#101923;', 'light'),
                         f"color:{palette('light')['text']};background:{palette('light')['bg']};")
        self.assertNotEqual(palette('graphite')['bg'],palette('ice')['bg'])
    def test_immediate_qt_theme(self):
        self.assertIn('self.qt.setStyleSheet(stylesheet(STYLE,value))',method('set_theme'))
        self.assertIn("appearance_theme=self.appearance_theme",method('save_settings'))


class NotificationTests(unittest.TestCase):
    def test_persists_and_marks_read(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'inbox.sqlite3'
            n=NotificationStore(path)
            item=n.push('messages','Новое сообщение','От устройства')
            self.assertEqual(n.unread(),1)
            n.close()
            n=NotificationStore(path)
            self.assertEqual(n.list()[0]['id'],item)
            n.mark_read(item)
            self.assertEqual(n.unread(),0)
            n.close()
    def test_debounce_and_filters(self):
        with tempfile.TemporaryDirectory() as temp:
            n=NotificationStore(Path(temp)/'n.db')
            self.assertIsNotNone(n.push('spaces','Room',dedupe='room',now=100))
            self.assertIsNone(n.push('spaces','Room',dedupe='room',now=103))
            self.assertEqual(len(n.list(kind='spaces')),1)
            self.assertEqual(n.list(kind='files'),[])
            with self.assertRaises(ValueError):n.push('evil','bad')
            n.clear();self.assertEqual(n.unread(),0)
            n.close()
    def test_no_preview_of_message(self):
        self.assertIn("self.notify('files' if kind=='file' else 'messages',title,peer,",method('note_incoming'))
        self.assertIn("self.tray_icon.showMessage",method('notify'))
        self.assertIn('self.notifications.close()',method('shutdown'))


class AnalyticsTests(unittest.TestCase):
    def test_counts_sources_export_and_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'stats.db'
            a=AnalyticsStore(path)
            a.record('clip_capture','VS Code')
            a.record('clip_capture','VS Code')
            a.record('chat_in')
            self.assertEqual(a.summary(7)['totals']['clip_capture'],2)
            self.assertIn(('VS Code',2),a.summary(7)['sources'])
            a.export_csv(Path(temp)/'stats.csv')
            content=(Path(temp)/'stats.csv').read_text('utf-8-sig')
            self.assertIn('VS Code',content)
            self.assertNotIn('some-secret',content)
            a.reset();self.assertEqual(a.summary(7)['totals']['chat_in'],0)
            a.close()
    def test_disabled_means_no_recording(self):
        with tempfile.TemporaryDirectory() as temp:
            a=AnalyticsStore(Path(temp)/'a.db',enabled=False)
            a.record('chat_in')
            self.assertEqual(a.summary(30)['totals']['chat_in'],0)
            a.enabled=True
            with self.assertRaises(ValueError):a.record('made-up')
            a.close()
    def test_source_names_only_not_text(self):
        self.assertIn("self.analytics.record('clip_capture',source)",SRC)
        self.assertNotIn('vault.items, self.analytics',SRC)


class PlatformTests(unittest.TestCase):
    def test_macos_two_status_icons(self):
        code=method('create_macos_status_icons')
        self.assertIn("icon('clipboard')",code)
        self.assertIn("icon('send')",code)
        self.assertIn('self.chat_status_icon=messenger',code)
        self.assertIn('self.tray_icon=history',code)
    def test_floating_clock_and_hide(self):
        code=method('__init__','OrbitPill')
        self.assertIn('Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint',code)
        self.assertIn('Qt.WA_ShowWithoutActivating',code)
        self.assertIn('self.clock.hide()',method('set_clock_hidden_windows'))
    def test_drum_and_compact_setting(self):
        self.assertIn('DrumBubble(self)',SRC)
        self.assertIn("self.wheel_view=='drum'",SRC)
        self.assertIn("wheel_view=self.wheel_view",SRC)
    def test_independent_sql_explorer(self):
        self.assertIn('def open_sql_explorer(self)',SRC)
        self.assertIn('SQLExplorer()',SRC)
        self.assertIn('from orbit_sql_ui import SQLExplorer',SRC)


if __name__=='__main__':unittest.main()
