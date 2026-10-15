"""Local, review-first transformations for text/SQL/JSON/CSV/URLs/code.

Does not evaluate input, access network or modify original clipboard history.
A transformation that only validates is explicitly marked as a report.
"""
from __future__ import annotations

import ast
import csv
import html
from html.parser import HTMLParser
import io
import json
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING={'fbclid','gclid','yclid','ysclid','mc_cid','mc_eid','igshid','ref_src','spm','msclkid','twclid','ttclid','_hsenc','_hsmi'}
MAX_INPUT=2_000_000


def clean_link(text):
    url=text.strip()
    parts=urlsplit(url)
    if parts.scheme.lower() not in ('http','https') or not parts.netloc:
        raise ValueError('Нужна корректная http(s)-ссылка')
    kept=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True)
          if k.lower() not in TRACKING and not k.lower().startswith(('utm_','pk_','mtm_'))]
    return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(kept),parts.fragment))


def parse_table(text):
    lines=[x for x in text.splitlines() if x.strip()]
    if len(lines)<2:raise ValueError('Для таблицы требуется минимум две строки')
    if lines[0].lstrip().startswith('|') and '|' in lines[0]:
        rows=[[z.strip() for z in line.strip().strip('|').split('|')] for line in lines]
        if len(rows)>1 and all(re.fullmatch(r':?-{3,}:?',x) for x in rows[1]):rows.pop(1)
    else:
        counts={ '\t':lines[0].count('\t'), ';':lines[0].count(';'), ',':lines[0].count(',') }
        delimiter=max(counts,key=counts.get)
        if counts[delimiter]==0:raise ValueError('Не обнаружены столбцы')
        rows=list(csv.reader(io.StringIO('\n'.join(lines)),delimiter=delimiter))
    if not rows or max(map(len,rows))<2:raise ValueError('Не удалось распознать столбцы')
    width=max(map(len,rows))
    return [(row+['']*width)[:width] for row in rows[:5001]]


def make_table(rows,delimiter='\t'):
    out=io.StringIO();csv.writer(out,delimiter=delimiter,lineterminator='\n').writerows(rows)
    return out.getvalue().rstrip('\n')


def table_clean(text):
    rows=parse_table(text)
    return make_table([[c.strip().replace('\r','') for c in row] for row in rows])


def table_transpose(text):
    rows=parse_table(text)
    return make_table(list(map(list,zip(*rows))))


def table_summary(text):
    rows=parse_table(text);head=rows[0];data=rows[1:]
    blanks=sum(not x.strip() for row in data for x in row)
    duplicates=len(data)-len({tuple(row) for row in data})
    bad_names=[str(i+1) for i,name in enumerate(head) if not name.strip()]
    return ('Строк данных: '+str(len(data))+'\nСтолбцов: '+str(len(head))+
            '\nПустых ячеек: '+str(blanks)+'\nПовторяющихся строк: '+str(duplicates)+
            '\nБезымянные столбцы: '+(', '.join(bad_names) if bad_names else 'нет')+
            '\n\nЗаголовки: '+', '.join(head))


def table_remove_duplicates(text):
    rows=parse_table(text)
    if not rows:return ''
    seen=set();out=[rows[0]]
    for row in rows[1:]:
        key=tuple(row)
        if key not in seen:seen.add(key);out.append(row)
    return make_table(out)


def json_flatten(text):
    obj=json.loads(text)
    if isinstance(obj,dict):data=[obj]
    elif isinstance(obj,list) and all(isinstance(x,dict) for x in obj):data=obj
    else:raise ValueError('Для таблицы JSON нужен объект или список объектов')
    if not data:raise ValueError('Пустой список объектов')
    def flatten(row,prefix=''):
        result={}
        for key,value in row.items():
            name=(prefix+'.' if prefix else '')+str(key)
            if isinstance(value,dict):result.update(flatten(value,name))
            elif isinstance(value,list):result[name]=json.dumps(value,ensure_ascii=False)
            elif value is None:result[name]=''
            else:result[name]=str(value)
        return result
    flat=[flatten(x) for x in data[:5000]]
    headers=list(dict.fromkeys(k for item in flat for k in item))
    return make_table([headers]+[[item.get(k,'') for k in headers] for item in flat])


