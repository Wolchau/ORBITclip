"""KINETIC clipboard vault: private local JSON, smart types, permanent pins.
No content ever leaves this module except via explicit user actions.
"""
import csv
import io
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from orbit_secret import seal_text, open_text

MAX_TEXT_LENGTH = 200_000
MAX_RECENT = 200  # Favorites are never automatically deleted
STATE_FILE = Path.home() / '.chronochip_clipboard.json'
SQL = re.compile(r'^\s*(?:--[^\n]*\n\s*)*(?:WITH|SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|EXPLAIN|MERGE|TRUNCATE|GRANT|REVOKE)\b', re.I)
PYTHON = re.compile(r'^\s*(?:def |class |import |from \w+ import |async def |if __name__ ==)', re.I)
MARKDOWN_TABLE = re.compile(r'^\s*\|[^\n]+\|\s*$', re.M)
SHORTCUT = re.compile(r'^(ctrl|cmd)\+alt\+([a-z0-9])$', re.I)


def kind_of(text):
    s=text.strip()
    if not s:
        return 'text'
    if SQL.match(s):
        return 'sql'
    if s[:1] in ('{','['):
        try:
            obj=json.loads(s)
            if isinstance(obj, (dict,list)):
                return 'json'
        except (ValueError,TypeError):pass
    if s.startswith(('http://','https://')) and '\n' not in s:
        p=urlparse(s)
        if p.hostname:return 'link'
    if re.match(r'^\s*<(?:html|div|table|p|span|script|svg|section|!DOCTYPE)\b',s,re.I):
        return 'html'
    if PYTHON.match(s):
        return 'python'
    lines=[line.strip() for line in s.splitlines() if line.strip()]
    if len(lines)>=2 and MARKDOWN_TABLE.search(s) and '|' in lines[0]:
        return 'table'
    if len(lines)>=2:
        if all('\t' in x for x in lines[:min(len(lines),6)]):
            sizes=[len(x.split('\t')) for x in lines[:min(len(lines),6)]]
            if min(sizes)>=2 and max(sizes)==min(sizes):return 'table'
        for delim in (',',';'):
            try:
                sampled=list(csv.reader(io.StringIO('\n'.join(lines[:min(len(lines),6)])),delimiter=delim))
                if len(sampled)>=2 and min(map(len,sampled))>=2 and len({len(x) for x in sampled})==1:
                    return 'table'
            except csv.Error:pass
    return 'text'


LABELS = {
    'sql': ('⌘', 'SQL-запрос'), 'table': ('▦','Таблица'),
    'json': ('{}','JSON'), 'python': ('λ','Python'),
    'html': ('</>','HTML'), 'link': ('↗','Ссылка'), 'text': ('≡','Текст')
}
ACCENTS = {
    'sql':'#F2BD7B','table':'#9FC4FF','json':'#BFADF6',
    'python':'#ABD68A','html':'#EBA9BB','link':'#7CD8BF','text':'#BCC1CD'
}


