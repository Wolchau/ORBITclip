"""Regression tests for ORBITclip 7.0.3 global Ctrl+wheel queue.
Can run without PySide6 or macOS/Windows-specific native dependencies.
"""
import queue
import unittest
from pathlib import Path
from orbit_switcher import ClipboardWheel


class FakeKeys:
    ctrl='Key.ctrl'
    ctrl_l='Key.ctrl_l'
    ctrl_r='Key.ctrl_r'
    alt='Key.alt'
    alt_l='Key.alt_l'
    alt_r='Key.alt_r'
    alt_gr='Key.alt_gr'
    esc='Key.esc'


class FakeKeyboard:
    Key=FakeKeys


class WheelTests(unittest.TestCase):
    def setUp(self):
        self.wheel=ClipboardWheel()
        self.wheel.keyboard=FakeKeyboard
        self.wheel._mac_flags=None

    def drain(self):
        out=[]
        while True:
            try:out.append(self.wheel.events.get_nowait())
            except queue.Empty:return out

    def test_ctrl_scroll_commits_on_release(self):
        self.wheel.on_press(FakeKeys.ctrl_l)
        self.wheel.on_scroll(100,100,0,-1)
        self.wheel.on_scroll(100,100,0,-1)
        self.assertEqual(self.drain(),[('move',1),('move',1)])
        self.wheel.on_release(FakeKeys.ctrl_l)
        self.assertEqual(self.drain(),[('commit',0)])

    def test_alt_cycles_only_during_selection(self):
        self.wheel.on_press(FakeKeys.ctrl)
        self.wheel.on_press(FakeKeys.alt)
        self.assertEqual(self.drain(),[])
        self.wheel.on_release(FakeKeys.alt)
        self.wheel.on_scroll(0,0,0,1)
        self.wheel.on_press(FakeKeys.alt)
        self.assertEqual(self.drain(),[('move',-1),('category',1)])
        self.wheel.on_press(FakeKeys.alt)
        self.assertEqual(self.drain(),[]) # key auto-repeat does not re-cycle
        self.wheel.on_release(FakeKeys.alt)
        self.wheel.on_press(FakeKeys.alt)
        self.assertEqual(self.drain(),[('category',1)])
        self.wheel.on_release(FakeKeys.ctrl)
        self.assertEqual(self.drain(),[('commit',0)])

    def test_esc_cancels(self):
        self.wheel.on_press(FakeKeys.ctrl)
        self.wheel.on_scroll(0,0,0,1)
        self.wheel.on_press(FakeKeys.esc)
        self.assertEqual(self.drain(),[('move',-1),('cancel',0)])
        self.wheel.on_release(FakeKeys.ctrl)
        self.assertEqual(self.drain(),[])

    def test_alt_alone_does_not_trigger_selector(self):
        self.wheel.on_press(FakeKeys.alt)
        self.wheel.on_scroll(0,0,0,-2)
        self.assertEqual(self.drain(),[])

    def test_client_retains_bubble_when_inactive(self):
        source=(Path(__file__).parent/'orbitclip.py').read_text(encoding='utf-8')
        self.assertIn('if not self.switch_active:self.bubble.hide()',source)
        self.assertIn('self.setAttribute(Qt.WA_ShowWithoutActivating,True)',source)


    def test_diagnostic_counts_and_simulated_first_step(self):
        diag=self.wheel.diagnostics()
        self.assertEqual(diag['moves'],0)
        self.wheel.simulate_one_step()
        self.assertEqual(self.drain(),[('move',1)])
        self.assertEqual(self.wheel.diagnostics()['moves'],1)

    def test_wheel_without_ctrl_not_selected(self):
        self.wheel.on_scroll(0,0,0,1)
        self.assertEqual(self.drain(),[])
        self.assertEqual(self.wheel.diagnostics()['raw_wheel'],1)
        self.assertEqual(self.wheel.diagnostics()['ctrl_wheel'],0)

    def test_backend_windows_runloop_uses_typed_MSG(self):
        from pathlib import Path
        src=(Path(__file__).parent/'orbit_switcher.py').read_text('utf-8')
        self.assertIn('msg = wintypes.MSG()',src)
        self.assertIn('self._windows_safe_thread',src)
        self.assertIn('cf.CFRunLoopRunInMode.argtypes',src)

    def test_native_mac_tap_has_scroll_and_flags_events(self):
        source=(Path(__file__).parent/'orbit_switcher.py').read_text(encoding='utf-8')
        self.assertIn('(1 << 22) | (1 << 12) | (1 << 10)',source)
        self.assertIn('self._mac_ctrl and not ctrl',source)
        self.assertIn("self.events.put(('category', 1))",source)
        self.assertIn('return None',source)


if __name__=='__main__':unittest.main()