def json_summary(text):
    obj=json.loads(text)
    lines=['JSON корректен.','Тип корня: '+('массив' if isinstance(obj,list) else 'объект' if isinstance(obj,dict) else type(obj).__name__)]
    if isinstance(obj,dict):lines.append('Ключи ('+str(len(obj))+'): '+', '.join(list(map(str,obj))[:30]))
    if isinstance(obj,list):lines.append('Элементов: '+str(len(obj)))
    lines.append('Размер в символах: '+str(len(text)))
    return '\n'.join(lines)


def sql_format(text):
    if not text.strip():return ''
    try:
        import sqlparse
        return sqlparse.format(text,keyword_case='upper',reindent=True,indent_width=2).strip()
    except ImportError:
        return text.strip()


def sql_summary(text):
    # Lexical diagnostics, never execute SQL. sqlparse protects quoted literals.
    try:
        import sqlparse
        statements=[s for s in sqlparse.parse(text) if str(s).strip()]
        kinds=[s.get_type() for s in statements]
    except ImportError:
        statements=[x for x in text.split(';') if x.strip()]
        kinds=[re.match(r'\s*([A-Za-z]+)',s).group(1).upper() if re.match(r'\s*([A-Za-z]+)',s) else '?' for s in statements]
    params=sorted(set(re.findall(r'(?<!:):([A-Za-z_][\w]*)|\{([A-Za-z_][\w]*)\}',text)))
    params=[a or b for a,b in params]
    return ('Запросов: '+str(len(statements))+'\nТипы: '+(', '.join(kinds) or '—')+
            '\nИменованные параметры: '+(', '.join(params) if params else 'не обнаружены')+
            '\n\nЭто статический анализ: SQL не выполняется.')


class Plain(HTMLParser):
    def __init__(self):super().__init__();self.text=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if tag in ('p','br','li','h1','h2','h3','tr'):self.text.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip:self.text.append(data)


def html_text(text):
    parser=Plain();parser.feed(text)
    return '\n'.join(' '.join(line.split()) for line in ''.join(parser.text).splitlines() if line.strip())


