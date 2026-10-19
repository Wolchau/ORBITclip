"""Native/offscreen Qt regression for business semantics inside SQL Explorer."""
import os
import tempfile
import unittest

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,"PySide6 unavailable")
class BusinessQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        cls.qt=QApplication.instance() or QApplication([])

    def test_business_editor_saves_fields_and_builds_sql(self):
        from orbit_sql_core import SQLProject
        from orbit_sql_ui import SQLExplorer
        class FakeDB:
            def columns(self,schema,table):
                return [
                    {"name":"id","type":"bigint","nullable":False,
                     "primary_key":True,"comment":""},
                    {"name":"total","type":"numeric","nullable":False,
                     "primary_key":False,"comment":"Всего"},
                ]
            def foreign_keys(self,keys):
                return []
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            win=SQLExplorer()
            try:
                win.project=SQLProject("businessqt",tmp)
                win.project.select(["public.orders"])
                win.catalog=[{"schema":"public","name":"orders",
                              "kind":"table","comment":"Заказы"}]
                win.columns={}
                win.fks=[]
                win.db=FakeDB()
                self.assertIn("Бизнес-семантика",win.pages)
                win.navigation.setCurrentRow(5)
                editor=win.business_panel
                self.assertEqual(editor.tables.currentText(),"public.orders")
                self.assertEqual(editor.fields.rowCount(),2)
                editor.table_title.setText("Заказы покупателей")
                editor.table_grain.setText("Одна строка на заказ")
                editor.fields.item(1,1).setText("Сумма заказа")
                editor.fields.item(1,3).setText("RUB")
                editor.fields.cellWidget(1,2).setCurrentIndex(
                    editor.fields.cellWidget(1,2).findData("measure"))
                editor.fields.item(1,4).setText("Сумма до возвратов")
                editor.save_table()
                self.assertEqual(
                    editor.logic.get_table("public.orders")["grain"],
                    "Одна строка на заказ")
                self.assertEqual(
                    editor.logic.get_field("public.orders","total")["unit"],
                    "RUB")
                editor.metric_name.setText("Оборот")
                editor.metric_table.setCurrentText("public.orders")
                editor.metric_column.setCurrentText("total")
                editor.metric_agg.setCurrentIndex(
                    editor.metric_agg.findData("SUM"))
                editor.save_metric()
                self.assertIn('SUM("total") AS "Оборот"',
                              editor.sql_preview.toPlainText())
                self.assertIn("FROM \"public\".\"orders\"",
                              editor.sql_preview.toPlainText())
                win.navigation.setCurrentRow(2)
                win.navigation.setCurrentRow(5)
                self.assertIn("Оборот",win.business_panel.logic.data["metrics"])
                self.assertEqual(
                    SQLProject("businessqt",tmp).data["business"]["tables"]
                    ["public.orders"]["title"],"Заказы покупателей")
            finally:
                win.close()
                win.deleteLater()
                self.qt.processEvents()


if __name__=="__main__":
    unittest.main()
