"""Client identity, online roster and voluntary trust between peers.
No private key is sent to the relay; chat encryption remains end to end.
"""
import base64
import hashlib
import json
import queue
import secrets
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from kinetic_clipboard import private_write
from kinetic_remote import http_json

IDENTITY_FILE=Path.home()/'.orbitclip_identity.json'

def encode(buf):return base64.urlsafe_b64encode(buf).decode('ascii').rstrip('=')
def decode(s):return base64.urlsafe_b64decode(s+'='*((-len(s))%4))

class DeviceIdentity:
    def __init__(self,path=IDENTITY_FILE):
        self.path=Path(path)
        try:raw=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError,UnicodeError):raw={}
        secret=raw.get('private') if isinstance(raw,dict) else None
        try:self.private=x25519.X25519PrivateKey.from_private_bytes(decode(secret))
        except (TypeError,ValueError):self.private=x25519.X25519PrivateKey.generate()
        self.public=encode(self.private.public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw))
        self.id=hashlib.sha256(self.public.encode('ascii')).hexdigest()[:32]
        self.name=str(raw.get('name') or socket.gethostname() or 'Мой компьютер')[:32] if isinstance(raw,dict) else 'Мой компьютер'
        self.name_confirmed=bool(raw.get('name_confirmed',False)) if isinstance(raw,dict) else False
        self.trusted=raw.get('trusted',{}) if isinstance(raw,dict) and isinstance(raw.get('trusted'),dict) else {}
        # Never trust malformed persisted records as credentials.
        self.trusted={k:v for k,v in self.trusted.items() if isinstance(v,dict) and
                      isinstance(v.get('public'),str) and len(v['public'])==43 and isinstance(v.get('name'),str)}
        self.save()
    def save(self):
        private=self.private.private_bytes(serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,serialization.NoEncryption())
        private_write(self.path,{'version':1,'private':encode(private),'name':self.name,'name_confirmed':self.name_confirmed,'trusted':self.trusted})
    def rename(self,name):
        n=str(name).strip()[:32]
        if not n or n in ('Мой компьютер','Устройство'):
            raise ValueError('Укажи собственный псевдоним устройства')
        self.name=n;self.name_confirmed=True;self.save()
    def pair(self,device_id,name,peer_public):
        if device_id!=hashlib.sha256(peer_public.encode('ascii')).hexdigest()[:32]:
            raise ValueError('Несовпадение идентификатора и ключа устройства')
        other=x25519.X25519PublicKey.from_public_bytes(decode(peer_public))
        shared=self.private.exchange(other)
        both=sorted((self.public,peer_public))
        salt=hashlib.sha256(('ORBITclip-7:'+both[0]+both[1]).encode()).digest()
        secret=HKDF(algorithm=hashes.SHA256(),length=32,salt=salt,
                    info=b'ORBITclip-v7 trusted peer room').derive(shared).hex()
        self.trusted[device_id]={'name':str(name)[:32],'public':peer_public,
                                 'pair':secret,'added':time.time()}
        self.save()
        return self.trusted[device_id]

class PeerDirectory:
    """All I/O stays outside GUI thread. Events contain roster and invitation changes."""
    def __init__(self,identity,config_factory,version):
        self.identity=identity;self.config_factory=config_factory;self.version=version
        self.events=queue.Queue();self.tasks=queue.Queue();self.stop_flag=threading.Event()
        self.peers=[];self.known_requests=set();self.processed=set()
        self.thread=threading.Thread(target=self._run,daemon=True,name='orbit-directory')
        self.thread.start()
    def discard_pending(self):
        while True:
            try:self.tasks.get_nowait()
            except queue.Empty:break
    def request(self,device_id):self.tasks.put(('request',device_id))
    def respond(self,req_id,accept):self.tasks.put(('respond',req_id,accept))
    def stop(self):self.stop_flag.set();self.thread.join(timeout=1)
    def _call(self,cfg,method,path,obj=None):return http_json(cfg,method,path,obj)
    def _run(self):
        next_run=0
        while not self.stop_flag.wait(.4):
            cfg=self.config_factory()
            if not cfg or not self.identity.name_confirmed:continue
            try:
                if time.monotonic()>=next_run:
                    next_run=time.monotonic()+10
                    ans=self._call(cfg,'POST','/v3/hello',{'device':self.identity.id,
                       'name':self.identity.name,'public':self.identity.public,'version':self.version})
                    peers=ans.get('peers',[])
                    self.events.put(('roster',peers))
                    requests=self._call(cfg,'GET','/v3/requests?'+urlencode({'device':self.identity.id})).get('requests',[])
                    for req in requests:
                        rid=req.get('id')
                        if not rid:continue
                        if req.get('to')==self.identity.id and req.get('status')=='pending' and rid not in self.known_requests:
                            self.known_requests.add(rid);self.events.put(('request',req))
                        if req.get('status')=='accepted' and rid not in self.processed:
                            self.processed.add(rid);self.events.put(('accepted',req))
                        if req.get('status')=='declined' and rid not in self.processed:
                            self.processed.add(rid);self.events.put(('declined',req))
                while True:
                    try:task=self.tasks.get_nowait()
                    except queue.Empty:break
                    if task[0]=='request':
                        result=self._call(cfg,'POST','/v3/request',{'device':self.identity.id,'to':task[1]})
                        self.events.put(('requested',task[1],result.get('id')))
                    elif task[0]=='respond':
                        self._call(cfg,'POST','/v3/respond',{'device':self.identity.id,'id':task[1],'accept':task[2]})
                        self.events.put(('response_sent',task[1],task[2]))
            except Exception as ex:
                self.events.put(('error',str(ex)[:220]))
                next_run=time.monotonic()+8
