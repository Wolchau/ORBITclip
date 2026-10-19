"""7.8.7: structured local text-to-SQL planner safety and business-context tests."""
import json
import unittest
from unittest.mock import patch
from io import BytesIO

from orbit_sql_core import SQLProject
from orbit_sql_semantics import BusinessSemantics
from orbit_sql_planner import SQLPlanner, PlanError
from orbit_sql_ollama import local_plan, make_request, OLLAMA_URL

CATALOG=[{"schema":"public","name":x,"kind":"table","comment":""}
         for x in ("sales","customers","items")]
COLUMNS={
    "public.sales":[
        {"name":"id","type":"bigint"},
        {"name":"customer_id","type":"bigint"},
        {"name":"amount","type":"numeric(12,2)"},
        {"name":"created_at","type":"date"}],
    "public.customers":[
        {"name":"id","type":"bigint"},
        {"name":"display_name","type":"text"}],
    "public.items":[
        {"name":"id","type":"bigint"},
        {"name":"sale_id","type":"bigint"},
        {"name":"product","type":"text"}],
}
FKS=[
    {"source_schema":"public","source_table":"sales","source_column":"customer_id",
     "target_schema":"public","target_table":"customers","target_column":"id"},
    {"source_schema":"public","source_table":"items","source_column":"sale_id",
     "target_schema":"public","target_table":"sales","target_column":"id"}
]


class FakeProject:
    def __init__(self):
        self.data={"selected":["public.sales","public.customers","public.items"],
                   "comments":{},"positions":{},"joins":[],"business":{}}
    def save(self):pass


def base_plan():
    return {
        "status":"ready","base_table":"public.sales",
        "joins":[{"from_table":"public.sales","from_column":"customer_id",
                  "to_table":"public.customers","to_column":"id","join_type":"LEFT"}],
        "dimensions":[{"table":"public.customers","column":"display_name","alias":"Клиент"}],
        "metrics":[{"name":"Выручка"}],
        "filters":[{"table":"public.sales","column":"created_at",
                    "op":"gte","value":"2026-01-01"}],
        "having":[{"metric":"Выручка","op":"gt","value":10000}],
        "order_by":[{"by":"Выручка","direction":"DESC"}],
        "limit":100,"assumptions":["Считаем сумму по всем продажам"]
    }


