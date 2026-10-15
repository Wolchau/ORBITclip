"""Regression tests for v7.0.4 features; no Qt required."""
import queue
import tempfile
import time
import unittest
from unittest.mock import patch
from orbit_ui_logic import next_nonempty_category, parse_table_preview, safe_web_url
from kinetic_remote import RemoteBridge
from kinetic_pairing import PairingBridge


class CategoryCycle(unittest.TestCase):
    def test_wraps_and_skips_empty(self):
        categories=[('all','Все'),('text','Текст'),('links','Ссылки'),('sql','SQL')]
        present={'all','links'}
        fn=lambda cid:cid in present
        self.assertEqual(next_nonempty_category(categories,0,fn),2)
        self.assertEqual(next_nonempty_category(categories,2,fn),0)
        self.assertEqual(next_nonempty_category(categories,3,fn),0)
        self.assertEqual(next_nonempty_category(categories,1,fn),2)

    def test_everything_empty_stays_visible(self):
        self.assertEqual(next_nonempty_category([('all','Все')],0,lambda _:False),0)
        self.assertEqual(next_nonempty_category([('a','A'),('b','B')],1,lambda _:False),1)
        self.assertEqual(next_nonempty_category([],0,lambda _:False),0)

    def test_only_current_nonempty(self):
        cats=[('a','A'),('b','B'),('c','C')]
        self.assertEqual(next_nonempty_category(cats,1,lambda name:name=='b'),1)


class TablePreview(unittest.TestCase):
    def test_tsv_preview_five_rows(self):
        raw='name\tage\n'+'\n'.join(f'Person {i}\t{i*10}' for i in range(8))
        labels,rows,tail=parse_table_preview(raw)
        self.assertEqual(labels,['name','age'])
        self.assertEqual(len(rows),5)
        self.assertEqual(tail,3)
        self.assertEqual(rows[1],['Person 1','10'])

    def test_csv_quoted_cells(self):
        raw='name,total\n"Hello, world",10\n"More",20'
        labels,rows,tail=parse_table_preview(raw)
        self.assertEqual(rows[0],['Hello, world','10'])

    def test_markdown_table(self):
        result=parse_table_preview('| User | Role |\n| :--- | ---: |\n| Alex | Admin |\n| Sam | Reader |')
        self.assertEqual(result[0],['User','Role'])
        self.assertEqual(result[1][1],['Sam','Reader'])

    def test_plain_text_not_table(self):
        self.assertIsNone(parse_table_preview('Hello world\nAnother line'))

    def test_url_restrictions(self):
        self.assertEqual(safe_web_url('https://example.com/path?q=1'),'https://example.com/path?q=1')
        for text in ('javascript:alert(1)','file:///etc/passwd','https://evil.com\nanything',
                     'https://user:secret@example.com','example.com', 'https://example.com '):
            self.assertFalse(safe_web_url(text),text)


class OfflineTraffic(unittest.TestCase):
    def test_bridge_does_not_contact_server_when_offline(self):
        with patch('kinetic_remote.http_json',side_effect=AssertionError('Network must be off')) as http:
            bridge=RemoteBridge()
            bridge.set_online(False)
            bridge.configure({'url':'https://example.com','token':'t'*24,'room':'a'*64,'pair':'z'*32},'0'*32)
            bridge.send({'kind':'text','text':'never send'})
            time.sleep(.65)
            bridge.stop()
            self.assertEqual(http.call_count,0)

    def test_pairing_bridge_refuses_network_while_offline(self):
        with patch('kinetic_pairing.req',side_effect=AssertionError('Unexpected network')) as http:
            pairing=PairingBridge()
            pairing.set_online(False)
            pairing.create('https://example.com','t'*32,{'url':'https://example.com'})
            time.sleep(.6)
            pairing.stop()
            self.assertEqual(http.call_count,0)


if __name__=='__main__':
    unittest.main(verbosity=2)
