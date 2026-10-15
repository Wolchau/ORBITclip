"""v7.0.5: attachment safety, persistent local paths and trackpad responsiveness."""
import base64
import tempfile
import time
import unittest
from pathlib import Path
from orbit_attachments import save_attachment, safe_attachment_name, decode_attachment
from orbit_switcher import ClipboardWheel
from kinetic_remote import MessageStore

class Downloads(unittest.TestCase):
    def test_path_traversal_and_windows_name(self):
        self.assertEqual(safe_attachment_name('../../notes.txt'),'notes.txt')
        self.assertEqual(safe_attachment_name(r'C:\\Windows\\system.ini'),'system.ini')
        self.assertTrue(safe_attachment_name('CON.txt').startswith('_'))

    def test_save_and_collision(self):
        with tempfile.TemporaryDirectory() as d:
            payload={'name':'../../data.csv','bytes':base64.b64encode(b'hello').decode()}
            a=save_attachment(payload,Path(d)/'ORBITclip',100)
            b=save_attachment(payload,Path(d)/'ORBITclip',100)
            self.assertEqual(a.name,'data.csv')
            self.assertEqual(b.name,'data (1).csv')
            self.assertEqual(a.read_bytes(),b'hello')
            self.assertTrue(a.is_relative_to(Path(d)))

    def test_size_and_encoding(self):
        with self.assertRaises(ValueError):decode_attachment({'bytes':'?%%'},10)
        with self.assertRaises(ValueError):decode_attachment({'bytes':base64.b64encode(b'12345').decode()},4)

    def test_store_saved_path_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'history.json'
            store=MessageStore(path=f)
            self.assertTrue(store.put('room',{'id':11,'device':'b','ts':12.0,'payload':'encrypted'},'in'))
            self.assertTrue(store.set_saved_path('room',11,Path(d)/'ORBITclip'/'data.csv'))
            new=MessageStore(path=f)
            self.assertEqual(new.fetch('room')[0]['saved_path'],str(Path(d)/'ORBITclip'/'data.csv'))

class Trackpad(unittest.TestCase):
    def test_tiny_first_motion_steps_immediately(self):
        w=ClipboardWheel()
        with w._lock:w._mac_trackpad_locked(-0.3)
        self.assertEqual(w.events.get_nowait(),('move',1))

    def test_short_swipe_advances_after_guard(self):
        w=ClipboardWheel()
        with w._lock:
            w._mac_trackpad_locked(0.3)
            self.assertEqual(w.events.get_nowait(),('move',-1))
            w._last_step=time.monotonic()-0.08
            w._mac_trackpad_locked(1.8)
        self.assertEqual(w.events.get_nowait(),('move',-1))

if __name__=='__main__':unittest.main()