class PlanCompilerTests(unittest.TestCase):
    def setUp(self):
        self.project=FakeProject()
        self.semantics=BusinessSemantics(self.project,CATALOG,COLUMNS)
        self.semantics.save_table("public.sales","Продажи","Продажа по клиенту",
                                  "Одна строка = одна продажа")
        self.semantics.save_field("public.sales","amount","Выручка","Денежная сумма",
                                  "measure","RUB")
        self.semantics.save_metric("Выручка","public.sales","amount","SUM",
                                   "Общая выручка", "RUB")
        self.semantics.save_metric("Заказы","public.sales","","COUNT_ROWS")
        self.semantics.save_glossary("Покупка","Завершённая операция продажи")
        self.compiler=SQLPlanner(self.semantics,FKS)

    def test_context_contains_business_but_no_rows_or_password(self):
        ctx=self.compiler.context()
        self.assertEqual(ctx["tables"][0]["grain"],"Одна строка = одна продажа")
        self.assertEqual(ctx["tables"][0]["fields"][2]["title"],"Выручка")
        self.assertEqual(ctx["metrics"]["Выручка"]["aggregation"],"SUM")
        self.assertEqual(ctx["glossary"]["Покупка"],"Завершённая операция продажи")
        self.assertEqual(len(ctx["fks"]),2)
        self.assertNotIn("password",json.dumps(ctx))
        self.assertNotIn("rows",json.dumps(ctx))

    def test_local_ollama_request_only_selected_metadata(self):
        request=make_request("Выручка по клиентам",self.compiler.context(),"qwen3:4b")
        self.assertEqual(request["model"],"qwen3:4b")
        self.assertIs(request["stream"],False)
        self.assertEqual(len(request["messages"]),2)
        text=request["messages"][1]["content"]
        self.assertIn("Общая выручка",text)
        self.assertIn("Одна строка",text)
        self.assertNotIn("localhost:5432",text)

    def test_compiles_multi_table_group_filters_having_order_without_exec(self):
        sql=self.compiler.compile(base_plan())["sql"]
        self.assertIn('FROM "public"."sales" AS "t0"',sql)
        self.assertIn('LEFT JOIN "public"."customers" AS "t1"',sql)
        self.assertIn('"t0"."customer_id" = "t1"."id"',sql)
        self.assertIn('SUM("t0"."amount") AS "Выручка"',sql)
        self.assertIn('"t0"."created_at" >= \'2026-01-01\'',sql)
        self.assertIn('HAVING SUM("t0"."amount") > 10000',sql)
        self.assertIn('GROUP BY "t1"."display_name"',sql)
        self.assertTrue(sql.endswith("LIMIT 100;"))
        self.assertNotIn("DELETE ",sql)

    def test_reverse_one_to_many_join_rejected_for_aggregation(self):
        plan=base_plan()
        plan["base_table"]="public.sales"
        plan["joins"]=[{"from_table":"public.sales","from_column":"id",
                         "to_table":"public.items","to_column":"sale_id","join_type":"LEFT"}]
        plan["dimensions"]=[]
        plan["filters"]=[]
        plan["having"]=[]
        plan["order_by"]=[]
        with self.assertRaisesRegex(PlanError,"дублировать"):
            self.compiler.compile(plan)

    def test_join_not_declared_rejected(self):
        plan=base_plan()
        plan["joins"][0]["from_column"]="id"
        with self.assertRaisesRegex(PlanError,"отсутствует"):
            self.compiler.compile(plan)

    def test_nonexistent_column_and_unknown_metric_rejected(self):
        plan=base_plan()
        plan["filters"][0]["column"]="fake"
        with self.assertRaises(PlanError):self.compiler.compile(plan)
        plan=base_plan()
        plan["metrics"]=[{"name":"Непонятный показатель"}]
        with self.assertRaisesRegex(PlanError,"Неизвестная"):
            self.compiler.compile(plan)

    def test_sql_injection_in_values_and_identifiers_blocked(self):
        plan=base_plan()
        plan["filters"].append({"table":"public.customers","column":"display_name",
                                "op":"eq","value":"x'; DROP TABLE customer; --"})
        sql=self.compiler.compile(plan)["sql"]
        self.assertIn("'x''; DROP TABLE customer; --'",sql)
        plan["filters"][0]["value"]="2026-01-01'; DELETE FROM sales"
        with self.assertRaises(PlanError):self.compiler.compile(plan)
        plan=base_plan()
        plan["joins"][0]["join_type"]="LEFT;DELETE"
        with self.assertRaises(PlanError):self.compiler.compile(plan)

    def test_unsafe_numeric_value_or_missing_limit_is_rejected(self):
        plan=base_plan()
        plan["having"][0]["value"]="10000 OR TRUE"
        with self.assertRaises(PlanError):self.compiler.compile(plan)
        plan=base_plan()
        plan["limit"]=99999999
        with self.assertRaises(PlanError):self.compiler.compile(plan)

    def test_clarification_and_unselected_context(self):
        self.assertEqual(self.compiler.compile({"status":"clarify",
                          "question":"Какие статусы продаж учитывать?"})["status"],
                         "clarify")
        self.project.data["selected"]=["public.sales"]
        with self.assertRaisesRegex(PlanError,"вне выбранной"):
            self.compiler.compile(base_plan())

    def test_manual_join_without_cardinality_blocks_sum(self):
        self.project.data["joins"].append({
            "left":"public.sales","left_column":"id",
            "right":"public.items","right_column":"sale_id"})
        plan=base_plan()
        plan["joins"]=[{"from_table":"public.sales","from_column":"id",
                         "to_table":"public.items","to_column":"sale_id","join_type":"LEFT"}]
        plan["dimensions"]=[]
        with self.assertRaisesRegex(PlanError,"дублировать"):
            self.compiler.compile(plan)

    def test_only_strict_structure_accepted(self):
        plan=base_plan()
        plan["sql"]="DROP TABLE sales;"
        with self.assertRaisesRegex(PlanError,"ключи"):
            self.compiler.compile(plan)
        with self.assertRaises(PlanError):make_request("Hello",self.compiler.context(),
                                                        "http://remote.example.com")


class OllamaTransportTests(unittest.TestCase):
    def test_only_fixed_loopback_and_validated_json(self):
        answer={"message":{"content":json.dumps({"status":"clarify",
                                   "question":"Какой период?"},ensure_ascii=False)}}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return json.dumps(answer).encode()
        with patch("urllib.request.urlopen",return_value=Response()) as client:
            result=local_plan("Вопрос",{"tables":[{"name":"public.sales"}]})
            self.assertEqual(result["status"],"clarify")
            request=client.call_args.args[0]
            self.assertEqual(request.full_url,OLLAMA_URL)
            data=json.loads(request.data)
            self.assertEqual(data["format"],"json")
            self.assertFalse(data["stream"])


if __name__=="__main__":unittest.main()
