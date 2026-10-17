"""Experimental offline semantic hints: fast lexical search with curated synonym groups.

This is NOT an embedding model or generative AI; do not claim semantic
understanding. Protected clipboard items are never scanned. Nothing persists.
"""
from __future__ import annotations
import math
import re

TOKENS=re.compile(r'[\wа-яё]+',re.I)
MAX_RESULTS=300
MAX_ITEMS=1500
MAX_TEXT=4000
GROUPS=[
 ('profit','маржа','маржинальность','рентабельность','прибыль','margin','profit'),
 ('price','цена','цены','тариф','тарифы','тарифов','стоимость','прайс','pricing','price'),
 ('change','изменение','изменения','изменением','смена','пересмотр','пересмотра',
  'корректировка','редакция','changed','change'),
 ('sales','продажа','продажи','продаж','реализация','sales','sold'),
 ('revenue','выручка','оборот','revenue','turnover'),
 ('order','заказ','заказы','заказов','orders','order'),
 ('error','ошибка','ошибки','сбой','ошибке','exception','error','failed'),
 ('query','запрос','запросы','sql','select','query'),
 ('customer','клиент','клиенты','клиентов','покупатель','customer','client'),
 ('report','отчет','отчёт','отчеты','отчёты','дашборд','report','dashboard'),
 ('delivery','доставка','перевозка','перевозки','груз','shipping','delivery'),
 ('month','месяц','месяца','месячный','monthly','month'),
 ('year','год','года','годовой','annual','year'),
]
CANON={word:group[0] for group in GROUPS for word in group}
STOP={'как','где','найти','что','у','в','с','на','и','по','для','из','но',
      'после','про','это','тот','то','там','было','был','мне','the','and',
      'with','from','this','find','about','a','an'}


def tokens(value):
    return [x.casefold() for x in TOKENS.findall(str(value)[:MAX_TEXT])
            if len(x)>1 and x.casefold() not in STOP]


def semantic_tokens(value):
    return {CANON.get(t,t) for t in tokens(value)}


def find(query,items,limit=MAX_RESULTS):
    """Rank existing clipboard records using exact and curated semantic overlap.

    Excludes protected entries even when the query would have matched.
    No scoring from clipboard content that hasn't already been stored.
    """
    terms=tokens(query)
    if not terms:return []
    query_raw=set(terms)
    query_sem={CANON.get(x,x) for x in terms}
    found=[]
    for index,item in enumerate(items[:MAX_ITEMS]):
        if item.get('encrypted'):continue
        raw=(str(item.get('title') or '')+' '+str(item.get('text') or '')+' '+
             str(item.get('kind') or '')+' '+str(item.get('source_app') or ''))[:MAX_TEXT]
        exact_raw=raw.casefold()
        raw_terms=set(tokens(raw))
        normalized={CANON.get(t,t) for t in raw_terms}
        exact_count=len(query_raw & raw_terms)
        broad_count=len(query_sem & normalized)
        if exact_count==0 and broad_count==0:continue
        # Favour exact phrase and identifiers; synonyms cannot outrank
        # a complete exact match for technical values.
        phrase_bonus=3 if query.casefold().strip() in exact_raw else 0
        score=(exact_count*3.0 + (broad_count-exact_count)*1.35
               +phrase_bonus + 0.05/(index+1))
        if score>0:found.append((score,index,item))
    found.sort(key=lambda x:(-x[0],x[1]))
    return [item for _,_,item in found[:max(1,min(int(limit),MAX_RESULTS))]]
