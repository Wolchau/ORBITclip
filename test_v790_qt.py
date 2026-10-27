"""Qt-compatible in-memory two-peer delivery smoke without live relay."""
import tempfile
from pathlib import Path
import unittest
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,'PySide6 not installed')
class ReliableDeliverySmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        cls.qt=QApplication.instance() or QApplication([])

    def test_text_receipt_proof_dedup_no_duplicate_notification(self):
        from orbitclip import OrbitApp
        from orbit_delivery import DurableOutbox
        from kinetic_remote import MessageStore,encrypt_message,decrypt_message
        class FakeBridge:
            def __init__(self):self.sent=[]
            def send(self,payload):self.sent.append(payload)
        secret="local-device-pair-code-with-more-than-24-characters"
        place="f"*64
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            sender=OrbitApp.__new__(OrbitApp)
            recipient=OrbitApp.__new__(OrbitApp)
            sender.store=MessageStore(root/"out.json")
            sender.delivery_outbox=DurableOutbox(root/"queue.json")
            sender.chat=None
            sender.note_incoming=lambda *_:None
            recipient.store=MessageStore(root/"received.json")
            recipient.delivery_outbox=DurableOutbox(root/"recipient-queue.json")
            recipient.chat=None
            notices=[]
            recipient.note_incoming=lambda *_:notices.append("message")
            uid=sender.delivery_outbox.enqueue(
                place,'legacy',secret,{'kind':'text','text':'hello','origin':'chat'})
            packet=sender.delivery_outbox.list()[0]['ciphertext']
            content=decrypt_message(packet,secret)
            transport={'id':54,'ts':2,'device':'sender','payload':packet}
            fake=FakeBridge()
            self.assertTrue(sender.process_delivery_packet(
                content,transport,'out',fake,place,secret))
            self.assertEqual(sender.store.fetch(place)[0]['delivery_id'],uid)
            self.assertTrue(recipient.process_delivery_packet(
                content,transport,'in',fake,place,secret))
            self.assertEqual(notices,['message'])
            self.assertEqual(len(recipient.store.fetch(place)),1)
            duplicate=dict(transport,id=55)
            self.assertTrue(recipient.process_delivery_packet(
                content,duplicate,'in',fake,place,secret))
            self.assertEqual(len(fake.sent),2)
            self.assertEqual(len(recipient.store.fetch(place)),1)
            self.assertEqual(notices,['message'])
            receipt=fake.sent[0]
            ack_transport={'id':56,'ts':4,'device':'receiver',
                           'payload':encrypt_message(receipt,secret)}
            self.assertTrue(sender.process_delivery_packet(
                receipt,ack_transport,'in',fake,place,secret))
            self.assertEqual(sender.delivery_outbox.pending_count(),0)
            self.assertTrue(sender.store.fetch(place)[0]['delivered'])

if __name__=='__main__':unittest.main()
