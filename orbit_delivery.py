"""Private durable outgoing queue for acknowledged ORBITclip peer text messages.

The persisted outbox contains ONLY E2E ciphertext, hashed room location and
peer identifier: never plaintext, room secrets or server credentials.
Relay submission is NOT delivery. A recipient acknowledgement is required.
"""
from __future__ import annotations
import json
from pathlib import Path
import secrets
import time
from kinetic_clipboard import private_write
from kinetic_remote import encrypt_message

DEFAULT_FILE=Path.home()/'.orbitclip_outbox.json'
MAX_QUEUE=80
MAX_TOTAL_BYTES=4*1024*1024
MAX_TEXT=200_000
RETRY_SECONDS=(4,10,25,60,150,300,600,900)


def _uid(value):
    return isinstance(value,str) and len(value)==32 and all(c in '0123456789abcdef' for c in value)


class DurableOutbox:
    def __init__(self,path=DEFAULT_FILE):
        self.path=Path(path)
        try:
            payload=json.loads(self.path.read_text(encoding='utf-8'))
            rows=payload.get('outbox',[]) if isinstance(payload,dict) else []
        except (OSError,ValueError,UnicodeError):
            rows=[]
        self.rows=[]
        if isinstance(rows,list):
            for row in rows[:MAX_QUEUE]:
                if (isinstance(row,dict) and _uid(row.get('id'))
                        and isinstance(row.get('place'),str) and len(row['place'])==64
                        and isinstance(row.get('peer'),str) and len(row['peer'])<=64
                        and isinstance(row.get('ciphertext'),str)
                        and len(row['ciphertext'])<=400_000
                        and isinstance(row.get('created'),(int,float))
                        and isinstance(row.get('attempts'),int) and 0<=row['attempts']<=100_000
                        and isinstance(row.get('next_at'),(int,float))
                        and row['id'] not in {r['id'] for r in self.rows}):
                    self.rows.append(dict(row))

    def _save(self):
        private_write(self.path,{'version':1,'outbox':self.rows})

    def enqueue(self,place,peer,secret,payload,now=None):
        if not isinstance(place,str) or len(place)!=64 or any(c not in '0123456789abcdef' for c in place):
            raise ValueError('Некорректный идентификатор канала')
        if not isinstance(peer,str) or not peer or len(peer)>64:
            raise ValueError('Неизвестный получатель')
        if not isinstance(payload,dict) or payload.get('kind')!='text':
            raise ValueError('В очередь пока можно добавить только текст')
        text=payload.get('text')
        if not isinstance(text,str) or not 1<=len(text)<=MAX_TEXT:
            raise ValueError('Недопустимая длина текста')
        if len(self.rows)>=MAX_QUEUE:
            raise ValueError('Очередь заполнена (80 сообщений)')
        uid=secrets.token_hex(16)
        wire=dict(payload)
        wire['kind']='delivery_text'
        wire['delivery_id']=uid
        packet=encrypt_message(wire,secret)
        if sum(len(r['ciphertext']) for r in self.rows)+len(packet)>MAX_TOTAL_BYTES:
            raise ValueError('Суммарный размер очереди ограничен 4 МБ')
        t=time.time() if now is None else float(now)
        self.rows.append({'id':uid,'place':place,'peer':peer,
                          'ciphertext':packet,'created':t,'attempts':0,
                          'next_at':t,'state':'queued'})
        self._save()
        return uid

    def due(self,now=None,limit=3):
        t=time.time() if now is None else float(now)
        return [dict(r) for r in self.rows if r['next_at']<=t][:max(1,min(10,int(limit)))]

    def mark_attempt(self,uid,now=None):
        t=time.time() if now is None else float(now)
        for row in self.rows:
            if row['id']==uid:
                row['attempts']+=1
                row['next_at']=t+RETRY_SECONDS[min(row['attempts']-1,len(RETRY_SECONDS)-1)]
                row['state']='sending'
                self._save()
                return True
        return False

    def submitted(self,uid):
        for row in self.rows:
            if row['id']==uid:
                row['state']='awaiting_receipt'
                self._save()
                return True
        return False

    def acknowledge(self,place,uid):
        if not _uid(uid):return False
        for row in self.rows:
            if row['id']==uid and row['place']==place:
                self.rows.remove(row)
                self._save()
                return True
        return False

    def cancel(self,uid):
        for row in self.rows:
            if row['id']==uid:
                self.rows.remove(row)
                self._save()
                return True
        return False

    def list(self,place=None):
        return [dict(r) for r in self.rows
                if place is None or r['place']==place]

    def pending_count(self,place=None):
        return len(self.list(place))