def python_summary(text):
    try:
        tree=ast.parse(text)
    except SyntaxError as exc:
        return f'Ошибка синтаксиса: строка {exc.lineno}, позиция {exc.offset}\n{exc.msg}\n{exc.text or ""}'
    functions=[n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
    classes=[n.name for n in ast.walk(tree) if isinstance(n,ast.ClassDef)]
    imports=[n.names[0].name for n in ast.walk(tree) if isinstance(n,ast.Import) and n.names]
    imports += [n.module or '?' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    return ('Синтаксис Python корректный.\nФункции: '+(', '.join(functions) if functions else 'нет')+
            '\nКлассы: '+(', '.join(classes) if classes else 'нет')+
            '\nИмпорты: '+(', '.join(imports) if imports else 'нет')+
            '\nСтрок: '+str(len(text.splitlines())))


def normalize_text(text):
    return '\n'.join(' '.join(line.split()) for line in text.replace('\r\n','\n').splitlines()).strip()


def action_catalog(text,kind):
    """Return structured action descriptors with descriptions and safe, deterministic previews.

    Each result contains id, title, description, extension, result, report.
    """
    text=str(text)
    if len(text)>MAX_INPUT:raise ValueError('Слишком длинный фрагмент (предел 2 млн символов)')
    kind=str(kind or 'text').lower()
    trimmed=text.lstrip()
    if kind=='text':
        if trimmed.startswith(('{','[')):kind='json'
        elif trimmed.lower().startswith(('http://','https://')) and '\n' not in trimmed:kind='link'
        elif re.search(r'<[a-z][\w-]*(?:\s|>)',trimmed,re.I):kind='html'
    actions=[]
    def add(ident,title,description,extension,result,report=False):
        actions.append({'id':ident,'title':title,'description':description,
            'extension':extension,'result':str(result),'report':report})
    if kind=='json':
        try:
            obj=json.loads(text)
        except (ValueError,TypeError) as ex:
            add('json.invalid','Проверить JSON','Сообщение парсера с позицией ошибки.','.txt','Ошибка JSON: '+str(ex),True)
        else:
            add('json.report','Структура JSON','Тип корня, размер и обзор ключей.','.txt',json_summary(text),True)
            add('json.pretty','Форматировать','Отступы, Unicode без экранирования.','.json',json.dumps(obj,ensure_ascii=False,indent=2))
            add('json.minify','Минимизировать','Без пробелов и переносов.','.json',json.dumps(obj,ensure_ascii=False,separators=(',',':')))
            if isinstance(obj,dict) or (isinstance(obj,list) and obj and all(isinstance(x,dict) for x in obj)):
                add('json.table','JSON → таблица','Вложенные поля превращаются в столбцы; массивы — в JSON.','.tsv',json_flatten(text))
    elif kind=='sql':
        add('sql.report','Проанализировать SQL','Количество запросов, типы и параметры; без исполнения.','.txt',sql_summary(text),True)
        add('sql.format','Форматировать SQL','Сохраняются строки и условия; используется sqlparse.','.sql',sql_format(text))
    elif kind=='table':
        try:
            add('table.report','Профиль таблицы','Размеры, пустоты и повторы строк.','.txt',table_summary(text),True)
            add('table.clean','Очистить пробелы','TSV с обрезанными пробелами по краям ячеек.','.tsv',table_clean(text))
            add('table.unique','Убрать дубли строк','Первая строка — заголовки; сохраняет первое вхождение.','.tsv',table_remove_duplicates(text))
            add('table.transpose','Транспонировать','Строки становятся столбцами.','.tsv',table_transpose(text))
            add('table.csv','Экспортировать CSV','Правильное экранирование кавычек и разделителей.','.csv',make_table(parse_table(text),','))
        except ValueError as ex:
            add('table.invalid','Диагностика таблицы','Почему таблица не распознана.','.txt',str(ex),True)
    elif kind=='link':
        try:
            parts=urlsplit(text.strip())
            add('link.report','Разобрать ссылку','Домен, путь, параметры и якорь.','.txt',
                'Домен: '+(parts.hostname or '—')+'\nПуть: '+(parts.path or '/')+
                '\nПараметров: '+str(len(parse_qsl(parts.query,keep_blank_values=True)))+
                '\nФрагмент: '+(parts.fragment or '—'),True)
            add('link.clean','Убрать трекеры','Удаляет utm_*, fbclid, gclid и другие маркеры.','.txt',clean_link(text))
        except ValueError as ex:add('link.invalid','Проверить ссылку','Ошибка формата URL.','.txt',str(ex),True)
    elif kind=='python':
        add('python.report','Анализ Python','Ошибки синтаксиса, функции, классы и импорты.','.txt',python_summary(text),True)
    elif kind=='html':
        add('html.text','HTML → текст','Удаляет теги, script и style.','.txt',html_text(text))
        add('html.escape','Экранировать HTML','Преобразовать в текст для безопасного отображения.','.txt',html.escape(text))
    else:
        add('text.normalize','Нормализовать текст','Убирает лишние пробелы и пустые переносы.','.txt',normalize_text(text))
    return actions


def smart_actions(text,kind):
    """Legacy interface retained for existing integrations and tests."""
    actions={a['title']:(a['extension'],a['result']) for a in action_catalog(text,kind)}
    # Older UI extensions and existing user tests expect these public action names.
    for entry in action_catalog(text,kind):
        legacy={
            'json.pretty':'Форматировать JSON',
            'json.minify':'Минимизировать JSON',
            'json.invalid':'Проверка JSON',
            'sql.format':'Форматировать SQL',
            'table.csv':'Экспорт CSV',
            'link.clean':'Удалить трекеры из ссылки',
            'python.report':'Проверить синтаксис',
        }.get(entry['id'])
        if legacy:actions[legacy]=(entry['extension'],entry['result'])
    return actions
