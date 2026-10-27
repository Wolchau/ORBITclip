"""Business semantics persistence, source safety and SQL generation regressions."""
import json
from pathlib import Path
import tempfile
import unittest

from orbit_sql_core import SQLProject
from orbit_sql_semantics import (
    BusinessSemantics, quote_ident, AGGREGATIONS,
)
from orbit_version import CLIENT_VERSION


CATALOG=[
    {"schema":"public","name":"sales","kind":"table",
     "comment":"Операции продаж"},
    {"schema":"public","name":"customers","kind":"table",
     "comment":"Справочник клиентов"},
]
COLUMNS={
    "public.sales":[
        {"name":"id","type":"bigint","nullable":False,"primary_key":True,"comment":""},
        {"name":"customer_id","type":"bigint","nullable":False,"primary_key":False,"comment":""},
        {"name":"price","type":"numeric","nullable":True,"primary_key":False,"comment":"Стоимость"},
        {"name":"paid_at","type":"date","nullable":True,"primary_key":False,"comment":""},
    ],
    "public.customers":[
        {"name":"id","type":"bigint","nullable":False,"primary_key":True,"comment":""},
        {"name":"display_name","type":"text","nullable":False,"primary_key":False,"comment":""},
    ],
}


class SemanticModelTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.project=SQLProject("session01",self.folder.name)
        self.project.select(["public.sales","public.customers"])
        self.logic=BusinessSemantics(self.project,CATALOG,COLUMNS)

    def test_version(self):
        self.assertEqual(CLIENT_VERSION,"7.9.0")

    def test_table_field_definitions_survive_restart(self):
        self.logic.save_table("public.sales","Продажи",
            "Все проведённые и непроведённые операции",
            "Одна строка — одна операция продажи")
        self.logic.save_field("public.sales","price","Сумма продажи",
            "Сумма в валюте заказа","currency","RUB")
        self.logic.save_field("public.sales","customer_id","Покупатель",
            "Идентификатор клиента","identifier")
        restored=SQLProject("session01",self.folder.name)
        recovered=BusinessSemantics(restored,CATALOG,COLUMNS)
        self.assertEqual(recovered.get_table("public.sales")["title"],"Продажи")
        self.assertEqual(recovered.get_field("public.sales","price")["unit"],"RUB")
        self.assertEqual(recovered.get_field("public.sales","customer_id")["role"],
                         "identifier")
        self.assertEqual(restored.data["selected"],
                         ["public.sales","public.customers"])
        # Existing old SQL annotations and manually-added joins are retained.
        self.assertIn("comments",restored.data)
        self.assertIn("joins",restored.data)

    def test_metric_compiles_only_verified_columns(self):
        self.logic.save_metric("Выручка","public.sales","price","SUM",
                               "Выручка по продажам, без вычета возвратов","RUB")
        statement=self.logic.compile_metric("Выручка","customer_id")
        self.assertEqual(statement,
            'SELECT\n    "customer_id",\n'
            '    SUM("price") AS "Выручка"\n'
            'FROM "public"."sales"\n'
            'GROUP BY "customer_id"\nORDER BY "customer_id";')
        self.assertNotIn("JOIN",statement)
        self.assertEqual(
            self.logic.compile_metric("Выручка"),
            'SELECT\n    SUM("price") AS "Выручка"\nFROM "public"."sales";'
        )
        self.logic.save_metric("Заказы","public.sales","","COUNT_ROWS",
                               "Количество строк")
        self.assertIn('COUNT(*) AS "Заказы"',self.logic.compile_metric("Заказы"))
        self.logic.save_metric("Уникальные клиенты","public.sales","customer_id",
                               "COUNT_DISTINCT")
        self.assertIn('COUNT(DISTINCT "customer_id")',
                      self.logic.compile_metric("Уникальные клиенты"))
        self.assertEqual(len(AGGREGATIONS),7)

    def test_no_dangerous_expression_in_sql(self):
        self.logic.save_metric('Сумма "особая"','public.sales',"price","SUM")
        self.assertIn('AS "Сумма ""особая"""',
                      self.logic.compile_metric('Сумма "особая"'))
        for bad in ('price); DROP TABLE sales;--',"nonexistent"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.logic.save_metric("Ошибка","public.sales",bad,"SUM")
        with self.assertRaises(ValueError):
            self.logic.compile_metric('Сумма "особая"','id); DELETE FROM sales')
        with self.assertRaises(ValueError):
            self.logic.save_metric("Bad","public.sales","price","SUM);DROP")
        self.assertEqual(quote_ident('col"name'),'"col""name"')

    def test_relation_and_glossary_persist(self):
        key=self.logic.save_relation(
            "public.sales","customer_id","public.customers","id",
            "Заказ связан с покупателем; суммы повторяются при N:N","N:1")
        self.logic.save_glossary("Активный клиент",
                                 "Совершил хотя бы одну покупку за 90 дней")
        restored=SQLProject("session01",self.folder.name)
        state=BusinessSemantics(restored,CATALOG,COLUMNS).data
        self.assertEqual(state["relations"][key]["cardinality"],"N:1")
        self.assertIn("Активный клиент",state["glossary"])
        self.assertTrue(self.logic.delete_glossary("Активный клиент"))
        self.assertFalse(self.logic.delete_glossary("Активный клиент"))

    def test_context_exports_metadata_only(self):
        self.logic.save_table("public.sales","Продажи",
                              "Операции клиента","Одна продажа")
        self.logic.save_metric("Выручка","public.sales","price","SUM")
        context=self.logic.context()
        self.assertEqual(len(context["tables"]),2)
        self.assertEqual(context["tables"][0]["fields"][2]["name"],"price")
        self.assertIn("Выручка",context["metrics"])
        self.assertNotIn("password",json.dumps(context))
        self.assertEqual(context["tables"][0]["title"],"Продажи")

    def test_invalid_physical_mapping_rejected(self):
        with self.assertRaises(ValueError):
            self.logic.save_table("public.secret","Тайна","","")
        with self.assertRaises(ValueError):
            self.logic.save_field("public.sales","not_a_column","X","","measure")
        with self.assertRaises(ValueError):
            self.logic.save_field("public.sales","price","X","","unknown")
        with self.assertRaises(ValueError):
            self.logic.save_relation(
                "public.sales","unknown","public.customers","id","","1:N")
        with self.assertRaises(ValueError):
            self.logic.save_glossary("","Definition")
        self.assertEqual(self.logic.data["metrics"],{})

    def test_old_project_migrates_without_losing_annotations(self):
        path=Path(self.folder.name)/"legacy001.json"
        path.write_text(json.dumps({
            "selected":["public.sales"],"comments":{"public.sales.price":"old"},
            "joins":[],"positions":{"public.sales":[10,20]}}),encoding="utf-8")
        project=SQLProject("legacy001",self.folder.name)
        logic=BusinessSemantics(project,CATALOG,COLUMNS)
        logic.save_table("public.sales","Sales","","")
        reloaded=SQLProject("legacy001",self.folder.name)
        self.assertEqual(reloaded.data["comments"]["public.sales.price"],"old")
        self.assertEqual(reloaded.data["positions"]["public.sales"],[10,20])
        self.assertEqual(reloaded.data["business"]["tables"]["public.sales"]["title"],
                         "Sales")


if __name__=="__main__":
    unittest.main()
