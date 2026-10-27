"""Encrypted bridge for KINETIC. Client only. Requires cryptography.

The relay sees room identifiers and ciphertext, never message bodies or filenames.
"""
import base64
import hashlib
import ipaddress
from functools import lru_cache
import json
import os
import queue
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from kinetic_clipboard import private_write
from orbit_file_transfer import MAX_FILE_SIZE, LEGACY_FILE_SIZE, validate_control

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from kinetic_transport import pinned_request, valid_pin
from orbit_tls import public_urlopen
from orbit_version import CLIENT_VERSION

MAX_TEXT_SIZE = 200_000
MAX_PACKET_SIZE = 7 * 1024 * 1024
DB_PATH = Path.home() / '.kinetic_messages.json'
LEGACY_DB_PATH = Path.home() / '.kinetic_messages.sqlite3'


def make_pair_code():
    return secrets.token_urlsafe(24)


def room_id(pair_code):
    return hashlib.sha256(b'kinetic-room-v1:' + pair_code.encode('utf-8')).hexdigest()


@lru_cache(maxsize=8)
def derive_key(pair_code):
    return hashlib.pbkdf2_hmac('sha256', pair_code.encode('utf-8'), b'KINETIC-v1-2026', 140000, 32)


def encrypt_message(data, pair_code):
    plain = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(plain) > MAX_PACKET_SIZE:
        raise ValueError('Слишком большое сообщение для одного пакета.')
    compressed = zlib.compress(plain, level=4)
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(derive_key(pair_code)).encrypt(nonce, compressed, b'KINETIC1')
    return base64.b64encode(nonce + encrypted).decode('ascii')


def decrypt_message(packet, pair_code):
    raw = base64.b64decode(packet, validate=True)
    if len(raw) < 29 or len(raw) > MAX_PACKET_SIZE:
        raise ValueError('Повреждённый или слишком большой пакет')
    encoded = AESGCM(derive_key(pair_code)).decrypt(raw[:12], raw[12:], b'KINETIC1')
    decompressor = zlib.decompressobj()
    data = decompressor.decompress(encoded, MAX_PACKET_SIZE + 1)
    if not decompressor.eof or len(data) > MAX_PACKET_SIZE or decompressor.unconsumed_tail:
        raise ValueError('Слишком большой или повреждённый пакет')
    obj = json.loads(data.decode('utf-8'))
    if not isinstance(obj, dict) or obj.get('kind') not in ('text', 'file', 'file_probe', 'file_chunk', 'file_ack', 'file_ref', 'delivery_text', 'delivery_ack'):
        raise ValueError('Неизвестный формат сообщения')
    if obj['kind'] in ('text','delivery_text') and (not isinstance(obj.get('text'), str) or len(obj['text']) > MAX_TEXT_SIZE):
        raise ValueError('Некорректный текст')
    if obj['kind'] == 'file':
        filename = obj.get('name')
        content = obj.get('bytes')
        if not isinstance(filename, str) or not isinstance(content, str) or len(filename) > 250:
            raise ValueError('Некорректный файл')
        if len(content) > ((LEGACY_FILE_SIZE + 2) // 3 * 4 + 4):
            raise ValueError('Файл слишком большой')
        if len(base64.b64decode(content, validate=True)) > LEGACY_FILE_SIZE:
            raise ValueError('Файл слишком большой')
    if obj['kind'] in ('file_probe','file_chunk','file_ack','file_ref'):
        validate_control(obj)
    if obj['kind'] in ('delivery_text','delivery_ack'):
        identifier=obj.get('delivery_id')
        if (not isinstance(identifier,str) or len(identifier)!=32
                or any(ch not in '0123456789abcdef' for ch in identifier)):
            raise ValueError('Некорректный идентификатор доставки')
    return obj


def _private_http(host):
    if host=='localhost':return True
    try:
        addr=ipaddress.ip_address(host)
        allowed=(ipaddress.ip_network('10.0.0.0/8'), ipaddress.ip_network('172.16.0.0/12'),
                 ipaddress.ip_network('192.168.0.0/16'), ipaddress.ip_network('100.64.0.0/10'),
                 ipaddress.ip_network('127.0.0.0/8'))
        return addr.version==4 and any(addr in network for network in allowed)
    except ValueError:
        return False


def validate_config(url, token, pair_code, tls_pin=""):
    url = url.strip().rstrip('/')
    token = token.strip()
    pair_code = pair_code.strip()
    parsed = urllib.parse.urlparse(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Укажи адрес сервера вида https://clock.example.com')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and _private_http(parsed.hostname)):
        raise ValueError('Без HTTPS разрешены только локальные и Tailscale IP.')
    if tls_pin and (parsed.scheme != 'https' or not valid_pin(tls_pin)):
        raise ValueError('Неверный TLS-отпечаток в настройках')
    if len(token) < 16:
        raise ValueError('Токен сервера должен содержать минимум 16 символов.')
    if len(pair_code) < 24:
        raise ValueError('Код пары должен содержать минимум 24 символа.')
    return {'url':url,'token':token,'pair':pair_code,'room':room_id(pair_code),
            'tls_pin': tls_pin.lower() if tls_pin else ''}


def http_json(config, method, path, payload=None):
    url = config['url'] + path
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': 'Bearer ' + config['token'],
        'Content-Type': 'application/json',
        'User-Agent': 'ORBITclip/'+CLIENT_VERSION,
    })
    timeout = 45 if data is not None and len(data) > 1024*1024 else 15
    if config.get('tls_pin'):
        result = pinned_request(config['url'],method,path,data,dict(req.header_items()),
                                config['tls_pin'],timeout=timeout)
    else:
        with public_urlopen(req, timeout=timeout) as response:
            if int(response.headers.get('Content-Length') or 0) > 9 * 1024 * 1024:
                raise ValueError('Ответ сервера слишком большой')
            result = response.read(9 * 1024 * 1024 + 1)
    if len(result) > 9 * 1024 * 1024:
        raise ValueError('Ответ сервера слишком большой')
    return json.loads(result.decode('utf-8'))


