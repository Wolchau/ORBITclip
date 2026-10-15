import unittest,tempfile,json
from pathlib import Path
from orbit_smart import clean_link,smart_actions,table_transpose
from orbit_workspaces import Workspaces
class Dummy:
 def __init__(self,d):
  self.id=d;self.trusted={}
class TestSmart(unittest.TestCase):
 def test_link(self):self.assertEqual(clean_link('https://e.org/p?a=1&utm_source=abc&fbclid=x#anchor'),'https://e.org/p?a=1#anchor')
 def test_json(self):self.assertIn('"k": 1',smart_actions('{"k":1}','json')['Форматировать JSON'][1])
 def test_table(self):self.assertIn('name\tА',table_transpose('name\tage\nА\t20'))
 def test_no_code_execution(self):self.assertIn('Синтаксис',smart_actions('print(1)','python')['Проверить синтаксис'][1])
 def test_workspace_consent(self):
  with tempfile.TemporaryDirectory() as folder:
   a,b=Dummy('a'*32),Dummy('b'*32)
   a.trusted[b.id]={'name':'b'};b.trusted[a.id]={'name':'a'}
   owner=Workspaces(a,Path(folder)/'owner.json');guest=Workspaces(b,Path(folder)/'guest.json')
   s=owner.create('Team',[b.id])
   self.assertEqual(guest.receive(a.id,owner.envelope(s['id'],'invite',name=s['name'])),'invite')
   self.assertEqual(guest.spaces[s['id']]['members'][b.id],'pending')
   with self.assertRaises(ValueError):guest.chat(s['id'],'premature')
   response=guest.decide(s['id'],True)
   self.assertEqual(owner.receive(b.id,response),'joined')
   self.assertEqual(owner.spaces[s['id']]['members'][b.id],'accepted')
   self.assertEqual(guest.receive(a.id,owner.envelope(s['id'],'roster',members=s['members'])),'update')
   self.assertEqual(guest.receive(a.id,owner.publish(s['id'],{'text':'secret? not automatic','kind':'text','encrypted':None})),'update')
   self.assertEqual(guest.spaces[s['id']]['clips'][0]['text'],'secret? not automatic')
   with self.assertRaises(ValueError):owner.publish(s['id'],{'text':'','encrypted':{'x':'cipher'}})
if __name__=='__main__':unittest.main()
