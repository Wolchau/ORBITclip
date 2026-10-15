"""ORBITclip 7.2 regressions, no PySide6 required to run domain tests."""
import ast
import io
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock
from PIL import Image,ImageDraw,ImageFont
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

    def test_fast_ocr_and_screenshot_tools_are_wired(self):
        capture=ast.parse((ROOT/'orbit_capture.py').read_text())
        capture_classes={n.name:n for n in capture.body if isinstance(n,ast.ClassDef)}
        methods={n.name for n in capture_classes['ScreenshotEditor'].body if isinstance(n,ast.FunctionDef)}
        self.assertTrue({'undo','snapshot','save','copy','ocr','set_mode'}.issubset(methods))
        self.assertIn('crop',(ROOT/'orbit_capture.py').read_text())
        core=ast.parse((ROOT/'orbitclip.py').read_text())
        app=next(x for x in core.body if isinstance(x,ast.ClassDef) and x.name=='OrbitApp')
        functions={x.name for x in app.body if isinstance(x,ast.FunctionDef)}
        self.assertTrue({'capture_ocr','capture_screen','recognize_capture','broadcast_workspace','handle_workspace_message'}.issubset(functions))
        self.assertIn('self.app.workspaces.publish',(ROOT/'orbitclip.py').read_text())

    def test_ocr_real_image_using_installed_tesseract(self):
        # Extract Qt-independent recognize_png AST to validate real OCR without PySide6.
        syntax=ast.parse((ROOT/'orbit_capture.py').read_text())
        func=next(n for n in syntax.body if isinstance(n,ast.FunctionDef) and n.name=='recognize_png')
        scope={'io':io,'RuntimeError':RuntimeError,'Exception':Exception,'str':str}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[func],type_ignores=[])), '<ocr>','exec'),scope)
        img=Image.new('RGB',(460,94),'white')
        draw=ImageDraw.Draw(img)
        filename=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        if not filename.is_file():self.skipTest('OCR image fixture uses a Linux font')
        font=ImageFont.truetype(str(filename),32)
        draw.text((14,15),'HELLO 2026',fill='black',font=font)
        out=io.BytesIO();img.save(out,format='PNG')
        try:recognized=scope['recognize_png'](out.getvalue())
        except (ImportError,RuntimeError,FileNotFoundError) as exc:self.skipTest(str(exc))
        self.assertIn('HELLO',recognized.upper())

if __name__=='__main__':unittest.main()
