"""Offscreen Qt smoke for integrated business-grounded local SQL workspace."""
import os
import unittest
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,"PySide6 unavailable")
class LocalSqlQtSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        cls.qt=QApplication.instance() or QApplication([])

    def test_open_local_sql_build_and_copy_only(self):
        from orbit_sql_ui import SQLExplorer
        from orbit_sql_core import SQLProject
        import tempfile
        class FakeDB:
            def columns(self,schema,table):
                return [{"name":"id","type":"bigint","primary_key":True,"comment":"","nullable":False},
                        {"name":"amount","type":"numeric","primary_key":False,"comment":"","nullable":True}]
            def foreign_keys(self,selected):return []
            def close(self):pass
        with tempfile.TemporaryDirectory() as td:
            explorer=SQLExplorer()
            try:
                project=SQLProject("localai",td)
                project.select(["public.sales"])
                explorer.project=project
                explorer.db=FakeDB()
                explorer.catalog=[{"schema":"public","name":"sales","kind":"table","comment":""}]
                explorer.columns={}
                explorer.fks=[]
                # Prepare a real persisted business definition first.
                from orbit_sql_semantics import BusinessSemantics
                logic=BusinessSemantics(project,explorer.catalog,{"public.sales":explorer.db.columns("public","sales")})
                logic.save_table("public.sales","Продажи","Сумма продаж","Одна строка = одна продажа")
                logic.save_metric("Выручка","public.sales","amount","SUM")
                explorer.navigation.setCurrentRow(6)
                self.assertIn("Спросить данные",explorer.pages[6])
                panel=explorer.local_sql_panel
                self.assertEqual(panel.planner.context()["metrics"]["Выручка"]["aggregation"],"SUM")
                panel.prompt.setPlainText("Покажи выручку по продажам")
                panel.inspect_context()
                self.assertIn("Таблиц: 1",panel.status.text())
                plan={"status":"ready","base_table":"public.sales",
                      "joins":[],"dimensions":[],"metrics":[{"name":"Выручка"}],
                      "filters":[],"having":[],"order_by":[],"limit":100}
                panel.events.put(("plan",plan))
                panel._poll()
                self.assertTrue(panel.copy.isEnabled())
                self.assertIn('SUM("t0"."amount")',panel.sql.toPlainText())
                self.assertNotIn("UPDATE",panel.sql.toPlainText())
                explorer.navigation.setCurrentRow(5)
                self.assertEqual(explorer.business_panel.logic.get_table("public.sales")["title"],
                                 "Продажи")
            finally:
                explorer.close()
                explorer.deleteLater()
                self.qt.processEvents()


if __name__=="__main__":
    unittest.main()
