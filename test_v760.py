"""ORBITclip 7.6.0: workflow, privacy and messenger regressions."""
import ast
import unittest
from pathlib import Path

from orbit_flow import PasteQueue, is_excluded, normalize_exclusions, quick_actions
from orbit_version import CLIENT_VERSION

ROOT=Path(__file__).resolve().parent
CORE=(ROOT/'orbitclip.py').read_text('utf-8')


class FlowTests(unittest.TestCase):
    def test_version_and_nonpersistent_bounded_queue(self):
        self.assertEqual(CLIENT_VERSION,'7.6.3')
        queue=PasteQueue()
        self.assertIsNone(queue.pop())
        self.assertFalse(queue.push(''))
        for i in range(queue.MAX_ITEMS):
            self.assertTrue(queue.push(f'Row {i}'))
        self.assertFalse(queue.push('overflow'))
        self.assertEqual(queue.pop(),'Row 0')
        queue.clear()
        self.assertEqual(len(queue),0)

    def test_exact_source_exclusion(self):
        names=normalize_exclusions(['1Password',' keepassxc ','1password',''])
        self.assertEqual(names,['1password','keepassxc'])
        self.assertTrue(is_excluded('1PASSWORD',names))
        self.assertFalse(is_excluded('1password-other',names))
        self.assertFalse(is_excluded('Неизвестно',names))

    def test_context_actions_are_review_only(self):
        actions=quick_actions('SELECT * FROM sales','sql')
        self.assertIsInstance(actions,list)
        self.assertTrue(all(isinstance(x['result'],str) for x in actions))
        self.assertEqual(quick_actions('A'*210000,'text'),[])

    def test_no_template_engine_and_clipboard_guard(self):
        self.assertIn('if self.paused or time.monotonic() < self.private_until:return',CORE)
        self.assertIn('if is_excluded(source,self.excluded_apps):return',CORE)
        self.assertIn("excluded_apps=self.excluded_apps",CORE)
        self.assertIn('self.paste_queue.clear()',CORE)
        self.assertIn('def open_palette(self):',CORE)
        self.assertNotIn('from orbit_sql_templates',CORE)

    def test_messenger_drop_uses_existing_encrypted_transport(self):
        self.assertIn('def dragEnterEvent(self,event):',CORE)
        self.assertIn('def dropEvent(self,event):',CORE)
        self.assertIn('def send_files(self,paths):',CORE)
        self.assertIn('if size>MAX_FILE_SIZE:',CORE)
        self.assertIn("self.app.send_to_active({",CORE)


if __name__=='__main__':unittest.main()