class MessageStore:
    """Client-side encrypted transfer archive in a local owner-only JSON file.

    One-time best-effort migration reads the old SQLite cache without changing it.
    It is local-only and is never uploaded to the relay.
    """
    def __init__(self,path=DB_PATH):
        self.path=Path(path)
        self.rows=[]
        try:
            raw=json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw,dict):self.rows=raw.get('messages',[])
            if not isinstance(self.rows,list):self.rows=[]
        except (OSError,ValueError,UnicodeError):
            self.rows=[]
            if not self.path.exists() and LEGACY_DB_PATH.exists():
                try:
                    with sqlite3.connect(str(LEGACY_DB_PATH)) as conn:
                        records=conn.execute('SELECT place,id,device,timestamp,ciphertext,direction FROM messages ORDER BY id DESC LIMIT 800').fetchall()
                    self.rows=[dict(zip(('place','id','device','ts','payload','direction'),r)) for r in records]
                    self._save()
                except (OSError,sqlite3.Error):pass

    def _save(self):
        private_write(self.path,{'version':5,'messages':self.rows})

    def put(self,place,message,direction,delivery_id=None):
        item_id=int(message['id'])
        if any(i.get('place')==place and int(i.get('id',0))==item_id for i in self.rows):return False
        if delivery_id and any(i.get('place')==place and i.get('direction')==direction
                               and i.get('delivery_id')==delivery_id for i in self.rows):
            return False
        self.rows.insert(0,{'place':place,'id':item_id,'device':message.get('device',''),
             'ts':float(message.get('ts',time.time())),'payload':message['payload'],
             'direction':direction, 'delivery_id':delivery_id or ''})
        counts={};fresh=[]
        for item in self.rows:
            key=item['place'];counts[key]=counts.get(key,0)+1
            if counts[key]<=100:fresh.append(item)
        self.rows=fresh[:1500]
        self._save()
        return True

    def mark_delivered(self,place,delivery_id):
        if not delivery_id:return False
        changed=False
        for item in self.rows:
            if (item.get('place')==place and item.get('direction')=='out'
                    and item.get('delivery_id')==delivery_id
                    and not item.get('delivered')):
                item['delivered']=True
                changed=True
        if changed:self._save()
        return changed

    def set_saved_path(self, place, item_id, path):
        """Bind an already received message to its downloaded local file."""
        for item in self.rows:
            if item.get('place') == place and int(item.get('id',0)) == int(item_id):
                item['saved_path'] = str(path)
                self._save()
                return True
        return False

    def delete(self,place,item_id):
        """Delete a message from the local history only; never remote-delete."""
        prior=len(self.rows)
        self.rows=[r for r in self.rows if not (r.get('place')==place and int(r.get('id',0))==int(item_id))]
        if len(self.rows)!=prior:
            self._save()
            return True
        return False

    def fetch(self,place,limit=50):
        rows=[i for i in self.rows if i.get('place')==place]
        return sorted(rows,key=lambda r:int(r['id']),reverse=True)[:limit]

    def close(self):
        pass


