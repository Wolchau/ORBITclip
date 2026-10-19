"""7.8.8: local history filtering, date scope and progressive presentation."""
import tempfile
import time
import unittest
from pathlib import Path
from kinetic_clipboard import ClipboardVault
from orbit_history_view import PAGE_SIZE, history_matches, visible_page, period_start

class HistoryPerformanceTests(unittest.TestCase):
    def entry(self,n,ts=None,**kwargs):
        return {"id":str(n),"text":"file "+str(n),"title":"",
                "kind":"text","source_app":"Browser","ts":ts or time.time(),
                "encrypted":None,**kwargs}

    def test_initial_page_stays_bounded_but_every_record_remains_available(self):
        entries=[self.entry(i) for i in range(620)]
        all_items=history_matches(entries)
        first,remaining=visible_page(all_items)
        self.assertEqual(len(first),PAGE_SIZE)
        self.assertEqual(remaining,620-PAGE_SIZE)
        self.assertEqual(len(entries),620)
        page,remaining=visible_page(all_items,620)
        self.assertEqual((len(page),remaining),(620,0))
        self.assertEqual([v["id"] for v in page],[str(i) for i in range(620)])

    def test_search_matches_untruncated_text_and_preserves_order(self):
        entries=[self.entry(1,text="x"*120000+" Уникальный Артикул"),
                 self.entry(2,text="ничего похожего"),
                 self.entry(3,text="артикул не из той категории",source_app="Excel")]
        found=history_matches(entries,"АРТИКУЛ")
        self.assertEqual([x["id"] for x in found],["1","3"])
        found=history_matches(entries,"артикул",source="Excel")
        self.assertEqual([x["id"] for x in found],["3"])
        found=history_matches(entries,category_match=lambda x:x["id"]!="3")
        self.assertEqual([x["id"] for x in found],["1","2"])

    def test_protected_entry_is_never_semantically_indexed(self):
        protected=self.entry(1,title="protected",text="",
                             encrypted={"ciphertext":"private"})
        records=[protected,self.entry(2,text="выручка компании")]
        self.assertEqual(history_matches(records,"protected"),[protected])
        self.assertEqual(history_matches(records,"выручка",semantic=True),
                         [records[1]])
        self.assertEqual(history_matches(records,"protected",semantic=True),[])

    def test_calendar_today_and_rolling_intervals(self):
        now=time.time()
        entries=[self.entry(1,ts=now),self.entry(2,ts=now-4*86400),
                 self.entry(3,ts=now-15*86400),self.entry(4,ts=now-45*86400)]
        self.assertEqual([e["id"] for e in history_matches(entries,period="week",now=now)],
                         ["1","2"])
        self.assertEqual([e["id"] for e in history_matches(entries,period="month",now=now)],
                         ["1","2","3"])
        self.assertEqual(len(history_matches(entries,period="all",now=now)),4)
        self.assertLessEqual(period_start("today",now),now)
        self.assertGreater(period_start("today",now),now-86401)
        with self.assertRaises(ValueError):
            history_matches(entries,period="wrong")

    def test_search_never_changes_history_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"history.json"
            vault=ClipboardVault(path)
            vault.add("Маржа снизилась после корректировки тарифа","Excel")
            vault.add("Чувствительные идентификаторы","Browser")
            before=path.read_bytes()
            _=history_matches(vault.items,"маржа")
            _=visible_page(history_matches(vault.items,period="today"))
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(vault.items),2)

if __name__=="__main__":
    unittest.main()
