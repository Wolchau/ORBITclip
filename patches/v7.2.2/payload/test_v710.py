"""ORBITclip 7.1 regression checks runnable without Qt or a network connection."""
from __future__ import annotations
import ast
import json
import tempfile
import unittest
from pathlib import Path
from kinetic_remote import MessageStore,make_pair_code,encrypt_message,decrypt_message
from orbit_version import CLIENT_VERSION

ROOT=Path(__file__).parent
source=(ROOT/'orbitclip.py').read_text(encoding='utf-8')
tree=ast.parse(source)
classes={node.name:node for node in tree.body if isinstance(node,ast.ClassDef)}

def method(cls,name):
    return next(node for node in classes[cls].body if isinstance(node,ast.FunctionDef) and node.name==name)

class MessengerTests(unittest.TestCase):
    def test_protocol_encrypted_replies_and_forwarding(self):
        key=make_pair_code()
        msg={'kind':'text','text':'Готово, посмотри файл','origin':'chat',
             'reply_to':{'own':False,'text':'Когда будет отчёт?'}}
        encrypted=encrypt_message(msg,key)
        self.assertNotIn('Когда будет отчёт?',encrypted)
        self.assertEqual(decrypt_message(encrypted,key),msg)

    def test_local_delete_does_not_destroy_other_messages(self):
        with tempfile.TemporaryDirectory() as d:
            store=MessageStore(Path(d)/'messages.json')
            for i in (1,2,3):
                store.put('one',{'id':i,'ts':10+i,'device':'other','payload':'example'},'in')
            store.put('two',{'id':4,'ts':14,'device':'me','payload':'other'},'out')
            self.assertTrue(store.delete('one',2))
            self.assertFalse(store.delete('one',2))
            self.assertEqual([r['id'] for r in store.fetch('one')],[3,1])
            self.assertEqual(len(MessageStore(Path(d)/'messages.json').fetch('two')),1)

    def test_chat_events_and_persistent_windows_in_source(self):
        self.assertIn('self.setWindowFlag(Qt.Window, True)',ast.get_source_segment(source,classes['ChatWindow']))
        self.assertIn('self.setWindowFlag(Qt.Window, True)',ast.get_source_segment(source,classes['VaultWindow']))
        focus=ast.get_source_segment(source,method('OrbitApp','on_application_state'))
        self.assertNotIn('self.history.hide()',focus)
        self.assertNotIn('self.chat.hide()',focus)
        self.assertIn('self.chat.refresh_messages()',ast.get_source_segment(source,method('OrbitApp','pump_events')))
        self.assertIn('unread_peers=',source)
        self.assertIn('self.reply_to',ast.get_source_segment(source,method('ChatWindow','send_text')))
        self.assertIn('self.app.send_to_peer(',ast.get_source_segment(source,method('ChatWindow','forward_message')))

    def test_unread_model_is_wired(self):
        for name in ('note_incoming','clear_unread','open_tour','send_to_peer'):
            method('OrbitApp',name)
        self.assertIn('self.note_incoming(ident)',source)
        self.assertIn("self.note_incoming('legacy')",source)

class RetiredTourTests(unittest.TestCase):
    def test_animations_intentionally_removed_in_721(self):
        self.assertFalse((ROOT/'assets'/'onboarding').exists())
        self.assertNotIn('FeatureTourWindow',source)
        self.assertNotIn('QMovie',source)

    def test_client_version_updated_without_protocol_change(self):
        self.assertEqual(CLIENT_VERSION,'7.2.2')
        self.assertIn('QT_CLIENT_VERSION = CLIENT_VERSION',source)
        self.assertNotIn('Возможности ✦',source)

if __name__=='__main__':unittest.main(verbosity=2)
