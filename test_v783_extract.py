"""7.8.3 Extract + exploratory local semantic search regressions."""
import json
import tempfile
import unittest
from orbit_extract import inspect,export_table,entity_rows
from orbit_semantic import find
from orbit_version import CLIENT_VERSION


class ExtractTests(unittest.TestCase):
    def test_key_value_business_extract_provenance(self):
        text=('ООО Пример\nВыручка: 12 450 000 руб.\nМаржинальность: 18,4%\n'
              'Количество заказов: 3 127\nДата: 02.10.2026\n'
              'Номер заказа: 001238')
        output=inspect(text)
        self.assertEqual(output['kind'],'fields')
        self.assertEqual(output['rows'][0],['Поле','Значение'])
        self.assertIn(['Выручка','12 450 000 руб.'],output['rows'])
        self.assertIn('revenue',[x['key'] for x in output['fields']])
        self.assertIn({'type':'date','source':'02.10.2026','value':'2026-10-02'},
                      output['entities'])
        self.assertTrue(any(x['type']=='quantity' and '18,4%' in x['source']
                            for x in output['entities']))
        self.assertTrue(any(x['type']=='identifier' and x['value']=='001238'
                            for x in output['entities']))
        self.assertIn('12 450 000',export_table(output['rows'],'tsv'))

    def test_nested_json_to_table_no_assumed_numbers(self):
        data=[{'city':'Москва','sum':1500,'nested':{'margin':0.2}},
              {'city':'Казань','sum':3400,'nested':{'margin':0.15}}]
        o=inspect(json.dumps(data,ensure_ascii=False))
        self.assertEqual(o['kind'],'json')
        self.assertEqual(o['rows'][0],['city','sum','nested.margin'])
        self.assertEqual(o['rows'][2],['Казань','3400','0.15'])
        converted=json.loads(export_table(o['rows'],'json'))
        self.assertEqual(converted[0]['sum'],'1500')
        self.assertIn('Казань',export_table(o['rows'],'csv'))

    def test_delimited_and_markdown(self):
        table=inspect('Город;Оборот\nМосква;1200\nКазань;3400')
        self.assertEqual(table['rows'][1],['Москва','1200'])
        self.assertEqual(table['kind'],'table')
        markdown=inspect('| Name | Sum |\n| --- | --- |\n| A | 12 |')
        self.assertEqual(markdown['rows'],[['Name','Sum'],['A','12']])
        self.assertEqual(export_table(markdown['rows'],'tsv'),'Name\tSum\nA\t12')

    def test_reject_invalid_dates_and_fake_csv(self):
        result=inspect('Дата: 31.02.2026\nОборот: 5 000 руб.')
        self.assertFalse(any(e['type']=='date' for e in result['entities']))
        self.assertTrue(any(e['type']=='quantity' for e in result['entities']))
        self.assertIsNone(inspect('Стоимость 15,45 руб. но не CSV')['rows'])

    def test_input_bounds_and_no_runtime_execution(self):
        with self.assertRaises(ValueError):inspect('')
        with self.assertRaises(ValueError):inspect('a'*200001)
        sample="__import__('os').system('echo exploit')"
        self.assertEqual(inspect(sample)['kind'],'text')
        self.assertIsNone(inspect(sample)['rows'])

    def test_source_values_unchanged_and_email(self):
        info=inspect('Связь: sample@example.org\nДата: 5 октября 2026')
        self.assertIn('sample@example.org',
                      [x['value'] for x in info['entities']])
        self.assertIn('2026-10-05',
                      [x['value'] for x in info['entities']])
        self.assertEqual(entity_rows(info['entities'])[0],
                         ['Тип','Исходное значение','Распознанное значение'])


class SemanticHintsTests(unittest.TestCase):
    def test_recall_synonyms_russian(self):
        data=[{'text':'После пересмотра тарифов рентабельность снизилась'},
              {'text':'Погодные условия и прогноз'},
              {'text':'Новые планы продаж'}]
        found=find('изменение цены маржа',data)
        self.assertEqual(found[0],data[0])

    def test_exact_ids_win_and_encrypted_ignored(self):
        records=[{'text':'идентификатор idsending 837264'},
                 {'text':'ошибка idsending 837265'},
                 {'text':'idsending 837264 secret','encrypted':True}]
        self.assertEqual(find('837264',records),[records[0]])
        self.assertEqual(find('secret',records),[])

    def test_no_side_effects_empty_search(self):
        records=[{'text':'маржа'}]
        old=[dict(x) for x in records]
        self.assertEqual(find('',records),[])
        self.assertEqual(find('маржинальность',records),records)
        self.assertEqual(records,old)


if __name__=='__main__':unittest.main()