def private_write(path,obj):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    fd=os.open(str(tmp), os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(obj,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        os.replace(str(tmp),str(path))
        if os.name!='nt':os.chmod(path,0o600)
    finally:
        try:tmp.unlink(missing_ok=True)
        except OSError:pass


def normalize_hotkey(shortcut):
    """Restrict to Ctrl/Command + Alt + one printable ASCII key."""
    text=str(shortcut).strip().lower().replace('control','ctrl').replace('option','alt')
    text=re.sub(r'\s+','',text)
    if not text:return ''
    if not SHORTCUT.fullmatch(text):
        raise ValueError('Формат: ctrl+alt+1 или cmd+alt+k')
    return text


class ClipboardVault:
    def __init__(self,path=STATE_FILE):
        self.path=Path(path)
        self.items=[]
        self.load()

    def load(self):
        try:raw=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,UnicodeError,ValueError):raw=[]
        if isinstance(raw,dict):raw=raw.get('items',[])
        if not isinstance(raw,list):raw=[]
        known=set();shortcuts=set();result=[]
        for entry in raw:
            if not isinstance(entry,dict) or not isinstance(entry.get('text'),str):continue
            s=entry['text']
            encrypted=entry.get('encrypted') if isinstance(entry.get('encrypted'),dict) else None
            if (not s and not encrypted) or len(s)>MAX_TEXT_LENGTH or (s and s in known):continue
            if s:known.add(s)
            try:ts=float(entry.get('ts',time.time()))
            except (ValueError,TypeError):ts=time.time()
            pinned=bool(entry.get('pinned',False))
            try:key=normalize_hotkey(entry.get('hotkey','')) if pinned else ''
            except ValueError:key=''
            if key in shortcuts:key=''
            if key:shortcuts.add(key)
            result.append({'id':str(entry.get('id') or uuid.uuid4().hex)[:40],
                           'text':s if not encrypted else '', 'ts':ts,'kind':str(entry.get('kind') or kind_of(s)) if encrypted else kind_of(s),'pinned':pinned,'hotkey':key,
                           'title':str(entry.get('title',''))[:90], 'category':str(entry.get('category',''))[:36], 'encrypted':encrypted,
                           'scroll_enabled':bool(entry.get('scroll_enabled',True)),
                           'scroll_priority':bool(entry.get('scroll_priority',False)),
                           'priority_ts':float(entry.get('priority_ts',0.0) or 0.0),
                           'source_app':str(entry.get('source_app') or 'Неизвестно')[:60]})
        self.items=result
        self.prune(save=False)

    def save(self):
        private_write(self.path,{'version':7,'items':self.items})

    def prune(self,save=True):
        nonfavorites=0;remaining=[]
        for item in self.items:
            if item['pinned']:
                remaining.append(item)
            elif nonfavorites<MAX_RECENT:
                remaining.append(item);nonfavorites+=1
        self.items=remaining
        if save:self.save()

    def add(self,text,source_app=None):
        if not isinstance(text,str) or not text or len(text)>MAX_TEXT_LENGTH:return None
        prior=next((x for x in self.items if x['text']==text),None)
        if prior:self.items.remove(prior)
        item=prior or {'id':uuid.uuid4().hex,'text':text,'pinned':False,'hotkey':'',
                       'scroll_enabled':True,'scroll_priority':False,'priority_ts':0.0,
                       'title':'','category':'','encrypted':None}
        item.update(ts=time.time(),kind=kind_of(text))
        if source_app:item['source_app']=str(source_app)[:60]
        self.items.insert(0,item)
        self.prune()
        return item

    def find(self,item_id):
        return next((x for x in self.items if x['id']==item_id),None)

    def favorite(self,item_id):
        item=self.find(item_id)
        if not item:return False
        item['pinned']=not item['pinned']
        if not item['pinned']:
            item['hotkey']=''
            self.prune()
        self.save()
        return item['pinned']

    def bind(self,item_id,shortcut):
        item=self.find(item_id)
        if not item:raise ValueError('Запись не найдена')
        if not item['pinned']:raise ValueError('Сначала добавь запись в избранное')
        key=normalize_hotkey(shortcut)
        for other in self.items:
            if other is not item and key and other['hotkey']==key:
                other['hotkey']=''  # explicit rebind moves the assignment
        item['hotkey']=key
        self.save()

    def toggle_scroll(self,item_id):
        """Hide from Ctrl+Wheel without deleting or un-favoriting the entry."""
        item=self.find(item_id)
        if not item:return None
        item['scroll_enabled']=not item.get('scroll_enabled',True)
        self.save()
        return item['scroll_enabled']

    def toggle_priority(self,item_id):
        """Independent of favorite; pinned scroll entries have priority in the bubble."""
        item=self.find(item_id)
        if not item:return None
        item['scroll_priority']=not item.get('scroll_priority',False)
        if item['scroll_priority']:
            item['priority_ts']=time.time()
            item['scroll_enabled']=True
        self.save()
        return item['scroll_priority']

    def scroll_candidates(self, category='all', limit=20, priority_limit=5):
        """Priority-first slots, followed by most recently copied entries, with no duplicates.

        Filtering is applied before quotas. Excluded entries remain stored and searchable.
        """
        limit=max(1,min(100,int(limit)))
        priority_limit=max(0,min(limit,int(priority_limit)))
        code_types={'sql','python','json','html'}
        def eligible(it):
            if not it.get('scroll_enabled',True):return False
            if category.startswith('custom:'):return it.get('category')==category[7:]
            if category=='all':return True
            if category=='favorites':return it.get('pinned',False)
            if category=='code':return it.get('kind') in code_types
            return it.get('kind')==category
        filtered=[item for item in self.items if eligible(item)]
        priority=sorted((i for i in filtered if i.get('scroll_priority',False)),
                        key=lambda i:(i.get('priority_ts',0),i.get('ts',0)), reverse=True)
        result=priority[:priority_limit]
        ids={i['id'] for i in result}
        for item in filtered:
            if len(result)>=limit:break
            if item['id'] not in ids:
                result.append(item)
                ids.add(item['id'])
        return result

    def delete(self,item_id):
        self.items=[i for i in self.items if i['id']!=item_id]
        self.save()

    def clear_recent(self):
        self.items=[i for i in self.items if i['pinned']]
        self.save()

    def by_hotkey(self,shortcut):
        key=normalize_hotkey(shortcut)
        return next((x for x in self.items if x['pinned'] and x['hotkey']==key),None)

    @property
    def favorite_count(self):
        return sum(1 for i in self.items if i['pinned'])

    def describe(self,item_id,title=None,category=None):
        item=self.find(item_id)
        if not item:raise ValueError('Запись не найдена')
        if title is not None:item['title']=str(title).strip()[:90]
        if category is not None:item['category']=str(category).strip()[:36]
        self.save()

    def encrypt_item(self,item_id,password):
        item=self.find(item_id)
        if not item or item.get('encrypted') or not item.get('text'):
            raise ValueError('Нечего шифровать')
        encrypted=seal_text(item['text'],password)
        # Replace sensitive plaintext with authenticated ciphertext on disk.
        item['text']=''
        item['encrypted']=encrypted
        item['scroll_enabled']=False
        item['scroll_priority']=False
        item['hotkey']=''
        self.save()

    def decrypt_item(self,item_id,password):
        item=self.find(item_id)
        if not item or not item.get('encrypted'):
            raise ValueError('Запись не зашифрована')
        return open_text(item['encrypted'],password)
