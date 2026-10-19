"""ORBITclip v7.2.2 regression tests without Qt runtime."""
import ast
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from orbit_smart import action_catalog,clean_link,json_flatten,table_summary,table_remove_duplicates,python_summary,html_text,sql_summary
from orbit_version import CLIENT_VERSION

ROOT=Path(__file__).parent
CORE=(ROOT/'orbitclip.py').read_text(encoding='utf-8')
SPACES=(ROOT/'orbit_workspace_ui.py').read_text(encoding='utf-8')

class Smart722(unittest.TestCase):
    def test_json_to_table(self):
        steps=action_catalog('[{"id":1,"a":{"b":"Привет"}},{"id":2,"a":{"b":"Мир"}}]','json')
        step=next(x for x in steps if x['id']=='json.table')
        self.assertEqual(step['result'],'id\ta.b\n1\tПривет\n2\tМир')
        self.assertFalse(step['report'])
    def test_malformed_json_is_diagnostic(self):
        steps=action_catalog('{"broken":}','text')
        self.assertEqual(steps[0]['id'],'json.invalid')
        self.assertTrue(steps[0]['report'])
    def test_csv_quotes_and_dedup(self):
        data='name,comment\nA,"a,b"\nA,"a,b"\nB,z'
        self.assertIn('Повторяющихся строк: 1',table_summary(data))
        self.assertEqual(table_remove_duplicates(data),'name\tcomment\nA\ta,b\nB\tz')
    def test_sql_analysis_no_execution(self):
        self.assertIn('Параметры',sql_summary('SELECT * FROM t WHERE id=:foo').replace('параметры','Параметры'))
        self.assertIn('foo',sql_summary('SELECT * FROM t WHERE id=:foo'))
    def test_python_diagnostics(self):
        self.assertIn('Функции: f',python_summary('def f():\n return 42\n'))
        self.assertIn('Ошибка синтаксиса',python_summary('def bad(:'))
    def test_html_ignores_scripts(self):
        self.assertEqual(html_text('<h1>Hi</h1><script>bad()</script><p>Text</p>'),'Hi\nText')
    def test_remove_trackers_keep_other_params(self):
        self.assertEqual(clean_link('https://example.org?a=3&utm_source=test&gclid=7#top'),'https://example.org?a=3#top')
    def test_no_data_execution_or_network(self):
        self.assertNotIn('exec(', (ROOT/'orbit_smart.py').read_text())
        self.assertNotIn('requests.', (ROOT/'orbit_smart.py').read_text())

class UX722(unittest.TestCase):
    def test_version(self):
        self.assertEqual(CLIENT_VERSION,'7.8.6')
        self.assertIn('QT_CLIENT_VERSION = CLIENT_VERSION',CORE)
        for phrase in ("'ORBITclip · Библиотека · v'+CLIENT_VERSION", "'ORBITclip · Сообщения · v'+CLIENT_VERSION", "'ORBITclip · Настройки · v'+CLIENT_VERSION"):
            self.assertIn(phrase,CORE)
    def test_navigation(self):
        self.assertIn('def set_connect_section(self,index)',CORE)
        self.assertIn("(0,'Обзор'",CORE)
        self.assertIn("(1,'Устройства'",CORE)
        self.assertIn("(2,'По PIN'",CORE)
        self.assertIn("(3,'Сервер'",CORE)
        self.assertNotIn('self.source_picker=',CORE)
        self.assertIn("self.set_space_mode('apps')",CORE)
        self.assertIn("self.app.history.change_source(app)",SPACES)
    def test_svg_categories(self):
        for name in ('python','sql','code','json','html','link','table'):
            el=ET.parse(ROOT/'assets'/'icons'/f'{name}.svg').getroot()
            self.assertEqual(el.attrib['viewBox'],'0 0 24 24')
        self.assertIn('Py', (ROOT/'assets'/'icons'/'python.svg').read_text())
        self.assertIn('DB', (ROOT/'assets'/'icons'/'sql.svg').read_text())
    def test_smart_actions_have_side_by_side_preview(self):
        self.assertIn('comparison.addWidget(original,1);comparison.addWidget(output,1)',CORE)
        self.assertIn('action_catalog(',CORE)
        self.assertIn("if current['step']['report']",CORE)

if __name__=='__main__':unittest.main()
