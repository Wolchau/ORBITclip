"""Password-protected clipboard entries: per-record scrypt + AES-GCM; never serialize plaintext."""
import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


def _b64(value):
    return base64.b64encode(value).decode('ascii')


def seal_text(text, password):
    if not isinstance(text, str) or not text:
        raise ValueError('Пустая запись')
    if not isinstance(password, str) or len(password)<8:
        raise ValueError('Пароль должен содержать хотя бы 8 символов')
    salt=os.urandom(16)
    nonce=os.urandom(12)
    key=Scrypt(salt=salt,length=32,n=2**15,r=8,p=1).derive(password.encode('utf-8'))
    blob=AESGCM(key).encrypt(nonce,text.encode('utf-8'),b'ORBITclip:secret:v1')
    return {'v':1,'salt':_b64(salt),'nonce':_b64(nonce),'ciphertext':_b64(blob)}


def open_text(bundle, password):
    try:
        if not isinstance(bundle,dict) or bundle.get('v')!=1:
            raise ValueError('Неизвестный формат записи')
        salt=base64.b64decode(bundle['salt'],validate=True)
        nonce=base64.b64decode(bundle['nonce'],validate=True)
        blob=base64.b64decode(bundle['ciphertext'],validate=True)
        if len(salt)!=16 or len(nonce)!=12 or not 16<len(blob)<400000:
            raise ValueError('Повреждённая запись')
        key=Scrypt(salt=salt,length=32,n=2**15,r=8,p=1).derive(password.encode('utf-8'))
        return AESGCM(key).decrypt(nonce,blob,b'ORBITclip:secret:v1').decode('utf-8')
    except (KeyError,UnicodeDecodeError,TypeError) as exc:
        raise ValueError('Запись повреждена') from exc
    except Exception as exc:
        raise ValueError('Неверный пароль или повреждённая запись') from exc
