"""Encrypted 40 MiB file transfer regression tests; relay packet cap is unchanged."""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest

from kinetic_remote import (
    MAX_FILE_SIZE, MAX_PACKET_SIZE, LEGACY_FILE_SIZE,
    encrypt_message, decrypt_message,
)
from orbit_file_transfer import (
    FileSender, FileReceiver, CHUNK_BYTES, MAX_CHUNKS, _digest_file,
    validate_control,
)
from orbit_messenger_logic import validate_dropped_files

MiB=1024*1024
KEY='unit-test-'+'x'*30


class TransferTests(unittest.TestCase):
    def test_bounds_and_legacy_message(self):
        self.assertEqual(MAX_FILE_SIZE,40*MiB)
        self.assertEqual(LEGACY_FILE_SIZE,3*MiB)
        self.assertEqual(MAX_CHUNKS,20)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'big.bin'
            with path.open('wb') as stream:stream.truncate(40*MiB)
            valid,bad=validate_dropped_files([path])
            self.assertEqual(len(valid),1)
            self.assertEqual(bad,[])
            with path.open('ab') as stream:stream.write(b'x')
            valid,bad=validate_dropped_files([path])
            self.assertEqual(valid,[])
            self.assertEqual(len(bad),1)
            self.assertIn('40',bad[0][1])
        old={'kind':'file','name':'small.txt',
             'bytes':base64.b64encode(b'legacy').decode('ascii')}
        self.assertEqual(decrypt_message(encrypt_message(old,KEY),KEY),old)

    def test_40_mebibyte_end_to_end_encrypted_chunks_and_local_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original=root/'send'/'example.bin'
            original.parent.mkdir()
            # High-entropy bytes prevent compression from hiding size mistakes.
            with original.open('wb') as out:
                for _ in range(20):out.write(os.urandom(CHUNK_BYTES))
            receiver=FileReceiver(root/'receive')
            sender=FileSender(wait=.3,retries=2)
            delivered=[]
            record_number=[3000]
            payload_sizes=[]
            def relay(payload):
                record_number[0]+=1
                message=encrypt_message(payload,KEY)
                payload_sizes.append(len(message))
                self.assertLessEqual(len(message),MAX_PACKET_SIZE)
                # The relay stores ciphertext only; receiver authenticates each part.
                content=decrypt_message(message,KEY)
                path,created=receiver.accept(content)
                if created:delivered.append(path)
                ack={'kind':'file_ack','transfer_id':payload['transfer_id'],
                     'index':payload['index']}
                ack=decrypt_message(encrypt_message(ack,KEY),KEY)
                sender.acknowledge(ack,{'id':record_number[0],'ts':time.time()})
            sender.start(original,relay,context={'place':'test','secret':KEY})
            until=time.monotonic()+28
            results=[]
            while time.monotonic()<until:
                try:event=sender.events.get(timeout=.3)
                except Exception:continue
                results.append(event)
                if event[0] in ('complete','error'):break
            self.assertTrue(results, 'no events reported')
            self.assertEqual(results[-1][0],'complete',str(results[-1]))
            self.assertEqual(results[-1][3],40*MiB)
            self.assertEqual(len(delivered),1)
            self.assertEqual(delivered[0].stat().st_size,40*MiB)
            self.assertEqual(_digest_file(delivered[0]),_digest_file(original))
            self.assertEqual(len(payload_sizes),20)
            self.assertTrue(all(v<7*MiB for v in payload_sizes))
            self.assertEqual([x[3] for x in results if x[0]=='progress'],list(range(1,21)))
            self.assertEqual(list((root/'receive'/'.orbitclip_incomplete').glob('*.part')),[])

    def test_lost_receipt_causes_retry_but_single_saved_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            path=root/'one.bin';path.write_bytes(b'content')
            receiver=FileReceiver(root/'out')
            sender=FileSender(wait=.01,retries=3)
            count=[0]
            def relay(packet):
                count[0]+=1
                saved,created=receiver.accept(packet)
                if count[0]>=2:
                    sender.acknowledge({'kind':'file_ack',
                                        'transfer_id':packet['transfer_id'],
                                        'index':packet['index']},{'id':5})
            sender.start(path,relay)
            events=[]
            until=time.monotonic()+2
            while time.monotonic()<until:
                try:ev=sender.events.get(timeout=.05)
                except Exception:continue
                events.append(ev)
                if ev[0] in ('complete','error'):break
            self.assertEqual(count[0],2)
            self.assertEqual(events[-1][0],'complete')
            self.assertEqual([p.name for p in (root/'out').glob('*') if p.is_file()],['one.bin'])

    def test_tampered_chunks_rejected_and_no_path_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            receiver=FileReceiver(Path(folder)/'download')
            body=b'hello'
            data={'kind':'file_chunk','transfer_id':'a'*32,
                  'name':'../../../attack.txt','size':len(body),'total':1,
                  'index':0,'sha256':'0'*64,
                  'bytes':base64.b64encode(body).decode('ascii')}
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                receiver.accept(data)
            self.assertFalse((Path(folder)/'attack.txt').exists())
            data['sha256']=hashlib.sha256(body).hexdigest()
            saved,created=receiver.accept(data)
            self.assertTrue(created)
            self.assertEqual(saved.name,'attack.txt')
            self.assertEqual(saved.read_bytes(),body)
            again,new=receiver.accept(data)
            self.assertFalse(new)
            self.assertIsNone(again)
            data['index']=1
            with self.assertRaises(ValueError):
                validate_control(data)

    def test_large_message_packet_not_mistaken_for_legacy_file(self):
        packet={'kind':'file_chunk','transfer_id':'b'*32,'name':'example.bin',
                'size':CHUNK_BYTES,'total':1,'index':0,
                'sha256':hashlib.sha256(b'x'*CHUNK_BYTES).hexdigest(),
                'bytes':base64.b64encode(b'x'*CHUNK_BYTES).decode('ascii')}
        encoded=encrypt_message(packet,KEY)
        self.assertEqual(decrypt_message(encoded,KEY)['kind'],'file_chunk')
        legacy={'kind':'file','name':'big.bin',
                'bytes':base64.b64encode(b'z'*(LEGACY_FILE_SIZE+1)).decode('ascii')}
        with self.assertRaises(ValueError):
            decrypt_message(encrypt_message(legacy,KEY),KEY)


if __name__=='__main__':
    unittest.main()
