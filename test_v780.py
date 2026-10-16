"""ORBITclip 7.8 Flow queue behavior and persistence regressions."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from orbit_flow import PasteQueue,QueuePresets
from orbit_version import CLIENT_VERSION


class VisualQueueTests(unittest.TestCase):
    def test_version_and_legacy_pop_semantics(self):
        self.assertEqual(CLIENT_VERSION,'7.8.2')
        q=PasteQueue()
        self.assertTrue(q.push('A'))
        self.assertTrue(q.push('B'))
        self.assertEqual(q.preview(),['A','B'])
        self.assertEqual(q.pop(),'A')
        self.assertEqual((q.completed,q.total,len(q)),(1,2,1))
        self.assertEqual(q.pop(),'B')
        self.assertEqual(q.pop(),None)
        self.assertEqual((q.completed,q.total,len(q)),(2,2,0))

    def test_move_preserves_data_and_targeted_wheel_consume(self):
        q=PasteQueue()
        for name in 'abcd':self.assertTrue(q.push(name))
        entries=q.items()
        q.move(entries[2]['uid'],0)
        self.assertEqual(q.preview(),['c','a','b','d'])
        self.assertEqual(q.take(entries[1]['uid']),'b')
        self.assertEqual(q.preview(),['c','a','d'])
        self.assertEqual(q.total,4)
        self.assertFalse(q.move('missing',0))
        self.assertTrue(q.remove(entries[0]['uid']))
        self.assertEqual(q.preview(),['c','d'])
        self.assertEqual(q.completed,1)

    def test_merge_in_queue_order_and_limit(self):
        q=PasteQueue()
        for x in ('first','second','third','fourth'):q.push(x)
        items=q.items()
        self.assertTrue(q.merge([items[3]['uid'],items[1]['uid']]))
        self.assertEqual(q.preview(),['first','second ↵ fourth','third'])
        self.assertEqual(q.items()[1]['source_id'],'')
        self.assertFalse(q.merge(['missing']))
        self.assertEqual(q.total,3)
        oversized=PasteQueue()
        oversized.push('a'*150000);oversized.push('b'*150000)
        self.assertFalse(oversized.merge([x['uid'] for x in oversized.items()]))

    def test_replace_transactional_and_bounded(self):
        q=PasteQueue();q.push('original')
        self.assertFalse(q.replace([{'text':'ok'},{'text':''}]))
        self.assertEqual(q.preview(),['original'])
        self.assertTrue(q.replace([{'text':'restored','title':'Saved'}]))
        self.assertEqual(q.items()[0]['title'],'Saved')
        self.assertFalse(q.replace([{'text':'x'}]*41))
        q.clear();self.assertEqual(q.total,0)

    def test_named_presets_only_explicitly_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'queues.json'
            presets=QueuePresets(path)
            q=PasteQueue();q.push('private payload','My title')
            self.assertFalse(path.exists())
            presets.save('Monthly report',q)
            self.assertTrue(path.exists())
            if os.name!='nt':self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(presets.all()['Monthly report'][0]['text'],'private payload')
            q.clear()
            self.assertTrue(presets.load('Monthly report',q))
            self.assertEqual(q.preview(),['private payload'])
            self.assertTrue(presets.delete('Monthly report'))
            self.assertFalse(presets.load('Monthly report',q))
            self.assertFalse(presets.delete('Monthly report'))

    def test_invalid_presets_and_protected_source_not_persisted_automatically(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'queues.json'
            presets=QueuePresets(path)
            path.write_text('invalid',encoding='utf-8')
            self.assertEqual(presets.all(),{})
            q=PasteQueue();q.push('plain')
            with self.assertRaises(ValueError):presets.save('x'*61,q)
            self.assertEqual(presets.all(),{})


if __name__=='__main__':unittest.main()
