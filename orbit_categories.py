"""Persistent user-managed categories and a deterministic manual Ctrl+Wheel queue.
Pure Python: supports test runs without Qt.
"""
import uuid

DEFAULT_CATEGORIES = [
    {'id':'all','name':'Все','icon':'clipboard','wheel':True,'system':True},
    {'id':'favorites','name':'Избранное','icon':'favorite','wheel':True,'system':True},
    {'id':'text','name':'Текст','icon':'text','wheel':True,'system':True},
    {'id':'link','name':'Ссылки','icon':'link','wheel':True,'system':True},
    {'id':'code','name':'Код','icon':'code','wheel':True,'system':True},
    {'id':'sql','name':'SQL','icon':'sql','wheel':True,'system':True},
    {'id':'table','name':'Таблицы','icon':'table','wheel':True,'system':True},
    {'id':'json','name':'JSON','icon':'json','wheel':True,'system':True},
    {'id':'python','name':'Python','icon':'python','wheel':True,'system':True},
    {'id':'html','name':'HTML','icon':'html','wheel':True,'system':True},
]
ICONS=['clipboard','favorite','text','link','code','sql','table','json','python','html','document','history','priority','remote','search']
SYSTEM_FIXED = {'all','favorites'}


def category_click_handler(category_id, activate):
    """Bind Qt's clicked(bool) without letting checked overwrite a category ID.

    QPushButton.clicked passes a bool argument even for non-checkable buttons.
    A closure written as ``lambda x=category_id: ...`` inadvertently receives
    False instead of the original category, breaking filtering and history.
    """
    if not isinstance(category_id, str):
        raise TypeError('category_id must be a string')

    def on_clicked(_checked=False):
        return activate(category_id)

    return on_clicked
CODE_KINDS={'sql','python','json','html'}

class CategoryModel:
    def __init__(self, raw=None):
        self.categories=[]
        saved={}
        if isinstance(raw,list):
            for c in raw:
                if isinstance(c,dict) and isinstance(c.get('id'),str):saved[c['id']]=c
        for default in DEFAULT_CATEGORIES:
            d=default.copy();d['visible']=True; prior=saved.get(d['id'])
            if prior:
                d['name']=str(prior.get('name') or d['name'])[:32]
                d['icon']=prior.get('icon') if prior.get('icon') in ICONS else d['icon']
                d['wheel']=bool(prior.get('wheel',True))
                d['visible']=bool(prior.get('visible',True))
            self.categories.append(d)
        for c in (raw if isinstance(raw,list) else []):
            if not isinstance(c,dict):continue
            cid=c.get('id')
            if not isinstance(cid,str) or not cid.startswith('user:') or cid in saved and saved[cid] is not c:continue
            if cid not in {x['id'] for x in self.categories}:
                self.categories.append({'id':cid,'name':str(c.get('name') or 'Без названия')[:32],
                  'icon':c.get('icon') if c.get('icon') in ICONS else 'document',
                  'wheel':bool(c.get('wheel',True)),'system':False,'visible':bool(c.get('visible',True))})

    def get(self,cid):return next((x for x in self.categories if x['id']==cid),None)
    def add(self,name,icon='document',wheel=True):
        name=str(name).strip()[:32]
        if not name:raise ValueError('Введите название категории')
        c={'id':'user:'+uuid.uuid4().hex[:14],'name':name,
           'icon':icon if icon in ICONS else 'document','wheel':bool(wheel),'system':False,'visible':True}
        self.categories.append(c);return c
    def edit(self,cid,name,icon,wheel):
        c=self.get(cid)
        if c is None:raise ValueError('Категория не найдена')
        name=str(name).strip()[:32]
        if not name:raise ValueError('Введите название')
        c.update(name=name,icon=icon if icon in ICONS else c['icon'],wheel=bool(wheel))
    def delete(self,cid):
        c=self.get(cid)
        if c is None:raise ValueError('Категория не найдена')
        if c['id']=='all':raise ValueError('Категорию «Все» нельзя удалить')
        if c['system']:
            c['visible']=False  # hide builtin without losing the meaning of existing content
        else:self.categories.remove(c)
    def wheel_categories(self):return [c for c in self.categories if c['wheel'] and c.get('visible',True)]
    def visible_categories(self):return [c for c in self.categories if c.get('visible',True)]
    def restore_builtin(self):
        for c in self.categories:
            if c['system']:c['visible']=True
    def matches(self,item,cid):
        # Defensive validation: malformed state must never crash the UI.
        if not isinstance(cid,str):return False
        if cid=='all':return True
        if cid=='favorites':return bool(item.get('pinned'))
        if cid=='code':return item.get('kind') in CODE_KINDS
        if cid.startswith('user:'):return item.get('category')==cid
        return item.get('kind')==cid
    def normalize_item_categories(self,vault):
        """Migrate old free-form category names to stable custom IDs."""
        changed=False
        for item in vault.items:
            cat=item.get('category','')
            if not cat or self.get(cat):continue
            existing=next((c for c in self.categories if not c['system'] and c['name'].casefold()==cat.casefold()),None)
            if not existing:existing=self.add(cat,'document',True)
            item['category']=existing['id'];changed=True
        if changed:vault.save()

class WheelQueue:
    """Stable hand-curated ordering, independently for each ring category."""
    def __init__(self,manual=None,limit=20):
        if isinstance(manual,dict):
            self.manual_map={str(k):list(dict.fromkeys(x for x in v if isinstance(x,str)))
                for k,v in manual.items() if isinstance(v,list)}
        else:self.manual_map={'all':list(dict.fromkeys(x for x in (manual if isinstance(manual,list) else []) if isinstance(x,str)))}
        self.limit=max(1,min(100,int(limit)))
    @property
    def manual(self):return self.manual_map.get('all',[])
    def eligible(self,items,category_model,category='all'):
        return [x for x in items if x.get('scroll_enabled',True) and not x.get('encrypted') and category_model.matches(x,category)]
    def candidates(self,items,category_model,category='all'):
        valid=self.eligible(items,category_model,category)
        mapping={x['id']:x for x in valid}
        manual=self.manual_map.get(category,self.manual_map.get('all',[]))
        first=[mapping[i] for i in manual if i in mapping]
        ordered_ids={x['id'] for x in first}
        remaining=sorted((x for x in valid if x['id'] not in ordered_ids),key=lambda x:x.get('ts',0),reverse=True)
        return (first+remaining)[:self.limit]
    def move_front(self,ordered_ids,items,category_model,category='all'):
        valid={x['id'] for x in self.eligible(items,category_model,category)}
        self.manual_map[category]=list(dict.fromkeys(x for x in ordered_ids if x in valid))[:self.limit]
    def promote(self,item_id):
        arr=[x for x in self.manual if x!=item_id]
        arr.insert(0,item_id)
        self.manual_map['all']=arr[:self.limit]
    def demote(self,item_id):
        self.manual_map['all']=[x for x in self.manual if x!=item_id]
    def reset(self,category='all'):self.manual_map.pop(category,None)
