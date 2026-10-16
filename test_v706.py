"""Pure-Python checks for the packaged defaults and the Windows tray lifecycle.

No dependency on PySide6; production tray methods are executed against doubles.
"""
from __future__ import annotations
import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import platform
from unittest.mock import patch
from orbit_client_defaults import load_connection_defaults, resolve_connection_settings

ROOT=Path(__file__).parent


class DefaultsTests(unittest.TestCase):
    def test_package_has_url_but_no_embedded_token(self):
        initial=load_connection_defaults(ROOT/'client_defaults.json')
        self.assertEqual(initial['https_url'],'https://kinetic-relay.onrender.com')
        self.assertFalse(initial.get('https_token'))

    def test_new_user_gets_default_connection(self):
        url,token=resolve_connection_settings({},ROOT/'client_defaults.json','https://fallback.example')
        initial=load_connection_defaults(ROOT/'client_defaults.json')
        self.assertEqual(url,initial['https_url'])
        self.assertEqual(token,'')

    def test_existing_user_values_win(self):
        url,token=resolve_connection_settings({'https_url':'https://my-relay.test','https_token':'own-private-token'},ROOT/'client_defaults.json','x')
        self.assertEqual((url,token),('https://my-relay.test','own-private-token'))

    def test_empty_settings_get_filled(self):
        url,token=resolve_connection_settings({'https_url':'','https_token':''},ROOT/'client_defaults.json','x')
        self.assertEqual(url,'https://kinetic-relay.onrender.com')
        self.assertEqual(token,'')

    def test_invalid_defaults_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'defaults.json'
            file.write_text('{invalid',encoding='utf-8')
            self.assertEqual(load_connection_defaults(file),{})
            self.assertEqual(resolve_connection_settings({},file,'https://fallback'),('https://fallback',''))
            file.write_text(json.dumps({'https_token':123,'https_url':'  x  ','other':'secret'}))
            self.assertEqual(load_connection_defaults(file),{'https_url':'x'})


class Signal:
    def __init__(self):self.callback=None
    def connect(self,cb):self.callback=cb


class FakeAction:
    def __init__(self,label,cb):self.text=label;self.callback=cb
    def setText(self,value):self.text=value


class FakeMenu:
    def __init__(self):self.actions=[]
    def addAction(self,label,cb):
        action=FakeAction(label,cb);self.actions.append(action);return action
    def addSeparator(self):pass


class FakeTray:
    enabled=True
    ActivationReason=SimpleNamespace(DoubleClick=2)
    def __init__(self,parent):self.parent=parent;self.activated=Signal();self.shown=False
    @staticmethod
    def isSystemTrayAvailable():return FakeTray.enabled
    def setIcon(self,icon):pass
    def setToolTip(self,text):pass
    def setContextMenu(self,menu):self.menu=menu
    def show(self):self.shown=True
    def hide(self):self.shown=False


class FakeClock:
    def __init__(self):self.visible=True
    def hide(self):self.visible=False
    def show(self):self.visible=True
    def collapse(self):pass


class FakePreferenceCheckbox:
    def blockSignals(self,val):pass
    def setChecked(self,val):self.checked=val


# Exercise the exact production methods by compiling only their AST bodies, without Qt imports.
base_ast=ast.parse((ROOT/'orbitclip.py').read_text(encoding='utf-8'))
app_ast=next(x for x in base_ast.body if isinstance(x,ast.ClassDef) and x.name=='OrbitApp')
needed=('create_windows_tray','tray_activated','refresh_tray_menu','set_clock_hidden_windows')
methods=[n for n in app_ast.body if isinstance(n,ast.FunctionDef) and n.name in needed]
assert len(methods)==len(needed)
code=compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='TrayLogic',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])),str(ROOT/'orbitclip.py'),'exec')
scope={'platform':platform,'QSystemTrayIcon':FakeTray,'QMenu':FakeMenu,'QIcon':lambda p:p,'ASSETS':ROOT/'assets',
       'QMessageBox':SimpleNamespace(warning=Mock())}
exec(code,scope)
TrayLogic=scope['TrayLogic']


class TrayTests(unittest.TestCase):
    def setUp(self):
        FakeTray.enabled=True
        self.client=TrayLogic()
        self.client.qt=object()
        self.client.hide_clock_windows=False
        self.client.tray_icon=None;self.client.tray_menu=None;self.client.tray_clock_action=None
        self.client.clock=FakeClock();self.client.preferences=None
        self.client.save_settings=Mock();self.client.open_history=Mock();self.client.open_chat=Mock()
        self.client.open_online=Mock();self.client.open_settings=Mock();self.client.open_tour=Mock();self.client.shutdown=Mock()

    @patch.object(platform,'system',return_value='Windows')
    def test_tray_hides_clock_but_stays_running(self,platform_mock):
        c=self.client;c.create_windows_tray()
        self.assertTrue(c.tray_icon.shown)
        self.assertGreaterEqual(len(c.tray_menu.actions),7)
        self.assertIn('Переписка',[x.text for x in c.tray_menu.actions])
        self.assertIn('Настройки…',[x.text for x in c.tray_menu.actions])
        c.set_clock_hidden_windows(True)
        self.assertFalse(c.clock.visible)
        self.assertTrue(c.tray_icon.shown)
        self.assertEqual(c.tray_clock_action.text,'Показать виджет часов')
        c.tray_menu.actions[0].callback(False)
        c.open_history.assert_called_once()
        c.tray_clock_action.callback(False)
        self.assertTrue(c.clock.visible)
        self.assertEqual(c.tray_clock_action.text,'Скрыть виджет часов')
        self.assertEqual(c.save_settings.call_count,2)

    @patch.object(platform,'system',return_value='Windows')
    def test_no_tray_prevents_clock_hiding(self,platform_mock):
        c=self.client;FakeTray.enabled=False;c.create_windows_tray()
        self.assertIsNone(c.tray_icon)
        c.set_clock_hidden_windows(True)
        self.assertTrue(c.clock.visible)
        self.assertFalse(c.hide_clock_windows)

    @patch.object(platform,'system',return_value='Windows')
    def test_double_click_opens_history(self,platform_mock):
        c=self.client;c.create_windows_tray()
        c.tray_activated(FakeTray.ActivationReason.DoubleClick)
        c.open_history.assert_called_once()

    @patch.object(platform,'system',return_value='Darwin')
    def test_macos_does_not_create_windows_tray(self,platform_mock):
        c=self.client;c.create_windows_tray()
        self.assertIsNone(c.tray_icon)
        c.set_clock_hidden_windows(True)
        self.assertFalse(c.hide_clock_windows)

if __name__=='__main__':unittest.main()
