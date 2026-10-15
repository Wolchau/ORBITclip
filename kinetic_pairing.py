"""KINETIC v2 device pairing with ephemeral X25519 session keys.

An 8-digit code locates a short-lived session on the shared relay.
The encrypted configuration contains the original room secret and relay token.
Compare the *verification fingerprint* through an independent channel to rule
out an active malicious relay swapping public keys.
"""
import base64
import hashlib
import json
import queue
import secrets
import threading
import time
import urllib.parse
import urllib.request
from kinetic_remote import _private_http
from kinetic_transport import pinned_request, valid_pin
from orbit_tls import public_urlopen
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def base64e(buf):
    return base64.urlsafe_b64encode(buf).decode('ascii').rstrip('=')


def base64d(text):
    if not isinstance(text, str) or len(text) > 10000:
        raise ValueError('Недопустимое кодирование')
    return base64.urlsafe_b64decode(text + '='*((-len(text))%4))


def parse_relay(url):
    url = url.strip().rstrip('/')
    p = urllib.parse.urlparse(url)
    if p.scheme != 'https' and not (p.scheme == 'http' and _private_http(p.hostname)):
        raise ValueError('Без HTTPS разрешён только локальный или Tailscale IP')
    if not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/'):
        raise ValueError('Некорректный адрес релея')
    return url


def make_invite(url, code, tls_pin=""):
    # A single paste includes an address but NO secret or server token.
    args={'server':url,'code':code}
    if tls_pin:args['pin']=tls_pin
    return 'kinetic-pair://join?' + urllib.parse.urlencode(args)


def parse_invite(text, known_url=''):
    url,code,_pin=parse_invite_detail(text,known_url)
    return url,code


def parse_invite_detail(text, known_url=''):
    text = text.strip()
    if text.isdigit() and len(text) in (6,8):
        if not known_url:
            raise ValueError('Нет адреса сервера: вставь приглашение-ссылку')
        return parse_relay(known_url), text, ''
    p=urllib.parse.urlparse(text)
    if p.scheme != 'kinetic-pair' or p.netloc != 'join':
        raise ValueError('Вставь PIN из 6 цифр или ссылку-приглашение')
    q=urllib.parse.parse_qs(p.query)
    url=parse_relay(q.get('server',[''])[0]); code=q.get('code',[''])[0]
    if not code.isdigit() or len(code) not in (6,8):
        raise ValueError('Некорректный код приглашения')
    pin=q.get('pin',[''])[0]
    if pin and (not valid_pin(pin) or not url.startswith('https://')):
        raise ValueError('Некорректный отпечаток сертификата в приглашении')
    return url,code,pin.lower()


def req(url,path,data,token='',tls_pin=''):
    payload=json.dumps(data,separators=(',',':')).encode('utf-8')
    if len(payload)>12000:
        raise ValueError('Слишком много данных')
    headers={'Content-Type':'application/json','User-Agent':'ORBITclip/6.0.0'}
    if token:
        headers['Authorization']='Bearer '+token
    r=urllib.request.Request(url+path,data=payload,method='POST',headers=headers)
    if tls_pin:
        raw=pinned_request(url,'POST',path,payload,headers,tls_pin,timeout=7,max_bytes=13000)
    else:
        with public_urlopen(r,timeout=7) as resp:
            raw=resp.read(13000)
    if len(raw)>12000:
        raise ValueError('Ответ сервера слишком велик')
    result=json.loads(raw)
    if not isinstance(result,dict):
        raise ValueError('Неверный ответ сервера')
    return result


def pubkey(private):
    from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
    return private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)


def shared_key(private, owner_public, joiner_public, is_owner):
    other = joiner_public if is_owner else owner_public
    secret=private.exchange(x25519.X25519PublicKey.from_public_bytes(other))
    return HKDF(algorithm=hashes.SHA256(), length=32,
                salt=hashlib.sha256(owner_public+joiner_public).digest(),
                info=b'KINETIC device pairing v2 AES-GCM').derive(secret)


def fingerprint(key):
    # Both endpoints derive this independently; compare it out of band.
    digest=hashlib.sha256(b'KINETIC-fingerprint-v2'+key).hexdigest().upper()
    return '-'.join((digest[:4],digest[4:8],digest[8:12]))


def seal(config,key):
    raw=json.dumps(config,separators=(',',':')).encode('utf-8')
    nonce=secrets.token_bytes(12)
    return base64e(nonce+AESGCM(key).encrypt(nonce,raw,b'KINETIC-v2-pairing'))


def unseal(packet,key):
    raw=base64d(packet)
    if len(raw)<29:
        raise ValueError('Слишком короткий пакет')
    return json.loads(AESGCM(key).decrypt(raw[:12],raw[12:],b'KINETIC-v2-pairing'))


