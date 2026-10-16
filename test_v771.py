"""7.7.1 updater observability regressions (standard library only)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import orbit_update


class UpdateAuditTests(unittest.TestCase):
    def test_bounded_history_and_backup_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            location=Path(tmp)/'history.jsonl'
            with patch.object(orbit_update,'LOG_FILE',location):
                self.assertEqual(orbit_update.read_history(),[])
                for i in range(150):
                    orbit_update.log_update('check','Проверка '+str(i),
                                            old_version='7.7.0',new_version='7.7.1')
                result=orbit_update.read_history(150)
                self.assertEqual(len(result),orbit_update.MAX_LOG_EVENTS)
                self.assertEqual(result[-1]['message'],'Проверка 149')
                self.assertEqual(result[0]['message'],'Проверка 30')
                self.assertTrue(all('time' in v for v in result))
            self.assertEqual(orbit_update.backup_location(tmp),
                             (Path(tmp)/'.orbitclip_patch_backups').resolve())

    def test_log_never_accepts_unknown_events(self):
        with self.assertRaises(ValueError):
            orbit_update.log_update('secret_payload','no')

    def test_callback_receives_real_download_bytes(self):
        class Response:
            headers={'Content-Length':'9'}
            def __init__(self):self.contents=[b'1234',b'56789',b'']
            def __enter__(self):return self
            def __exit__(self,*a):return None
            def read(self,n):return self.contents.pop(0)
        events=[]
        with patch('urllib.request.urlopen',return_value=Response()):
            data=orbit_update._get_bytes(
                orbit_update.API+'/releases/assets/123',
                maximum=100,progress=lambda sent,total:events.append((sent,total)))
        self.assertEqual(data,b'123456789')
        self.assertEqual(events,[(4,9),(9,9)])


if __name__=='__main__':
    unittest.main()
