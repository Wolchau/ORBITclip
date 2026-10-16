"""ORBITclip 7.2 regressions, no PySide6 required to run domain tests."""
import ast
import io
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock
from kinetic_clipboard import ClipboardVault
from kinetic_remote import encrypt_message,decrypt_message
from orbit_smart import smart_actions
from orbit_workspaces import Workspaces
from orbit_context import foreground_app

ROOT=Path(__file__).parent

class Identity:
    def __init__(self,name):self.id=name*32;self.trusted={}

def link(*identities):
    for a in identities:
        for b in identities:
            if a!=b:a.trusted[b.id]={'name':b.id[:8]}

class WorkspacesTests(unittest.TestCase):
    def test_group_chat_relay_and_private_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            identities=[Identity(x) for x in 'abc'];link(*identities)
            a,b,c=[Workspaces(p,Path(d)/(p.id+'.json')) for p in identities]
            space=a.create('Team',[identities[1].id,identities[2].id]);wid=space['id']
            self.assertEqual(space['clips'],[])
            self.assertEqual(b.receive(identities[0].id,a.invitation(wid)),'invite')
            self.assertEqual(c.receive(identities[0].id,a.invitation(wid)),'invite')
            with self.assertRaises(ValueError):b.chat(wid,'unapproved')
            self.assertEqual(a.receive(identities[1].id,b.decide(wid,True)),'joined')
            self.assertEqual(a.receive(identities[2].id,c.decide(wid,True)),'joined')
            roster=a.envelope(wid,'roster',members=a.spaces[wid]['members'])
            self.assertEqual(b.receive(identities[0].id,roster),'update')
            self.assertEqual(c.receive(identities[0].id,roster),'update')
            packet=b.chat(wid,'Привет от B')
            pair='s'*64
            encrypted=encrypt_message(packet,pair)
            self.assertEqual(decrypt_message(encrypted,pair)['workspace']['entry']['text'],'Привет от B')
            self.assertEqual(a.receive(identities[1].id,decrypt_message(encrypted,pair)),'update')
            forwarded=dict(packet,workspace=dict(packet['workspace'],relay=True))
            self.assertEqual(c.receive(identities[0].id,forwarded),'update')
            self.assertEqual(c.spaces[wid]['messages'][0]['sender'],identities[1].id)
            self.assertEqual(c.receive(identities[0].id,forwarded),'ignored')
            self.assertEqual(c.spaces[wid]['clips'],[])
            clip=a.publish(wid,{'id':'private-item','text':'Only selected fragment','kind':'sql','encrypted':None,'title':'Report'})
            self.assertEqual(b.receive(identities[0].id,clip),'update')
            self.assertEqual(b.spaces[wid]['clips'][0]['title'],'Report')
            self.assertEqual(c.spaces[wid]['clips'],[])
            self.assertEqual(Workspaces(identities[1],Path(d)/(identities[1].id+'.json')).spaces[wid]['clips'][0]['text'],'Only selected fragment')

    def test_add_pending_retry_decline_protect(self):
        with tempfile.TemporaryDirectory() as d:
            owner,guest,third=[Identity(x) for x in 'xyz'];link(owner,guest,third)
            a=Workspaces(owner,Path(d)/'a.json');b=Workspaces(guest,Path(d)/'b.json')
            wid=a.create('Project',[])['id']
            self.assertEqual(a.invite_more(wid,[guest.id,guest.id]),[guest.id])
            self.assertEqual(b.receive(owner.id,a.invitation(wid)),'invite')
            self.assertEqual(b.receive(owner.id,a.invitation(wid)),'invite')
            self.assertEqual(a.receive(guest.id,b.decide(wid,False)),'declined')
            self.assertEqual(a.receive(guest.id,b.chat(wid,'no')) if False else 'blocked','blocked')
            with self.assertRaises(ValueError):a.publish(wid,{'text':'','encrypted':None})
            with self.assertRaises(ValueError):b.chat(wid,'no')
            self.assertEqual(a.invite_more(wid,[third.id]),[third.id])
            self.assertEqual(a.accepted(a.spaces[wid]),[])

    def test_unauthorized_forged_workspace_packet(self):
        with tempfile.TemporaryDirectory() as d:
            owner,guest,outsider=[Identity(x) for x in 'mno'];link(owner,guest)
            a=Workspaces(owner,Path(d)/'a');b=Workspaces(guest,Path(d)/'b')
            s=a.create('Members',[guest.id])
            invite=a.invitation(s['id'])
            self.assertEqual(b.receive(outsider.id,invite),'ignored')
            self.assertEqual(b.receive(owner.id,invite),'invite')
            self.assertEqual(b.receive(guest.id,invite),'ignored')
            self.assertEqual(b.spaces[s['id']]['clips'],[])

class LocalDataTests(unittest.TestCase):
    def test_source_collections_do_not_change_clipboard_privacy(self):
        with tempfile.TemporaryDirectory() as d:
            vault=ClipboardVault(Path(d)/'clipboard.json')
            a=vault.add('SELECT 1',source_app='VS Code')
            b=vault.add('A\tB\n1\t2',source_app='Excel')
            c=vault.add('https://example.com',source_app='Safari')
            self.assertEqual({item['source_app'] for item in vault.items},{'VS Code','Excel','Safari'})
            self.assertEqual(len(ClipboardVault(Path(d)/'clipboard.json').items),3)
            self.assertTrue(all(item.get('category','')=='' for item in vault.items))

    def test_smart_actions_offline_and_preview_only(self):
        actions=smart_actions('https://example.org?a=1&utm_source=x#frag','link')
        self.assertEqual(actions['Удалить трекеры из ссылки'][1],'https://example.org?a=1#frag')
        self.assertIn('Экспорт CSV',smart_actions('Name\tValue\nA\t12','table'))
        self.assertIn('Форматировать SQL',smart_actions('select x from y','sql'))
        self.assertIn('Форматировать JSON',smart_actions('{"a":1}','json'))
        self.assertIn('Проверка JSON',smart_actions('{"missing": }','text'))

    def test_retired_capture_and_ocr_are_absent(self):
        self.assertFalse((ROOT/'orbit_capture.py').exists())
        source=(ROOT/'orbitclip.py').read_text('utf-8')
        self.assertNotIn('capture_ocr',source)
        self.assertNotIn('capture_screen',source)
        self.assertNotIn('ScreenshotEditor',source)
        requirements=(ROOT/'requirements-client.txt').read_text('utf-8').lower()
        self.assertNotIn('pytesseract',requirements)
        self.assertNotIn('pillow',requirements)
        self.assertIn('self.app.workspaces.publish',source)


if __name__=='__main__':unittest.main()
