"""Tests that can be run even on a headless system without PySide6."""
from pathlib import Path
import tempfile
from kinetic_clipboard import ClipboardVault
from kinetic_remote import encrypt_message,decrypt_message,make_pair_code,validate_config,MessageStore
from kinetic_pairing import make_invite,parse_invite_detail
from orbit_version import CLIENT_VERSION

def test_models():
    with tempfile.TemporaryDirectory() as folder:
        base=Path(folder)
        v=ClipboardVault(base/'clipboard.json')
        a=v.add('SELECT * FROM sales;')
        b=v.add('https://example.org')
        v.describe(a['id'],'Выручка','Работа')
        v.favorite(a['id']);v.bind(a['id'],'ctrl+alt+1')
        v.toggle_scroll(b['id']);v.toggle_priority(a['id'])
        assert v.scroll_candidates('all',20,5)[0]['id']==a['id']
        assert b['id'] not in [x['id'] for x in v.scroll_candidates('all',20,5)]
        assert v.by_hotkey('ctrl+alt+1')['id']==a['id']
        secret=v.add('not-for-server')
        v.encrypt_item(secret['id'],'password-strong-123')
        assert 'not-for-server' not in (base/'clipboard.json').read_text('utf-8')
        assert v.decrypt_item(secret['id'],'password-strong-123')=='not-for-server'
        assert ClipboardVault(base/'clipboard.json').find(a['id'])['title']=='Выручка'
        code=make_pair_code()
        packet=encrypt_message({'kind':'text','text':'hello'},code)
        assert decrypt_message(packet,code)['text']=='hello'
        cfg=validate_config('https://kinetic-relay.onrender.com','a'*24,code)
        assert parse_invite_detail(make_invite(cfg['url'],'123456'),cfg['url'])[1]=='123456'
        messages=MessageStore(base/'messages.json')
        messages.put('place',{'id':1,'ts':123,'device':'x','payload':packet},'out')
        assert len(MessageStore(base/'messages.json').fetch('place'))==1
        assert CLIENT_VERSION=='7.4.1'
        print('PASS: vault, migration, encryption, favorites, scroll, invites, message store')

if __name__=='__main__':test_models()
