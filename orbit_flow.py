"""Clipboard Flow helpers: ephemeral sequential paste, source exclusions, and suggestions.

No SQL templates, background network requests, or persistent copied content.
"""
from collections import deque
from datetime import datetime
import re


class PasteQueue:
    """Bounded, in-memory editing queue. Clipboard content is never autosaved.

    Backward compatible: push(text), pop() and preview() continue returning the
    same text semantics as 7.7; the UI uses richer named entry snapshots.
    """
    MAX_ITEMS = 40
    MAX_CHARS = 200_000
    MAX_MERGED_CHARS = 200_000

    def __init__(self):
        self._items = deque()
        self.completed = 0

    def __len__(self):
        return len(self._items)

    @property
    def total(self):
        return self.completed + len(self._items)

    def items(self):
        return [dict(entry) for entry in self._items]

    def push(self, text, title='', source_id=None):
        from uuid import uuid4
        value = str(text or '')
        if not value or len(value) > self.MAX_CHARS or len(self._items) >= self.MAX_ITEMS:
            return False
        self._items.append({'uid': uuid4().hex, 'text': value,
                            'title': str(title or '')[:160],
                            'source_id': str(source_id) if source_id is not None else ''})
        return True

    def pop(self):
        if not self._items:
            return None
        self.completed += 1
        return self._items.popleft()['text']

    def take(self, uid):
        """Consume a specific drum selection; all other positions retain order."""
        for index, item in enumerate(self._items):
            if item['uid'] == uid:
                del self._items[index]
                self.completed += 1
                return item['text']
        return None

    def move(self, uid, destination):
        entries = list(self._items)
        index = next((i for i,x in enumerate(entries) if x['uid']==uid),-1)
        if index < 0 or not isinstance(destination,int):
            return False
        element=entries.pop(index)
        destination=max(0,min(destination,len(entries)))
        entries.insert(destination,element)
        self._items=deque(entries)
        return True

    def remove(self, uid):
        for index,entry in enumerate(self._items):
            if entry['uid']==uid:
                del self._items[index]
                return True
        return False

    def merge(self, uids, delimiter='\n'):
        """Merge selected fragments in QUEUE order; no auto clipboard mutation."""
        selected = set(uids)
        if len(selected) < 2:
            return False
        entries=list(self._items)
        positions=[i for i,x in enumerate(entries) if x['uid'] in selected]
        if len(positions)<2:
            return False
        combined=str(delimiter).join(entries[i]['text'] for i in positions)
        if not combined or len(combined)>self.MAX_MERGED_CHARS:
            return False
        from uuid import uuid4
        merged={'uid':uuid4().hex,'text':combined,
                'title':f'Объединено: {len(positions)} записей','source_id':''}
        entries=[x for x in entries if x['uid'] not in selected]
        entries.insert(positions[0],merged)
        self._items=deque(entries)
        return True

    def replace(self, entries):
        """Replace pending fragments only. Returns False on invalid preset."""
        if not isinstance(entries,list) or len(entries)>self.MAX_ITEMS:
            return False
        fresh=PasteQueue()
        for item in entries:
            if not isinstance(item,dict) or not fresh.push(item.get('text',''),
                     item.get('title',''),item.get('source_id','')):
                return False
        self._items=fresh._items
        self.completed=0
        return True

    def clear(self):
        self._items.clear()
        self.completed=0

    def preview(self):
        return [x['text'].replace('\n', ' ↵ ')[:95] for x in self._items]


class QueuePresets:
    """Opt-in named queues in a local owner-only JSON file.

    NEVER autosave the active queue; persistence is only triggered by the
    explicit Save command. Do not accept protected clipboard items upstream.
    """
    MAX_PRESETS = 20
    MAX_TOTAL_CHARS = 400_000

    def __init__(self,path=None):
        from pathlib import Path
        self.path=Path(path) if path is not None else Path.home()/'.orbitclip_paste_presets.json'

    def all(self):
        import json
        try:
            data=json.loads(self.path.read_text('utf-8'))
        except (OSError,ValueError):
            return {}
        if not isinstance(data,dict) or data.get('version')!=1:
            return {}
        presets=data.get('presets')
        if not isinstance(presets,dict):
            return {}
        result={}
        for name,entries in list(presets.items())[:self.MAX_PRESETS]:
            if (not isinstance(name,str) or not (1<=len(name)<=60) or
                    not isinstance(entries,list) or len(entries)>PasteQueue.MAX_ITEMS):
                continue
            valid=[{'text':x['text'],'title':x.get('title','')}
                   for x in entries if isinstance(x,dict) and
                   isinstance(x.get('text'),str) and 0<len(x['text'])<=PasteQueue.MAX_CHARS]
            if len(valid)==len(entries) and sum(len(x['text']) for x in valid)<=self.MAX_TOTAL_CHARS:
                result[name]=valid
        return result

    def save(self,name,queue):
        from kinetic_clipboard import private_write
        name=str(name).strip()
        if not (1<=len(name)<=60):
            raise ValueError('Название должно содержать от 1 до 60 символов')
        entries=[{'text':x['text'],'title':x['title']} for x in queue.items()]
        if not entries or sum(len(x['text']) for x in entries)>self.MAX_TOTAL_CHARS:
            raise ValueError('Очередь пуста или превышает лимит сохранения')
        data=self.all()
        if name not in data and len(data)>=self.MAX_PRESETS:
            raise ValueError('Достигнут лимит: 20 наборов')
        data[name]=entries
        private_write(self.path,{'version':1,'presets':data})

    def delete(self,name):
        from kinetic_clipboard import private_write
        data=self.all()
        if name not in data:
            return False
        del data[name]
        private_write(self.path,{'version':1,'presets':data})
        return True

    def load(self,name,queue):
        entries=self.all().get(name)
        return queue.replace(entries) if entries is not None else False


def normalize_exclusions(value):
    """Match actual foreground process name, never a window title or wildcard."""
    entries = value if isinstance(value, list) else []
    return sorted({str(v).strip().casefold()[:60] for v in entries
                   if str(v).strip() and len(str(v)) <= 60})


def is_excluded(app_name, exclusions):
    name = str(app_name or '').strip().casefold()
    return bool(name and name != 'неизвестно' and name in normalize_exclusions(exclusions))


def quick_actions(text, kind):
    """Small list of context-sensitive actions; never execute input."""
    from orbit_smart import action_catalog
    if not isinstance(text, str) or not text.strip() or len(text) > 200_000:
        return []
    suggestions = action_catalog(text, kind)
    return [entry for entry in suggestions if not entry.get('report')][:5]