class PairingBridge:
    """Background pairing worker. UI only calls methods and drains .events."""
    def __init__(self):
        self.tasks=queue.Queue();self.events=queue.Queue()
        self.stopped=threading.Event()
        self.online=threading.Event();self.online.set()
        self.worker=threading.Thread(target=self._run,name='kinetic-pairing',daemon=True)
        self.worker.start()

    def create(self,url,token,config): self.tasks.put(('create',url,token,config))
    def join(self,invite,known_url): self.tasks.put(('join',invite,known_url))
    def approve(self): self.tasks.put(('approve',))
    def cancel(self): self.tasks.put(('cancel',))
    def set_online(self,enabled):
        if enabled:self.online.set()
        else:
            self.online.clear()
            # Pending PIN approval must be restarted after reconnect.
            self.tasks.put(('cancel',))
    def stop(self):
        self.stopped.set();self.tasks.put(('stop',));self.worker.join(timeout=1)

    def _run(self):
        session=None
        due=0
        while not self.stopped.is_set():
            try: task=self.tasks.get(timeout=.3)
            except queue.Empty:task=None
            if task:
                try:
                    action=task[0]
                    if action=='stop': break
                    if action=='cancel':
                        session=None;self.events.put(('pair_info','Сопряжение отменено'))
                    if action in ('create','join','approve') and not self.online.is_set():
                        raise ValueError('Режим оффлайн: сопряжение отключено')
                    if action=='create':
                        _,url,token,config=task
                        url=parse_relay(url)
                        if not token or len(token)<16:raise ValueError('Сначала задай токен сервера (16+ символов)')
                        private=x25519.X25519PrivateKey.generate()
                        pin=config.get('tls_pin','')
                        response=req(url,'/v2/pair/start',{'public':base64e(pubkey(private))},token,pin)
                        session={'role':'owner','url':url,'private':private,'token':token,'config':config, 'pin':pin,
                                 'sid':response['sid'],'secret':response['secret'],'code':response['code'],
                                 'expiry':time.monotonic()+int(response.get('expires_in',150)), 'state':'waiting'}
                        self.events.put(('pair_created',response['code'],make_invite(config.get('invite_url',url),response['code'],pin)))
                        due=0
                    if action=='join':
                        _,invite,known_url=task
                        url,code,pin=parse_invite_detail(invite,known_url)
                        private=x25519.X25519PrivateKey.generate()
                        response=req(url,'/v2/pair/join',{'code':code,'public':base64e(pubkey(private))},tls_pin=pin)
                        session={'role':'joiner','url':url,'private':private,'pin':pin,'sid':response['sid'],
                                 'secret':response['secret'],'expiry':time.monotonic()+int(response.get('expires_in',150)),
                                 'state':'waiting'}
                        self.events.put(('pair_info','Запрос отправлен. Подтверди подключение на первом устройстве.'))
                        due=0
                    if action=='approve':
                        if not session or session['role']!='owner' or session['state']!='joined':
                            raise ValueError('Пока нет ожидающего устройства')
                        packet=seal(session['config'],session['key'])
                        req(session['url'],'/v2/pair/approve',{'sid':session['sid'],
                            'secret':session['secret'],'packet':packet},tls_pin=session['pin'])
                        session['state']='approved'
                        self.events.put(('pair_info','Данные отправлены. Сверь проверочный код на втором устройстве.'))
                except Exception as exc:
                    self.events.put(('pair_error',str(exc)))
            if session and self.online.is_set() and time.monotonic() >= due:
                due=time.monotonic()+1.8
                if time.monotonic()>session['expiry']:
                    self.events.put(('pair_error','Время кода истекло. Создай новый.'))
                    session=None
                    continue
                try:
                    status=req(session['url'],'/v2/pair/check',{'sid':session['sid'],
                                   'secret':session['secret'],'role':session['role']},tls_pin=session['pin'])
                    state=status['state']
                    if session['role']=='owner' and state in ('joined','approved') and session['state']=='waiting':
                        owner_public=pubkey(session['private'])
                        joiner_public=base64d(status['joiner_public'])
                        key=shared_key(session['private'],owner_public,joiner_public,True)
                        session['key']=key;session['state']='joined'
                        self.events.put(('pair_joined',fingerprint(key)))
                    if session['role']=='joiner' and state in ('joined','approved') and session['state']=='waiting':
                        owner_public=base64d(status['owner_public'])
                        joiner_public=pubkey(session['private'])
                        key=shared_key(session['private'],owner_public,joiner_public,False)
                        session['key']=key
                        session['state']='verified'
                        self.events.put(('pair_fingerprint',fingerprint(key)))
                    if session['role']=='joiner' and state=='approved' and session['state']=='verified':
                        config=unseal(status['packet'],session['key'])
                        if not isinstance(config,dict) or config.get('url')!=session['url'] or config.get('tls_pin','')!=session['pin']:
                            raise ValueError('Данные сервера в приглашении не совпадают')
                        self.events.put(('pair_ready',config,fingerprint(session['key'])))
                        session['state']='done'
                    if session['state']=='done':session=None
                except Exception as exc:
                    self.events.put(('pair_error','Проверка пары: '+str(exc)))
                    session=None
