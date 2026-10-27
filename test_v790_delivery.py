"""7.9.0 reliable peer-message delivery and offline queue regressions."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orbit_delivery import DurableOutbox,MAX_QUEUE
from kinetic_remote import MessageStore,encrypt_message,decrypt_message
from orbit_version import CLIENT_VERSION

PAIR='integration-test-secret-value-more-than-24-chars'
PLACE='a'*64
OTHER='b'*64


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/"queue.json"
        self.box=DurableOutbox(self.path)

    def enqueue(self,text="Message",now=1000):
        return self.box.enqueue(PLACE,'peer-abc',PAIR,
                               {'kind':'text','text':text,'origin':'chat'},now)

    def test_new_version(self):
        self.assertEqual(CLIENT_VERSION,'7.9.0')

    def test_queue_persists_only_ciphertext_without_room_secret(self):
        uid=self.enqueue("confidential-93657")
        data=self.path.read_text(encoding='utf-8')
        self.assertNotIn("confidential-93657",data)
        self.assertNotIn(PAIR,data)
        self.assertIn(uid,data)
        loaded=DurableOutbox(self.path)
        self.assertEqual(loaded.pending_count(),1)
        self.assertEqual(
            decrypt_message(loaded.list()[0]['ciphertext'],PAIR)['text'],
            "confidential-93657")
        self.assertEqual(
            decrypt_message(loaded.list()[0]['ciphertext'],PAIR)['kind'],
            "delivery_text")

    def test_offline_retry_and_explicit_ack(self):
        uid=self.enqueue(now=1234)
        self.assertEqual(len(self.box.due(now=1234)),1)
        self.assertTrue(self.box.mark_attempt(uid,now=1234))
        self.assertEqual(self.box.due(now=1234),[])
        self.assertEqual(len(self.box.due(now=1238)),1)
        self.assertTrue(self.box.submitted(uid))
        self.assertEqual(self.box.pending_count(),1)
        self.assertFalse(self.box.acknowledge(OTHER,uid))
        self.assertEqual(self.box.pending_count(),1)
        self.assertTrue(self.box.acknowledge(PLACE,uid))
        self.assertEqual(self.box.pending_count(),0)
        self.assertEqual(DurableOutbox(self.path).pending_count(),0)

    def test_cancel_and_queue_limit(self):
        ids=[self.enqueue(str(i)) for i in range(MAX_QUEUE)]
        with self.assertRaisesRegex(ValueError,"заполнена"):
            self.enqueue("overflow")
        self.assertTrue(self.box.cancel(ids[8]))
        self.assertFalse(self.box.cancel(ids[8]))
        self.assertEqual(self.box.pending_count(),MAX_QUEUE-1)
        self.enqueue("new")

    def test_invalid_inputs_and_corrupt_json_do_not_send(self):
        with self.assertRaises(ValueError):
            self.box.enqueue(PLACE,'peer',PAIR,{'kind':'file','text':'hi'})
        with self.assertRaises(ValueError):
            self.box.enqueue(PLACE,'peer',PAIR,{'kind':'text','text':''})
        self.path.write_text('{broken json',encoding='utf-8')
        self.assertEqual(DurableOutbox(self.path).list(),[])

    def test_idempotent_store_dedupe_by_client_delivery_id(self):
        uid=self.enqueue()
        with tempfile.TemporaryDirectory() as tmp:
            store=MessageStore(Path(tmp)/'messages.json')
            packet=encrypt_message({'kind':'text','text':'hello'},PAIR)
            self.assertTrue(store.put(PLACE,
                {'id':44,'payload':packet,'ts':5,'device':'sender'},'in',uid))
            self.assertFalse(store.put(PLACE,
                {'id':45,'payload':packet,'ts':6,'device':'sender'},'in',uid))
            self.assertEqual(len(store.fetch(PLACE)),1)
            store2=MessageStore(Path(tmp)/'messages.json')
            self.assertFalse(store2.put(PLACE,
                {'id':46,'payload':packet,'ts':7,'device':'sender'},'in',uid))
            self.assertEqual(len(store2.fetch(PLACE)),1)

    def test_confirmed_delivery_persists_on_outgoing_history(self):
        uid=self.enqueue()
        with tempfile.TemporaryDirectory() as tmp:
            store=MessageStore(Path(tmp)/'messages.json')
            packet=encrypt_message({'kind':'text','text':'hello'},PAIR)
            store.put(PLACE,{'id':98,'payload':packet,'ts':5,'device':'self'},
                      'out',uid)
            self.assertTrue(store.mark_delivered(PLACE,uid))
            self.assertTrue(MessageStore(Path(tmp)/'messages.json').fetch(PLACE)[0]['delivered'])
            self.assertFalse(store.mark_delivered(OTHER,uid))


if __name__=='__main__':
    unittest.main()
