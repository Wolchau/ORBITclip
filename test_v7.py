"""Headless smoke checks: category migration, order persistence and device identities."""
import tempfile
from pathlib import Path
from orbit_categories import CategoryModel,WheelQueue
from orbit_peers import DeviceIdentity
from kinetic_clipboard import ClipboardVault
from kinetic_remote import encrypt_message,decrypt_message

with tempfile.TemporaryDirectory() as root:
    home=Path(root)
    v=ClipboardVault(home/'vault.json')
    sql=v.add('SELECT * FROM records');link=v.add('https://example.org');note=v.add('hello world')
    categories=CategoryModel()
    work=categories.add('Рабочее','code',False)
    v.describe(note['id'],title='Важная заметка',category=work['id'])
    categories2=CategoryModel(categories.categories)
    assert categories2.get(work['id'])['name']=='Рабочее'
    assert work['id'] not in [c['id'] for c in categories2.wheel_categories()]
    assert categories2.matches(v.find(note['id']),work['id'])
    assert not categories2.matches(v.find(sql['id']),work['id'])
    assert len([x for x in v.items if categories2.matches(x,'link')])==1
    assert len([x for x in v.items if categories2.matches(x,'code')])==1
    queue=WheelQueue([],20)
    assert queue.candidates(v.items,categories2)[0]['id']==note['id']
    queue.move_front([sql['id'],note['id']],v.items,categories2)
    assert queue.candidates(v.items,categories2)[0]['id']==sql['id']
    queue2=WheelQueue(queue.manual,20)
    assert queue2.candidates(ClipboardVault(home/'vault.json').items,categories2)[0]['id']==sql['id']
    v.toggle_scroll(sql['id'])
    assert sql['id'] not in [i['id'] for i in queue.candidates(v.items,categories2)]
    a=DeviceIdentity(home/'a.json');b=DeviceIdentity(home/'b.json')
    assert a.id!=b.id
    assert a.public!=b.public
    conf_a=a.pair(b.id,'Лэптоп',b.public)
    conf_b=b.pair(a.id,'Рабочий ПК',a.public)
    assert conf_a['pair']==conf_b['pair']
    packet=encrypt_message({'kind':'text','text':'hello from A','origin':'chat'},conf_a['pair'])
    decoded=decrypt_message(packet,conf_b['pair'])
    assert decoded['text']=='hello from A' and decoded['origin']=='chat'
    assert DeviceIdentity(home/'a.json').trusted[b.id]['pair']==conf_a['pair']
    categories2.delete(work['id'])
    assert categories2.get(work['id']) is None
print('PASS categories, filters, wheel order, exclusions, persistent identity and encrypted direct-peer packets')
