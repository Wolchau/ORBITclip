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
