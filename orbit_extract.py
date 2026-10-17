"""Offline, deterministic structured extraction. Input is NEVER executed or sent online."""
from __future__ import annotations
import csv
from datetime import datetime
import io
import json
import re

MAX_TEXT=200000
MAX_ROWS=300
MAX_FIELDS=80
MAX_ENTITIES=80
MONTHS={'января':1,'февраля':2,'марта':3,'апреля':4,'мая':5,'июня':6,'июля':7,
        'августа':8,'сентября':9,'октября':10,'ноября':11,'декабря':12}
DATE=re.compile(r'(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)')
MONTH_DATE=re.compile(r'(?<!\d)(\d{1,2})\s+('+'|'.join(MONTHS)+r')\s+(\d{4})(?!\d)',re.I)
AMOUNT=re.compile(r'(?<![\w.,])([-+]?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,4})?|[-+]?\d+(?:[.,]\d{1,4})?)\s*(₽|руб(?:\.|лей|ля)?|USD|EUR|\$|€|%|шт\.?|кг|м³)(?![а-яa-z])',re.I)
EMAIL=re.compile(r'(?<![\w.+-])[\w.+-]+@(?:[\w-]+\.)+[a-z]{2,24}\b',re.I)
URL=re.compile(r'https?://[^\s<>"{}|\\^]+',re.I)
PAIR=re.compile(r'^\s*([^:\n=]{2,65}?)\s*[:=]\s*(\S.*?)\s*$')
IDENT=re.compile(r'(?:\b(?:id|idsending|order\s*id|заказ\s*№|договор\s*№|инн|кпп|артикул|sku|номер\s+(?:заказа|сч[её]та))\b)\s*[:=#№]?\s*([\w./-]{2,70})',re.I)
FIELD_NAMES={'выручка':'revenue','оборот':'revenue','revenue':'revenue','сумма':'amount',
  'итого':'total','маржинальность':'margin_pct','рентабельность':'margin_pct',
  'количество заказов':'orders','заказы':'orders','дата':'date','период':'period',
  'инн':'tax_id','idsending':'shipment_id'}


def _date(day,month,year):
    try:return datetime(int(year),int(month),int(day)).strftime('%Y-%m-%d')
    except (ValueError,OverflowError):return None


def _table_json(obj):
    if isinstance(obj,dict):source=[obj]
    elif isinstance(obj,list) and obj and all(isinstance(x,dict) for x in obj):source=obj
    else:return None
    def flat(d,prefix='',depth=0):
        result={}
        for k,v in d.items():
            key=(prefix+'.' if prefix else '')+str(k)
            if isinstance(v,dict) and depth<3:result.update(flat(v,key,depth+1))
            elif isinstance(v,(list,dict)):result[key]=json.dumps(v,ensure_ascii=False)
            elif v is None:result[key]=''
            else:result[key]=str(v)
        return result
    rows=[flat(v) for v in source[:MAX_ROWS]]
    headers=list(dict.fromkeys(k for row in rows for k in row))
    if len(headers)>MAX_FIELDS:return None
    return [headers]+[[row.get(k,'') for k in headers] for row in rows]


def _table_delimited(text):
    lines=[line for line in text.splitlines() if line.strip()]
    if not 2<=len(lines)<=MAX_ROWS+1:return None
    if lines[0].lstrip().startswith('|') and '|' in lines[0]:
        rows=[[v.strip() for v in line.strip().strip('|').split('|')] for line in lines]
        if len(rows)>1 and all(re.fullmatch(r':?-{3,}:?',x or '') for x in rows[1]):
            rows.pop(1)
    else:
        sep=max(('\t',';',','),key=lines[0].count)
        if lines[0].count(sep)<1 or (sep==',' and re.search(r'\d,\d',lines[0])):
            return None
        try:rows=list(csv.reader(io.StringIO('\n'.join(lines)),delimiter=sep))
        except csv.Error:return None
    if not rows or len(rows)<2 or not 2<=len(rows[0])<=MAX_FIELDS:return None
    if any(len(row)!=len(rows[0]) for row in rows):return None
    return rows


def inspect(text):
    """Returns source-backed tables and extracted entities, no calculated values."""
    if not isinstance(text,str):raise ValueError('Нужен текст')
    if len(text)>MAX_TEXT:raise ValueError('Слишком большой текст (не более 200 000 символов)')
    if not text.strip():raise ValueError('Пустой фрагмент')
    result={'kind':'text','rows':None,'fields':[],'entities':[],
            'warnings':[],'source_size':len(text)}
    trimmed=text.strip()
    parsed=None
    if trimmed.startswith(('{','[')):
        try:
            parsed=json.loads(trimmed)
            result['kind']='json'
            result['rows']=_table_json(parsed)
            if result['rows'] is None:result['warnings'].append('JSON не является таблицей объектов')
        except (ValueError,TypeError):
            result['warnings'].append('Некорректный JSON')
    if result['rows'] is None and parsed is None:
        table=_table_delimited(trimmed)
        if table:
            result['rows']=table
            result['kind']='table'
    if result['rows'] is None and parsed is None:
        fields=[]
        for line in text.splitlines()[:MAX_ROWS]:
            m=PAIR.match(line)
            if m and len(m.group(2))<=5000 and not m.group(1).startswith('http'):
                name,value=m.groups()
                fields.append({'label':name.strip(),'key':FIELD_NAMES.get(name.casefold().strip(),''),
                               'value':value.strip()})
        if len(fields)>=2:
            result['fields']=fields[:MAX_FIELDS]
            result['kind']='fields'
            result['rows']=[['Поле','Значение']]+[[x['label'],x['value']] for x in result['fields']]
    entities=[];seen=set()
    def add(item):
        key=tuple(sorted(item.items()))
        if key not in seen and len(entities)<MAX_ENTITIES:
            seen.add(key);entities.append(item)
    for m in DATE.finditer(text):
        valid=_date(*m.groups())
        if valid:add({'type':'date','source':m.group(0),'value':valid})
    for m in MONTH_DATE.finditer(text):
        day,month,year=m.groups()
        valid=_date(day,MONTHS[month.casefold()],year)
        if valid:add({'type':'date','source':m.group(0),'value':valid})
    for m in AMOUNT.finditer(text):
        number,unit=m.groups()
        add({'type':'quantity','source':m.group(0),'value':number.strip(),'unit':unit})
    for pattern,kind in ((EMAIL,'email'),(URL,'url')):
        for m in pattern.finditer(text):
            add({'type':kind,'source':m.group(0),'value':m.group(0)})
    for m in IDENT.finditer(text):
        add({'type':'identifier','source':m.group(0),'value':m.group(1)})
    result['entities']=entities
    result['preview_rows']=max(0,len(result['rows'])-1) if result['rows'] else 0
    return result


def export_table(rows,format='tsv'):
    if not rows:raise ValueError('Нет таблицы')
    if format=='json':
        return json.dumps([dict(zip(rows[0],r)) for r in rows[1:]],ensure_ascii=False,indent=2)
    if format not in ('tsv','csv'):raise ValueError('Неизвестный формат')
    output=io.StringIO()
    csv.writer(output,delimiter='\t' if format=='tsv' else ',',
               lineterminator='\n').writerows(rows)
    return output.getvalue().rstrip('\n')


def entity_rows(entities):
    return [['Тип','Исходное значение','Распознанное значение']]+[
        [x['type'],x['source'],x['value']+((' '+x['unit']) if x.get('unit') else '')]
        for x in entities]
