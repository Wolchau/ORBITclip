"""ORBITclip 7.2.1 UX regression tests (source-level, no GUI dependency)."""
import ast
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).parent
SRC=(ROOT/'orbitclip.py').read_text('utf-8')
TREE=ast.parse(SRC)
CLASSES={x.name:x for x in TREE.body if isinstance(x,ast.ClassDef)}

def source_method(classname,name):
    method=next(x for x in CLASSES[classname].body if isinstance(x,ast.FunctionDef) and x.name==name)
    return ast.get_source_segment(SRC,method)

class UX721Tests(unittest.TestCase):
    def test_category_sidebar_only_contains_category_buttons(self):
        nav=source_method('VaultWindow','rebuild_nav')
        for old in ('ПРИЛОЖЕНИЯ-ИСТОЧНИКИ','Очередь Ctrl+колесо…','Возможности ✦','Редактор снимка…'):
            self.assertNotIn(old,nav)
        self.assertIn('self.app.categories.visible_categories()',nav)
        tools=source_method('VaultWindow','open_tools_menu')
        for entry in ('Управление категориями','Коллекции по приложениям','Порядок Ctrl + колесо','Настройки приложения'):
            self.assertIn(entry,tools)

    def test_shared_workspace_switcher_buttons_replaced_combo(self):
        history=ast.get_source_segment(SRC,CLASSES['VaultWindow'])
        self.assertNotIn('space_picker',history)
        self.assertIn('self.workspace_buttons.addWidget(button)',history)
        self.assertIn('self.selected_workspace',source_method('VaultWindow','refresh'))
        self.assertIn('self.choose_workspace(key)',history)

    def test_messenger_dialog_list_is_only_recipient_selector(self):
        chat=ast.get_source_segment(SRC,CLASSES['ChatWindow'])
        self.assertIn('self.dialog_list.currentItemChanged.connect(self.choose_dialog)',chat)
        self.assertNotIn('self.recipient',chat)
        self.assertIn('connected=list(self.app.identity.trusted)',source_method('ChatWindow','refresh_peers'))

    def test_chat_actions_are_hover_only_and_bubbles_narrow(self):
        bubble=ast.get_source_segment(SRC,CLASSES['MessageBubble'])
        self.assertIn('self.setMaximumWidth(475)',bubble)
        self.assertIn('self.hover_actions.hide()',bubble)
        self.assertIn('self.hover_actions.show()',source_method('MessageBubble','enterEvent'))
        self.assertIn('self.hover_actions.setGeometry',bubble)
        self.assertNotIn('foot.addWidget(cp)',bubble)

    def test_menu_hides_duplicate_star_delete_link_and_has_icons(self):
        menu=source_method('VaultRow','menu')
        self.assertIn('host.addAction(icon(name)',menu)
        self.assertNotIn('self.window.toggle_favorite(',menu)
        self.assertNotIn('self.window.remove_item(',menu)
        self.assertNotIn('self.open_link',menu)
        self.assertIn('Кольцевая прокрутка',menu)

    def test_tours_removed(self):
        self.assertNotIn('FeatureTourWindow',SRC)
        self.assertNotIn('QMovie',SRC)
        self.assertFalse((ROOT/'assets'/'onboarding').exists())
        self.assertNotIn('QTimer.singleShot(1100,self.open_tour)',SRC)

    def test_category_icons_are_valid_recognizable_svg(self):
        for name in ('python','sql','code','json','html','link','table'):
            root=ET.parse(ROOT/'assets'/'icons'/f'{name}.svg').getroot()
            self.assertEqual(root.attrib['viewBox'],'0 0 24 24')
        python=(ROOT/'assets'/'icons'/'python.svg').read_text('utf-8')
        self.assertIn('Py</text>',python)
        self.assertIn('viewBox="0 0 24 24"',python)

if __name__=='__main__':unittest.main()
