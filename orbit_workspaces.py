"""Explicitly shared workspaces over existing authenticated per-peer encrypted channels.

No automatic sharing. A private ClipboardVault remains private. Online peers only.
"""
from pathlib import Path
import json
import time
import uuid
from kinetic_clipboard import private_write

FILE=Path.home()/'.orbitclip_workspaces.json'
EVENTS={'invite','accept','decline','roster','chat','clip'}

class Workspaces:
    def __init__(self,identity,path=FILE):
        self.identity=identity
        self.path=Path(path)
        try:raw=json.loads(self.path.read_text(encoding='utf-8'))
        except (ValueError,OSError,UnicodeError):raw={}
        self.spaces=raw.get('spaces',{}) if isinstance(raw,dict) and isinstance(raw.get('spaces'),dict) else {}
        self.save()
    def save(self):private_write(self.path,{'version':1,'spaces':self.spaces})
    def create(self,name,peers):
        name=str(name).strip()[:64]
        if not name:raise ValueError('Укажи название рабочего пространства')
        peers=list(dict.fromkeys(x for x in peers if x!=self.identity.id and x in self.identity.trusted))
        wid=uuid.uuid4().hex
        self.spaces[wid]={'id':wid,'name':name,'owner':self.identity.id,'members':{self.identity.id:'accepted',**{p:'pending' for p in peers}},'messages':[],'clips':[],'seen':[],'created':time.time()}
        self.save();return self.spaces[wid]
    def accepted(self,space):return [k for k,v in space['members'].items() if v=='accepted' and k!=self.identity.id]
    def invite_more(self,wid,peer_ids):
        """Owner can explicitly invite new trusted devices; never auto-publish history."""
        space=self.spaces.get(wid)
        if not space or space['owner']!=self.identity.id:
            raise ValueError('Добавлять участников может только создатель пространства')
        additions=[]
        for pid in dict.fromkeys(peer_ids):
            if pid in space['members'] or pid not in self.identity.trusted:continue
            if len(space['members'])>=30:raise ValueError('Максимум 30 участников')
            space['members'][pid]='pending';additions.append(pid)
        if additions:self.save()
        return additions
    def invitation(self,wid):
        space=self.spaces[wid]
        if space['owner']!=self.identity.id:raise ValueError('Только создатель отправляет приглашения')
        return self.envelope(wid,'invite',name=space['name'])
    def envelope(self,space_id,event,**kwargs):
        if event not in EVENTS:raise ValueError('unsupported workspace event')
        return {'kind':'text','origin':'workspace','text':'','workspace':{'id':space_id,'event':event,'from':self.identity.id,'ts':time.time(),**kwargs}}
    def publish(self,wid,item):
        space=self.spaces.get(wid)
        if not space or space['members'].get(self.identity.id)!='accepted':raise ValueError('Нет доступа к пространству')
        if item.get('encrypted') or not item.get('text'):raise ValueError('Защищённую запись публиковать нельзя')
        entry={'id':uuid.uuid4().hex,'sender':self.identity.id,'text':item['text'][:200000],
               'kind':item.get('kind','text'),'title':item.get('title','')[:90],'ts':time.time()}
        self._record(space,'clips',entry)
        return self.envelope(wid,'clip',entry=entry)
    def chat(self,wid,text):
        space=self.spaces.get(wid)
        if not space or space['members'].get(self.identity.id)!='accepted':raise ValueError('Нет доступа к пространству')
        content=str(text).strip()
        if not content or len(content)>100000:raise ValueError('Сообщение пустое или слишком длинное')
        entry={'id':uuid.uuid4().hex,'sender':self.identity.id,'text':content,'ts':time.time()}
        self._record(space,'messages',entry)
        return self.envelope(wid,'chat',entry=entry)
    def _record(self,space,bucket,entry):
        if not isinstance(entry,dict) or not isinstance(entry.get('id'),str) or not isinstance(entry.get('text'),str):return False
        if len(entry['text'])>200000:return False
        if any(x.get('id')==entry['id'] for x in space[bucket]):return False
        space[bucket].append(entry)
        space[bucket]=space[bucket][-500:];self.save();return True
    def receive(self,peer_id,data):
        """Only invoke AFTER AES-GCM decryption on authenticated channel for peer_id.
        Returns invite, joined, declined, update, ignored.
        """
        if peer_id not in self.identity.trusted or not isinstance(data,dict):return 'ignored'
        if data.get('kind')!='text' or data.get('origin')!='workspace':return 'ignored'
        e=data.get('workspace')
        if not isinstance(e,dict) or e.get('event') not in EVENTS:return 'ignored'
        wid=e.get('id')
        if not isinstance(wid,str) or len(wid)!=32:return 'ignored'
        relayed=(e.get('relay') is True and self.spaces.get(wid,{}).get('owner')==peer_id)
        if e.get('from')!=peer_id and not relayed:return 'ignored'
        event=e['event'];space=self.spaces.get(wid)
        if event=='invite':
            if space:
                # The owner can retry an invite after the guest went offline.
                return 'invite' if (space.get('owner')==peer_id and
                    space['members'].get(self.identity.id)=='pending') else 'ignored'
            if not isinstance(e.get('name'),str):return 'ignored'
            self.spaces[wid]={'id':wid,'name':e['name'][:64],'owner':peer_id,
             'members':{peer_id:'accepted',self.identity.id:'pending'},'messages':[],
             'clips':[],'seen':[],'created':time.time()}
            self.save();return 'invite'
        if not space:return 'ignored'
        if event in ('accept','decline'):
            if space['owner']!=self.identity.id or space['members'].get(peer_id)!='pending':return 'ignored'
            space['members'][peer_id]='accepted' if event=='accept' else 'declined';self.save()
            return 'joined' if event=='accept' else 'declined'
        if event=='roster':
            if peer_id!=space['owner']:return 'ignored'
            new=e.get('members',{})
            if not isinstance(new,dict) or len(new)>40:return 'ignored'
            # Owner is the authoritative membership coordinator, no private keys exchanged.
            space['members']={k:v for k,v in new.items() if isinstance(k,str) and len(k)==32
                 and isinstance(v,str) and v in ('accepted','pending','declined')}
            if space['members'].get(self.identity.id) not in ('accepted','pending'):return 'ignored'
            self.save();return 'update'
        if space['members'].get(self.identity.id)!='accepted' or space['members'].get(peer_id)!='accepted':return 'ignored'
        if relayed and space['members'].get(e.get('from'))!='accepted':return 'ignored'
        if event in ('chat','clip'):
            entry=e.get('entry',{})
            if not isinstance(entry,dict) or entry.get('sender')!=e.get('from'):return 'ignored'
            return 'update' if self._record(space,'messages' if event=='chat' else 'clips',entry) else 'ignored'
        return 'ignored'
    def decide(self,wid,accept):
        space=self.spaces[wid]
        if space['members'].get(self.identity.id)!='pending':raise ValueError('Приглашение уже обработано')
        space['members'][self.identity.id]='accepted' if accept else 'declined';self.save()
        return self.envelope(wid,'accept' if accept else 'decline')
