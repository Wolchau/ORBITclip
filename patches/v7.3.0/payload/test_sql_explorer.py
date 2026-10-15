"""Headless regression tests of the PostgreSQL explorer domain logic and UI wiring."""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orbit_sql_core import (
    profile_key, table_id, split_table_id, load_project, save_project,
    new_project, manual_join, visible_links, inspect_tables, discover_tables,
    field_note_key, TABLES_SQL, COLUMNS_SQL
)

ROOT=Path(__file__).parent


class ProjectTests(unittest.TestCase):
    def test_profile_separates_databases(self):
        a=profile_key(' DB.Local ',5432,'sales','readonly')
        self.assertEqual(a,profile_key('db.local',5432,'sales','readonly'))
        self.assertNotEqual(a,profile_key('db.local',5432,'ops','readonly'))

    def test_ids_support_dots_and_unicode(self):
        value=table_id('отчёт.архив','заказы 2026')
        self.assertEqual(split_table_id(value),('отчёт.архив','заказы 2026'))

    def test_roundtrip_annotations_no_credential(self):
        with tempfile.TemporaryDirectory() as d:
            key=profile_key('localhost',5432,'data','reader')
            p=new_project();tbl=table_id('public','orders')
            p['selected']=[tbl]
            p['notes'][field_note_key(tbl,'id')]='Ключ заказа'
            p['positions'][tbl]=[12,16]
            p['joins']=[manual_join(tbl,'user_id',table_id('public','users'),'id')]
            save_project(key,p,Path(d))
            text=(Path(d)/(key+'.json')).read_text()
            self.assertNotIn('password',text)
            self.assertEqual(load_project(key,Path(d))['notes'][field_note_key(tbl,'id')],'Ключ заказа')
            self.assertEqual(load_project(key,Path(d))['positions'][tbl],[12.0,16.0])

    def test_malformed_positions_removed(self):
        from orbit_sql_core import validate_project
        p=new_project();p['positions'][table_id('s','x')]=[float('inf'),1]
        # Infinity rejected from persisted coordinate domain.
        self.assertEqual(validate_project(p)['positions'], {})

    def test_fk_multicolumn_and_manual(self):
        a=table_id('public','transactions');b=table_id('public','people')
        p=new_project();p['selected']=[a,b];p['joins']=[manual_join(a,'creator_id',b,'id')]
        meta={a:{'foreign_keys':[{'left':a,'left_columns':['owner_id','region_id'],'right':b,'right_columns':['id','region_id']} ]},
              b:{'foreign_keys':[]}}
        links=visible_links(meta,p)
        self.assertEqual([x['kind'] for x in links],['FK','FK','manual'])

    def test_catalog_queries_are_metadata_only(self):
        self.assertIn('pg_catalog.pg_class',TABLES_SQL)
        self.assertIn('has_schema_privilege',TABLES_SQL)
        self.assertIn('n.nspname=%s',COLUMNS_SQL)
        self.assertNotIn('SELECT * FROM',TABLES_SQL)

    def test_ui_entry_wired(self):
        source=(ROOT/'orbitclip.py').read_text(encoding='utf8')
        tree=ast.parse(source)
        app=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='OrbitApp')
        self.assertIn('open_sql_explorer',[x.name for x in app.body if isinstance(x,ast.FunctionDef)])
        self.assertIn('SQL Explorer',source)


class FakeCursor:
    def __init__(self):self.sql=[];self.params=[];self.result=[]
    def execute(self,sql,params=None):
        self.sql.append(sql);self.params.append(params)
        if 'FROM pg_catalog.pg_attribute a' in sql:
            self.result=[('id','bigint',False,'Ключ',1),('customer_id','bigint',True,'',2)]
        elif 'FROM pg_catalog.pg_constraint co' in sql:
            self.result=[('p','orders_pkey',['id'],None,None,[]),
                         ('f','orders_customer_fkey',['customer_id'],'public','customers',['id'])]
        else:self.result=[('public','orders','r','Заказы')]
    def fetchall(self):return self.result
    def __enter__(self):return self
    def __exit__(self,*args):pass

class FakeConn:
    def __init__(self):self.cursorobj=FakeCursor()
    def cursor(self):return self.cursorobj
    def __enter__(self):return self
    def __exit__(self,*args):pass

class PgTests(unittest.TestCase):
    def test_schema_listing(self):
        c=FakeConn()
        with patch('orbit_sql_core.pg_connect',return_value=c):
            result=discover_tables({})
        self.assertEqual(result[0]['id'],table_id('public','orders'))
    def test_metadata_and_fk(self):
        c=FakeConn();tbl=table_id('public','orders')
        with patch('orbit_sql_core.pg_connect',return_value=c):
            details=inspect_tables({},[tbl])
        self.assertTrue(details[tbl]['columns'][0]['pk'])
        self.assertTrue(details[tbl]['columns'][1]['fk'])
        self.assertEqual(details[tbl]['foreign_keys'][0]['right'],table_id('public','customers'))
        self.assertEqual(c.cursorobj.params, [('public','orders'),('public','orders')])

if __name__=='__main__':unittest.main()
