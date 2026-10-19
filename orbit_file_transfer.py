"""Encrypted, acknowledged file transfer in bounded relay-compatible chunks.

The relay never sees plaintext. Each individual packet fits its original
7-MiB limit. Receiver writes to disk incrementally; chat history stores
only a small encrypted file reference, never megabytes of chunk packets.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import math
import os
from pathlib import Path
import queue
import secrets
import shutil
import threading
import time

from orbit_attachments import safe_attachment_name

MAX_FILE_SIZE = 40 * 1024 * 1024
LEGACY_FILE_SIZE = 3 * 1024 * 1024
CHUNK_BYTES = 2 * 1024 * 1024
MAX_CHUNKS = (MAX_FILE_SIZE + CHUNK_BYTES - 1) // CHUNK_BYTES
MAX_ACTIVE = 4
TRANSFER_TIMEOUT = 300
ACK_WAIT = 20
RETRIES = 3


def _identity(text):
    if not isinstance(text,str) or len(text)!=32 or any(c not in '0123456789abcdef' for c in text):
        raise ValueError('Некорректный идентификатор передачи')
    return text


def _digest_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(CHUNK_BYTES),b''):
            digest.update(chunk)
    return digest.hexdigest()


def _checked_chunk(packet):
    if not isinstance(packet,dict) or packet.get('kind')!='file_chunk':
        raise ValueError('Некорректный фрагмент файла')
    tid=_identity(packet.get('transfer_id'))
    name=packet.get('name')
    size=packet.get('size')
    index=packet.get('index')
    total=packet.get('total')
    sha=packet.get('sha256')
    encoded=packet.get('bytes')
    if (not isinstance(name,str) or not (1<=len(name)<=250)
            or not isinstance(size,int) or isinstance(size,bool) or not 1<=size<=MAX_FILE_SIZE
            or not isinstance(index,int) or isinstance(index,bool)
            or not isinstance(total,int) or isinstance(total,bool)
            or total!=(size+CHUNK_BYTES-1)//CHUNK_BYTES
            or not 1<=total<=MAX_CHUNKS or not 0<=index<total
            or not isinstance(sha,str) or len(sha)!=64
            or any(x not in '0123456789abcdef' for x in sha)
            or not isinstance(encoded,str)
            or len(encoded)>((CHUNK_BYTES+2)//3)*4+4):
        raise ValueError('Неверные параметры передачи')
    try:chunk=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error) as exc:
        raise ValueError('Некорректное кодирование фрагмента') from exc
    expected=min(CHUNK_BYTES,size-index*CHUNK_BYTES)
    if len(chunk)!=expected:
        raise ValueError('Некорректная длина фрагмента')
    return tid,name,size,index,total,sha,chunk


def validate_control(packet):
    kind=packet.get('kind') if isinstance(packet,dict) else ''
    if kind=='file_chunk':
        # Avoid copying the 2 MiB binary content: this function is used
        # only after authenticated AES-GCM decryption.
        _checked_chunk(packet)
    elif kind=='file_ack':
        _identity(packet.get('transfer_id'))
        i=packet.get('index')
        if not isinstance(i,int) or isinstance(i,bool) or not 0<=i<MAX_CHUNKS:
            raise ValueError('Некорректное подтверждение части файла')
    elif kind=='file_ref':
        _identity(packet.get('transfer_id'))
        if (not isinstance(packet.get('name'),str)
                or not 1<=len(packet['name'])<=250
                or not isinstance(packet.get('size'),int)
                or not 0<=packet['size']<=MAX_FILE_SIZE):
            raise ValueError('Некорректная карточка файла')
    else:
        raise ValueError('Неизвестный тип передачи')


class FileSender:
    """Bounded one-in-flight protocol with ACKs, retries and progress events."""
    def __init__(self,wait=ACK_WAIT,retries=RETRIES):
        self.wait=wait
        self.retries=retries
        self.events=queue.Queue()
        self.active={}
        self.lock=threading.Lock()
        self.stopping=threading.Event()

    def start(self,path,send,context=None):
        path=Path(path)
        stat=path.stat()
        if not path.is_file() or not 1<=stat.st_size<=MAX_FILE_SIZE:
            raise ValueError('Допустимый размер файла — до 40 МБ')
        with self.lock:
            if len(self.active)>=2:
                raise ValueError('Уже выполняются две передачи. Заверши одну из них.')
            tid=secrets.token_hex(16)
            state={'id':tid,'path':path,'size':stat.st_size,
                   'mtime':stat.st_mtime_ns,'index':-1,'signal':threading.Event(),
                   'last_ack':None,'context':context}
            self.active[tid]=state
        thread=threading.Thread(target=self._run,args=(state,send),daemon=True,
                                name='orbit-file-'+tid[:6])
        thread.start()
        return tid

    def acknowledge(self,packet,record):
        validate_control(packet)
        if packet['kind']!='file_ack':return False
        with self.lock:
            state=self.active.get(packet['transfer_id'])
            if state is None or state['index']!=packet['index']:return False
            state['last_ack']=record
            state['signal'].set()
            return True

    def _run(self,state,send):
        path=state['path']
        try:
            size=state['size']
            sha=_digest_file(path)
            total=(size+CHUNK_BYTES-1)//CHUNK_BYTES
            with path.open('rb') as stream:
                for index in range(total):
                    if self.stopping.is_set():raise RuntimeError('Передача отменена')
                    stat=path.stat()
                    if stat.st_size!=size or stat.st_mtime_ns!=state['mtime']:
                        raise RuntimeError('Файл изменился во время передачи')
                    chunk=stream.read(min(CHUNK_BYTES,size-index*CHUNK_BYTES))
                    if len(chunk)!=min(CHUNK_BYTES,size-index*CHUNK_BYTES):
                        raise IOError('Невозможно прочитать фрагмент файла')
                    data={'kind':'file_chunk','transfer_id':state['id'],
                          'name':path.name,'size':size,'total':total,
                          'index':index,'sha256':sha,
                          'bytes':base64.b64encode(chunk).decode('ascii')}
                    state['index']=index
                    state['signal'].clear()
                    confirmed=False
                    for attempt in range(self.retries):
                        if self.stopping.is_set():raise RuntimeError('Передача отменена')
                        send(data)
                        if state['signal'].wait(self.wait):
                            confirmed=True
                            break
                    if not confirmed:
                        raise TimeoutError('Получатель не подтвердил часть файла. '
                                           'Убедись, что оба клиента обновлены и находятся в сети.')
                    self.events.put(('progress',state['id'],path.name,index+1,total))
            self.events.put(('complete',state['id'],path,size,
                             state['last_ack'],state['context']))
        except Exception as exc:
            self.events.put(('error',state['id'],path.name,str(exc)))
        finally:
            with self.lock:self.active.pop(state['id'],None)

    def stop(self):
        self.stopping.set()
        with self.lock:
            for state in self.active.values():state['signal'].set()


class FileReceiver:
    """Reassemble authenticated chunks into an isolated temporary file."""
    def __init__(self,folder,clock=time.monotonic):
        self.folder=Path(folder)
        self.clock=clock
        self.active={}
        self.completed={}

    def _cleanup(self):
        now=self.clock()
        for tid,state in list(self.active.items()):
            if now-state['seen']>TRANSFER_TIMEOUT:
                state['tmp'].unlink(missing_ok=True)
                del self.active[tid]
        for tid,state in list(self.completed.items()):
            if now-state['seen']>TRANSFER_TIMEOUT:
                del self.completed[tid]

    def accept(self,packet):
        tid,name,size,index,total,sha,chunk=_checked_chunk(packet)
        self._cleanup()
        if tid in self.completed:
            return None,False # duplicate last chunk: ack again, no duplicated history
        state=self.active.get(tid)
        if state is None:
            if len(self.active)>=MAX_ACTIVE:
                raise ValueError('Слишком много одновременных файлов')
            self.folder.mkdir(parents=True,exist_ok=True)
            staging=self.folder/'.orbitclip_incomplete'
            if staging.is_symlink():raise ValueError('Недопустимая папка временных файлов')
            staging.mkdir(exist_ok=True)
            try:os.chmod(staging,0o700)
            except OSError:pass
            tmp=staging/(tid+'.part')
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            os.close(fd)
            state={'tmp':tmp,'name':safe_attachment_name(name),'size':size,
                   'total':total,'sha256':sha,'seen':self.clock(),'parts':set()}
            self.active[tid]=state
        if (state['name']!=safe_attachment_name(name) or state['size']!=size
                or state['total']!=total or state['sha256']!=sha):
            raise ValueError('Метаданные передачи изменились')
        state['seen']=self.clock()
        if index in state['parts']:
            return None,False
        with state['tmp'].open('r+b') as file:
            file.seek(index*CHUNK_BYTES)
            file.write(chunk)
        state['parts'].add(index)
        if len(state['parts'])<total:return None,False
        if state['tmp'].stat().st_size!=size or _digest_file(state['tmp'])!=sha:
            state['tmp'].unlink(missing_ok=True)
            del self.active[tid]
            raise ValueError('SHA-256 принятого файла не совпал')
        safe=Path(state['name'])
        for n in range(10000):
            candidate=self.folder/(safe.name if not n else
                                   f'{safe.stem} ({n}){safe.suffix}')
            try:
                # Exclusively create the final file; never overwrite anything.
                with candidate.open('xb') as out:
                    try:os.chmod(candidate,0o600)
                    except OSError:pass
                    with state['tmp'].open('rb') as src:
                        shutil.copyfileobj(src,out,1024*1024)
                break
            except FileExistsError:
                continue
        else:
            raise IOError('Слишком много файлов с одинаковым именем')
        state['tmp'].unlink(missing_ok=True)
        del self.active[tid]
        self.completed[tid]={'seen':self.clock(),'path':candidate}
        return candidate,True
