"""PostgreSQL metadata discovery and private, annotated SQL workspaces.

Never saves credentials. PostgreSQL metadata is accessed read-only, with user
supplied identifiers always treated as query parameters rather than SQL.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile

PROJECT_DIR=Path.home()/'.orbitclip_sql_projects'


def profile_key(host,port,database,user):
    raw='|'.join(map(str,[host.strip().lower(),int(port),database.strip(),user.strip()]))
    if not host.strip() or not database.strip() or not user.strip():
        raise ValueError('Укажи сервер, базу данных и пользователя')
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


class SQLProject:
    def __init__(self, key, directory=None):
        if not key.isalnum():raise ValueError('Invalid project ID')
        self.path=Path(directory or PROJECT_DIR)/(key+'.json')
        self.data={'selected':[],'comments':{},'joins':[],'positions':{}}
        if self.path.exists():
            found=json.loads(self.path.read_text('utf-8'))
            if isinstance(found,dict):
                for name in self.data:
                    if name in found and isinstance(found[name],type(self.data[name])):
                        self.data[name]=found[name]

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix='.sql-',suffix='.tmp',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as file:
                json.dump(self.data,file,ensure_ascii=False,indent=2)
            os.chmod(temp,0o600)
            os.replace(temp,self.path)
        finally:
            if os.path.exists(temp):os.remove(temp)

    def select(self,tables):
        self.data['selected']=list(dict.fromkeys(tables));self.save()

    def annotate(self,table,column,comment):
        self.data['comments'][table+'.'+column]=str(comment)[:3000];self.save()

    def relation(self,left,left_column,right,right_column):
        if not all([left,left_column,right,right_column]):raise ValueError('Заполни обе таблицы и поля')
        relation={'left':left,'left_column':left_column,'right':right,'right_column':right_column}
        if relation not in self.data['joins']:
            self.data['joins'].append(relation);self.save()
        return relation

    def position(self,table,x,y):
        self.data['positions'][table]=[float(x),float(y)];self.save()


class PostgreSQLCatalog:
    """Introspection only. The DB role should additionally be restricted to read-only."""
    def __init__(self,host,port,database,user,password,sslmode='prefer'):
        self.config=dict(host=host.strip(),port=int(port),dbname=database.strip(),user=user.strip(),
                         password=password,sslmode=sslmode,connect_timeout=7)
        if sslmode not in ('verify-full','verify-ca','require','prefer','disable'):
            raise ValueError('Invalid TLS mode')
        self.conn=None

    def connect(self):
        import psycopg
        self.conn=psycopg.connect(**self.config,autocommit=True)
        # Cannot enable write operations via the Explorer session.
        with self.conn.cursor() as cursor:
            cursor.execute("SET default_transaction_read_only = on")
            cursor.execute("SET statement_timeout = '12000ms'")
        return self

    def close(self):
        if self.conn is not None:self.conn.close()
        self.conn=None

    def _query(self,query,args=()):
        if self.conn is None:raise RuntimeError('Нет подключения к базе')
        with self.conn.cursor() as cursor:
            cursor.execute(query,args)
            names=[getattr(c,'name',c[0]) for c in cursor.description]
            return [dict(zip(names,record)) for record in cursor.fetchall()]

    def tables(self):
        return self._query("""
            SELECT n.nspname AS schema, c.relname AS name,
                   CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view'
                     ELSE 'table' END AS kind,
                   COALESCE(obj_description(c.oid, 'pg_class'),'') AS comment
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p','v','m')
              AND n.nspname NOT IN ('pg_catalog','information_schema')
              AND n.nspname NOT LIKE 'pg_toast%'
            ORDER BY n.nspname,c.relname
        """)

    def columns(self,schema,table):
        return self._query("""
            SELECT a.attname AS name, format_type(a.atttypid,a.atttypmod) AS type,
                   NOT a.attnotnull AS nullable,
                   COALESCE(col_description(c.oid,a.attnum),'') AS comment,
                   EXISTS (
                      SELECT 1 FROM pg_constraint p
                      WHERE p.conrelid=c.oid AND p.contype='p'
                        AND a.attnum=ANY(p.conkey)
                   ) AS primary_key
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid
            WHERE n.nspname=%s AND c.relname=%s
              AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY a.attnum
        """,(schema,table))

    def foreign_keys(self,selected=None):
        rows=self._query("""
            SELECT ns.nspname AS source_schema, src.relname AS source_table,
                   nt.nspname AS target_schema, dst.relname AS target_table,
                   c.conname AS constraint_name,
                   a.attname AS source_column, b.attname AS target_column,
                   keys.pos AS position
            FROM pg_constraint c
            JOIN pg_class src ON src.oid=c.conrelid
            JOIN pg_namespace ns ON ns.oid=src.relnamespace
            JOIN pg_class dst ON dst.oid=c.confrelid
            JOIN pg_namespace nt ON nt.oid=dst.relnamespace
            JOIN LATERAL unnest(c.conkey,c.confkey) WITH ORDINALITY
                 AS keys(source_attnum,target_attnum,pos) ON TRUE
            JOIN pg_attribute a ON a.attrelid=src.oid AND a.attnum=keys.source_attnum
            JOIN pg_attribute b ON b.attrelid=dst.oid AND b.attnum=keys.target_attnum
            WHERE c.contype='f'
            ORDER BY ns.nspname,src.relname,c.conname,keys.pos
        """)
        if selected is not None:
            allowed=set(selected)
            rows=[r for r in rows if
                f"{r['source_schema']}.{r['source_table']}" in allowed and
                f"{r['target_schema']}.{r['target_table']}" in allowed]
        return rows

# Compatibility with the 7.3 SQL-project API. New 7.4 UI uses SQLProject,
# while existing saved 7.3 metadata and tests use these pure helper functions.
import math

def table_id(schema,table):
    return json.dumps([str(schema),str(table)],ensure_ascii=False,separators=(',',':'))


def split_table_id(value):
    parts=json.loads(value)
    if not isinstance(parts,list) or len(parts)!=2 or any(not isinstance(p,str) for p in parts):
        raise ValueError('Invalid table id')
    return tuple(parts)


def field_note_key(table,column):
    return table_id(table,column)


def new_project():
    return {'selected':[],'notes':{},'joins':[],'positions':{}}


def validate_project(raw):
    result=new_project()
    if not isinstance(raw,dict):return result
    if isinstance(raw.get('selected'),list):
        result['selected']=[str(t) for t in raw['selected'] if isinstance(t,str)][:150]
    if isinstance(raw.get('notes'),dict):
        result['notes']={str(k):str(v)[:3000] for k,v in raw['notes'].items() if isinstance(v,str)}
    if isinstance(raw.get('joins'),list):
        result['joins']=[j for j in raw['joins'] if isinstance(j,dict) and
                         all(j.get(k) for k in ('left','right','left_columns','right_columns'))]
    if isinstance(raw.get('positions'),dict):
        for key,value in raw['positions'].items():
            try:
                if len(value)!=2:continue
                x,y=map(float,value)
                if math.isfinite(x) and math.isfinite(y):result['positions'][str(key)]=[x,y]
            except (TypeError,ValueError):pass
    return result


def load_project(key,folder=None):
    path=Path(folder or PROJECT_DIR)/(key+'.json')
    if not path.exists():return new_project()
    try:return validate_project(json.loads(path.read_text('utf-8')))
    except (OSError,ValueError,TypeError):return new_project()


def save_project(key,project,folder=None):
    path=Path(folder or PROJECT_DIR)/(key+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    value=validate_project(project)
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.tmp-sql-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as output:
            json.dump(value,output,ensure_ascii=False,indent=2,allow_nan=False)
        os.chmod(temp,0o600);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def manual_join(left,left_column,right,right_column):
    return {'left':left,'left_columns':[str(left_column)],'right':right,
            'right_columns':[str(right_column)],'kind':'manual'}


def visible_links(meta,project):
    selected=set(project['selected']);links=[]
    for table in project['selected']:
        for key in meta.get(table,{}).get('foreign_keys',[]):
            if key.get('right') not in selected:continue
            for lc,rc in zip(key.get('left_columns',[]),key.get('right_columns',[])):
                links.append({'left':table,'left_column':lc,'right':key['right'],'right_column':rc,'kind':'FK'})
    for key in project.get('joins',[]):
        if key.get('left') in selected and key.get('right') in selected:
            for lc,rc in zip(key.get('left_columns',[]),key.get('right_columns',[])):
                links.append({'left':key['left'],'left_column':lc,'right':key['right'],'right_column':rc,'kind':'manual'})
    return links


TABLES_SQL='''
SELECT n.nspname, c.relname, c.relkind, COALESCE(obj_description(c.oid,'pg_class'),'')
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind IN ('r','p','v','m')
 AND n.nspname NOT IN ('pg_catalog','information_schema')
 AND has_schema_privilege(n.oid,'USAGE')
ORDER BY n.nspname,c.relname
'''
COLUMNS_SQL='''
SELECT a.attname, format_type(a.atttypid,a.atttypmod), NOT a.attnotnull,
 COALESCE(col_description(c.oid,a.attnum),''), a.attnum
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped
ORDER BY a.attnum
'''
CONSTRAINTS_SQL='''
SELECT co.contype, co.conname,
 ARRAY(SELECT a.attname FROM unnest(co.conkey) WITH ORDINALITY r(num,pos)
       JOIN pg_attribute a ON a.attrelid=co.conrelid AND a.attnum=r.num ORDER BY r.pos),
 target_schema.nspname,target_table.relname,
 ARRAY(SELECT a.attname FROM unnest(co.confkey) WITH ORDINALITY r(num,pos)
       JOIN pg_attribute a ON a.attrelid=co.confrelid AND a.attnum=r.num ORDER BY r.pos)
FROM pg_catalog.pg_constraint co
JOIN pg_catalog.pg_class c ON c.oid=co.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_catalog.pg_class target_table ON target_table.oid=co.confrelid
LEFT JOIN pg_catalog.pg_namespace target_schema ON target_schema.oid=target_table.relnamespace
WHERE n.nspname=%s AND c.relname=%s AND co.contype IN ('p','f','u')
ORDER BY co.conname
'''


def pg_connect(config):
    import psycopg
    # Never save a credential dictionary; the connection is session-only.
    return psycopg.connect(**config)


def discover_tables(config):
    conn=pg_connect(config)
    try:
        with conn.cursor() as cur:
            cur.execute(TABLES_SQL)
            return [{'id':table_id(row[0],row[1]),'schema':row[0],
                     'name':row[1],'kind':row[2],'comment':row[3]} for row in cur.fetchall()]
    finally:
        if hasattr(conn,'close'):conn.close()


def inspect_tables(config,tables):
    conn=pg_connect(config);result={}
    try:
        with conn.cursor() as cur:
            for key in tables:
                schema,table=split_table_id(key)
                cur.execute(COLUMNS_SQL,(schema,table))
                columns=[{'name':r[0],'type':r[1],'nullable':r[2],
                          'comment':r[3],'pk':False,'fk':False} for r in cur.fetchall()]
                cur.execute(CONSTRAINTS_SQL,(schema,table))
                links=[]
                for kind,name,local,rschema,rtable,remote in cur.fetchall():
                    for col in columns:
                        if col['name'] in local:
                            if kind=='p':col['pk']=True
                            if kind=='f':col['fk']=True
                    if kind=='f':
                        links.append({'left':key,'left_columns':list(local),'right':table_id(rschema,rtable),
                                      'right_columns':list(remote),'constraint':name})
                result[key]={'columns':columns,'foreign_keys':links}
        return result
    finally:
        if hasattr(conn,'close'):conn.close()