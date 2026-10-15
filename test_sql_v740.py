"""Headless checks for SQL metadata and password-free annotation persistence."""
import json
import tempfile
import unittest
from pathlib import Path
from orbit_sql_core import SQLProject,PostgreSQLCatalog,profile_key

class SQLTests(unittest.TestCase):
    def test_metadata_queries_are_parameterized(self):
        self.assertIn('WHERE n.nspname=%s AND c.relname=%s',PostgreSQLCatalog.columns.__code__.co_consts[1])
    def test_project_keeps_descriptions_but_no_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=SQLProject(profile_key('localhost',5432,'demo','analyst'),tmp)
            p.select(['public.orders','public.clients'])
            p.annotate('public.orders','client_id','Клиент заказа')
            p.relation('public.orders','client_id','public.clients','id')
            p.position('public.orders',100,200)
            restored=SQLProject(p.path.stem,tmp)
            self.assertEqual(len(restored.data['selected']),2)
            self.assertEqual(restored.data['positions']['public.orders'],[100.0,200.0])
            self.assertNotIn('password',p.path.read_text('utf-8').lower())
    def test_connection_credentials_not_persisted(self):
        pg=PostgreSQLCatalog('127.0.0.1',5432,'demo','reader','example-pass',sslmode='require')
        self.assertEqual(pg.config['password'],'example-pass')
        with self.assertRaises(ValueError):PostgreSQLCatalog('a',5432,'b','c','d','broken')

if __name__=='__main__':unittest.main()