class RemoteBridge:
    """Non-blocking, one background I/O worker; never calls Tk methods."""
    def __init__(self):
        self.tasks = queue.Queue()
        self.events = queue.Queue()
        self.stopping = threading.Event()
        self.online = threading.Event()
        self.online.set()
        self.thread = threading.Thread(target=self._run, daemon=True, name='kinetic-bridge')
        self.thread.start()

    def configure(self, config, device, cursor=0):
        self.tasks.put(('config',config,device,int(cursor)))

    def send_encrypted(self,ciphertext):
        if not self.online.is_set():
            self.events.put(('error','Режим оффлайн: отправка отключена'))
            return
        self.tasks.put(('send_encrypted',ciphertext))

    def send(self, message):
        if not self.online.is_set():
            self.events.put(('error','Режим оффлайн: отправка отключена'))
            return
        self.tasks.put(('send',message))

    def set_online(self, enabled):
        if enabled:
            self.online.set()
        else:
            self.online.clear()
            # Drop requests queued prior to disabling networking.
            retained = []
            while True:
                try: task=self.tasks.get_nowait()
                except queue.Empty: break
                if task[0] not in ('send','send_encrypted'):retained.append(task)
            for task in retained:self.tasks.put(task)

    def stop(self):
        self.stopping.set()
        self.tasks.put(('stop',))
        self.thread.join(timeout=.5)

    def _run(self):
        config = None
        device = None
        cursor = 0
        next_poll = 0
        last_error = None
        while not self.stopping.is_set():
            try:
                task = self.tasks.get(timeout=0.3)
            except queue.Empty:
                task = None
            if task:
                if task[0] == 'stop':
                    break
                if task[0] == 'config':
                    _, config, device, cursor = task
                    last_error = None
                    next_poll = 0
                    self.events.put(('status','Подключение…'))
                if task[0] in ('send','send_encrypted') and config and self.online.is_set():
                    try:
                        encrypted = (task[1] if task[0]=='send_encrypted'
                                     else encrypt_message(task[1],config['pair']))
                        answer = http_json(config,'POST','/v1/push',{
                            'room':config['room'],'device':device,'payload':encrypted})
                        entry = {'id':answer['id'],'ts':answer['ts'],
                                 'device':device,'payload':encrypted}
                        self.events.put(('sent', entry, config['room']))
                    except Exception as exc:
                        self.events.put(('error','Отправка: ' + ('Получатель не в сети — сервер не хранит сообщения' if getattr(exc,'code',None)==409 else str(exc))))
            if config and self.online.is_set() and time.monotonic() >= next_poll:
                next_poll = time.monotonic() + 3
                try:
                    qs = urllib.parse.urlencode({'room':config['room'],'after':cursor,'device':device})
                    answer = http_json(config,'GET','/v1/pull?' + qs)
                    messages = answer.get('messages', [])
                    if not isinstance(messages,list):
                        raise ValueError('Некорректный ответ сервера')
                    max_cursor = cursor
                    for msg in messages:
                        message_id = int(msg['id'])
                        max_cursor = max(max_cursor,message_id)
                        self.events.put(('received',msg,device,config['room']))
                    cursor = max_cursor
                    self.events.put(('cursor',cursor))
                    if last_error is not None:
                        last_error = None
                    self.events.put(('status','Защищено · '+('устройства связаны' if answer.get('peers',0)>0 else 'ожидаем второе устройство')))
                    if len(messages) >= 100:
                        next_poll = time.monotonic() + .1
                except Exception as exc:
                    text = str(exc)
                    if text != last_error:
                        self.events.put(('error','Соединение: ' + text))
                        last_error = text
                    next_poll = time.monotonic() + 5
