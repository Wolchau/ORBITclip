"""System-wide Ctrl+wheel selector for ORBITclip.

Windows: low-level Win32 hooks. macOS: CoreGraphics event tap with pynput fallback.
Linux X11: pynput. Only plain queue messages cross event threads; Qt owns the UI.
"""
import ctypes
import platform
import queue
import threading
import time


class ClipboardWheel:
    def __init__(self):
        self.events = queue.Queue()
        self.enabled = False
        self.error = ''
        self.backend = ''
        self._lock = threading.RLock()
        self._pressed = set()
        self._selected = False
        self._wheel_accum = 0.0
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._thread = None
        self._native_thread = None
        self._native_error = ''
        self.keyboard_listener = None
        self.mouse_listener = None
        self._mac_flags = None
        self._mac_ctrl = False
        self._mac_alt = False
        self._mac_tap = None
        self._mac_callback = None
        self._mac_status = ""
        self.keyboard = None
        self.mouse = None
        self.activation_mode = 'wheel'
        self._win_ctrl = False
        self._win_ctrl_keys = set()
        self._win_alt_keys = set()
        self._win_hook_mouse = None
        self._win_hook_keyboard = None
        self.move_count = 0
        self.last_move = 0.0
        self._last_step = 0.0
        self._mac_event_count = 0
        self._trackpad_accum = 0.0
        self._mac_tap_location = ''
        self._mac_tap_enabled = False
        self.raw_wheel_count = 0
        self.raw_ctrl_wheel_count = 0
        self.received_last_at = 0.0
        self._native_error = ''

    def set_activation_mode(self, mode):
        self.activation_mode = 'ctrl_alt' if mode == 'ctrl_alt' else 'wheel'

    def start(self):
        self.stop()
        self._stop_event.clear()
        if platform.system() == 'Windows':
            self._ready.clear()
            self._thread = threading.Thread(target=self._windows_safe_thread,
                                            name='orbit-ctrl-wheel', daemon=True)
            self._thread.start()
            self._ready.wait(2.0)
            if self.enabled:
                return True
            native_error = self.error
            # pynput fallback for systems that disallow low-level Windows hooks.
            if self._start_pynput():
                self.backend = 'pynput (резервный режим Windows)'
                return True
            self.error = (native_error + '; ' + self.error).strip('; ')
            return False
        if platform.system() == 'Darwin':
            self._ready.clear()
            self._thread = threading.Thread(target=self._mac_event_tap_thread,
                                            name='orbit-macos-wheel', daemon=True)
            self._thread.start()
            self._ready.wait(3.0)
            if self.enabled:
                return True
            native_error = self.error
            if self._start_pynput():
                self.backend = 'pynput (резервный режим macOS)'
                self.error = (native_error + '; используется резервный режим').strip('; ')
                return True
            self.error = (native_error + '; ' + self.error).strip('; ')
            return False
        return self._start_pynput()

    def _mac_event_tap_thread(self):
        """Global macOS scroll + modifier state using one native event tap.

        Must be created on its own thread with an active CFRunLoop. CoreGraphics
        delivers wheel events even when some other app owns keyboard focus.
        """
        if platform.system() != 'Darwin':
            self.error = 'CoreGraphics доступен только на macOS'
            self._ready.set()
            return
        tap = source = None
        try:
            cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
            cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
            PTR = ctypes.c_void_p
            CALLBACK = ctypes.CFUNCTYPE(PTR, PTR, ctypes.c_uint32, PTR, PTR)
            cg.CGEventTapCreate.argtypes = (ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                            ctypes.c_uint64, CALLBACK, PTR)
            cg.CGEventTapCreate.restype = PTR
            cg.CGEventTapEnable.argtypes = (PTR, ctypes.c_bool)
            cg.CGEventTapIsEnabled.argtypes = (PTR,)
            cg.CGEventTapIsEnabled.restype = ctypes.c_bool
            cg.CGEventGetFlags.argtypes = (PTR,)
            cg.CGEventGetFlags.restype = ctypes.c_uint64
            cg.CGEventGetIntegerValueField.argtypes = (PTR, ctypes.c_uint32)
            cg.CGEventGetIntegerValueField.restype = ctypes.c_int64
            cg.CGEventGetDoubleValueField.argtypes = (PTR, ctypes.c_uint32)
            cg.CGEventGetDoubleValueField.restype = ctypes.c_double
            cf.CFMachPortCreateRunLoopSource.argtypes = (PTR, PTR, ctypes.c_long)
            cf.CFMachPortCreateRunLoopSource.restype = PTR
            cf.CFRunLoopGetCurrent.restype = PTR
            cf.CFRunLoopAddSource.argtypes = (PTR, PTR, PTR)
            cf.CFRunLoopRunInMode.argtypes = (PTR, ctypes.c_double, ctypes.c_bool)
            cf.CFRunLoopRunInMode.restype = ctypes.c_int
            cf.CFMachPortInvalidate.argtypes = (PTR,)
            cf.CFRelease.argtypes = (PTR,)

            # 22 scroll wheel, 12 modifier changes, 10 key down (Escape).
            mask = (1 << 22) | (1 << 12) | (1 << 10)
            ctrl_flag = 1 << 18
            alt_flag = 1 << 19

            def proc(proxy, event_type, event, userdata):
                try:
                    if event_type in (0xFFFFFFFE, 0xFFFFFFFF):
                        if self._mac_tap is not None:
                            cg.CGEventTapEnable(self._mac_tap, True)
                        return event
                    flags = int(cg.CGEventGetFlags(event))
                    ctrl = bool(flags & ctrl_flag)
                    alt = bool(flags & alt_flag)
                    with self._lock:
                        if event_type == 12:  # flagsChanged
                            if self._mac_ctrl and not ctrl:
                                self._commit_locked()
                            elif ctrl and alt and not self._mac_alt:
                                if self.activation_mode == 'ctrl_alt' and not self._selected:
                                    self._move_locked(1)
                                elif self._selected:
                                    self.events.put(('category', 1))
                            self._mac_ctrl = ctrl
                            self._mac_alt = alt
                        elif event_type == 10 and self._selected:
                            # kCGKeyboardEventKeycode=9; Escape virtual key code=53.
                            if cg.CGEventGetIntegerValueField(event, 9) == 53:
                                self._cancel_locked()
                        elif event_type == 22:
                            self.raw_wheel_count += 1
                            if ctrl and (self.activation_mode == 'wheel' or self._selected):
                                self._mac_ctrl = True
                                self._mac_alt = alt
                                self._mac_event_count += 1
                                self.raw_ctrl_wheel_count += 1
                                # kCGScrollWheelEventIsContinuous=88;
                                # kCGScrollWheelEventPointDeltaAxis1=96;
                                # kCGScrollWheelEventDeltaAxis1=11.
                                continuous = bool(cg.CGEventGetIntegerValueField(event, 88))
                                point_delta = cg.CGEventGetIntegerValueField(event, 96)
                                wheel_delta = cg.CGEventGetIntegerValueField(event, 11)
                                if continuous:
                                    # Small trackpad movements count too. A native
                                    # trackpad event can carry just 1–2 points,
                                    # never a full mouse wheel notch.
                                    movement = float(point_delta or wheel_delta)
                                    if not movement:
                                        movement = cg.CGEventGetDoubleValueField(event,93)
                                    self._mac_trackpad_locked(movement)
                                else:
                                    self._move_locked(max(-1,min(1,wheel_delta)))
                                # Do not zoom the app underneath when Ctrl is used.
                                return None
                except Exception as exc:
                    self._native_error = str(exc)
                return event

            self._mac_callback = CALLBACK(proc)  # keep callable alive through runloop
            # Session tap delivers global input for the logged-in graphical
            # session. If unavailable, retry HID tap, which needs elevated
            # Accessibility permission on some macOS releases.
            for where, name in ((1,'session'),(0,'HID')):
                tap = cg.CGEventTapCreate(where, 0, 0, mask, self._mac_callback, None)
                if tap:
                    self._mac_tap_location = name
                    break
            if not tap:
                info = []
                try:
                    core = ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
                    core.AXIsProcessTrusted.restype = ctypes.c_bool
                    if not core.AXIsProcessTrusted():
                        info.append('Универсальный доступ (Accessibility)')
                except (OSError, AttributeError):
                    pass
                try:
                    cg.CGPreflightListenEventAccess.restype = ctypes.c_bool
                    if not cg.CGPreflightListenEventAccess():
                        info.append('Мониторинг ввода (Input Monitoring)')
                except (AttributeError, OSError):
                    pass
                self.error = ('macOS отклонила глобальный перехват. Разреши Python/Terminal: '
                              + (', '.join(info) if info else 'Accessibility и Input Monitoring')
                              + '. Перезапусти приложение.')
                self._ready.set()
                return
            self._mac_tap = tap
            source = cf.CFMachPortCreateRunLoopSource(None, tap, 0)
            if not source:
                self.error = 'Невозможно создать источник CoreGraphics RunLoop'
                self._ready.set()
                return
            loop = cf.CFRunLoopGetCurrent()
            default_mode = PTR.in_dll(cf, 'kCFRunLoopDefaultMode').value
            cf.CFRunLoopAddSource(loop, source, default_mode)
            cg.CGEventTapEnable(tap, True)
            if not cg.CGEventTapIsEnabled(tap):
                self.error = 'macOS создала, но не включила глобальный перехват; проверь Accessibility/Input Monitoring'
                self._ready.set()
                return
            self.enabled = True
            self._mac_tap_enabled = True
            self.backend = 'macOS CoreGraphics · '+self._mac_tap_location+' (глобальный)'
            self.error = ''
            self._ready.set()
            while not self._stop_event.is_set():
                cf.CFRunLoopRunInMode(default_mode, 0.12, False)
                if tap and not cg.CGEventTapIsEnabled(tap):
                    # macOS disables taps on long callback/timeout. Reenable
                    # rather than silently leaving the Qt-local handler alone.
                    cg.CGEventTapEnable(tap, True)
                self._mac_tap_enabled = bool(tap and cg.CGEventTapIsEnabled(tap))
        except Exception as exc:
            self.error = 'macOS CoreGraphics: ' + str(exc)
            self._ready.set()
        finally:
            if tap:
                try: cf.CFMachPortInvalidate(tap)
                except Exception: pass
            if source:
                try: cf.CFRelease(source)
                except Exception: pass
            if tap:
                try: cf.CFRelease(tap)
                except Exception: pass
            self._mac_tap = None
            self._mac_callback = None
            self._mac_tap_enabled = False

    def _mac_trackpad_locked(self,points):
        """Turn short macOS trackpad swipes into predictable single-item steps.

        Point deltas are much smaller than mouse wheel notches. One first
        touch scrolls immediately; subsequent steps are at most ~20/second.
        """
        if not points:
            return
        now=time.monotonic()
        self._trackpad_accum += float(points)
        if not self._selected:
            self._trackpad_accum=0.0
            self._move_locked(0.5 if points>0 else -0.5)
            return
        if now-self._last_step < 0.050:
            return
        if abs(self._trackpad_accum)>=1.5:
            amount=1.0 if self._trackpad_accum>0 else -1.0
            self._trackpad_accum=0.0
            self._move_locked(amount)

    def _start_pynput(self):
        try:
            from pynput import keyboard, mouse
            self.keyboard, self.mouse = keyboard, mouse
            self.keyboard_listener = keyboard.Listener(on_press=self.on_press,
                                                      on_release=self.on_release)
            self.mouse_listener = mouse.Listener(on_scroll=self.on_scroll, on_click=self.on_click)
            self.keyboard_listener.daemon = True
            self.mouse_listener.daemon = True
            self.keyboard_listener.start()
            self.mouse_listener.start()
            self.enabled = True
            self.backend = 'pynput'
            self.error = ''
            if platform.system() == 'Darwin':
                try:
                    cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
                    cg.CGEventSourceFlagsState.restype = ctypes.c_uint64
                    cg.CGEventSourceFlagsState.argtypes = [ctypes.c_uint32]
                    self._mac_flags = cg.CGEventSourceFlagsState
                    self.backend = 'pynput + CoreGraphics'
                except (OSError, AttributeError):
                    pass
            return True
        except Exception as exc:
            self.enabled = False
            self.error = 'Глобальный перехват недоступен: ' + str(exc)
            for listener in (self.keyboard_listener, self.mouse_listener):
                if listener:
                    try: listener.stop()
                    except Exception: pass
            self.keyboard_listener = self.mouse_listener = None
            return False

    def _control_key(self, key):
        return self.keyboard and key in (
            self.keyboard.Key.ctrl, self.keyboard.Key.ctrl_l, self.keyboard.Key.ctrl_r)

    def on_press(self, key):
        with self._lock:
            if self._control_key(key):
                self._pressed.add(str(key))
            elif self.keyboard and key in (self.keyboard.Key.alt, self.keyboard.Key.alt_l, self.keyboard.Key.alt_r, getattr(self.keyboard.Key,'alt_gr',None)):
                marker=str(key)
                if marker not in self._pressed and self._ctrl_held():
                    if self.activation_mode == 'ctrl_alt' and not self._selected:
                        self._move_locked(1)
                    elif self._selected:
                        self.events.put(('category', 1))
                self._pressed.add(marker)
            elif self.keyboard and key == self.keyboard.Key.esc and self._selected:
                self._cancel_locked()

    def on_release(self, key):
        with self._lock:
            if self._control_key(key):
                self._pressed.discard(str(key))
                if not any('ctrl' in marker for marker in self._pressed):
                    self._commit_locked()
            elif self.keyboard and key in (self.keyboard.Key.alt, self.keyboard.Key.alt_l, self.keyboard.Key.alt_r, getattr(self.keyboard.Key,'alt_gr',None)):
                self._pressed.discard(str(key))

    def _ctrl_held(self):
        # On macOS, this reads real modifier state and avoids missed key-press
        # events when the pointer is over another application.
        if self._mac_flags:
            try:
                if self._mac_flags(0) & (1 << 18):
                    return True
                return any('ctrl' in marker for marker in self._pressed)
            except Exception:
                pass
        if platform.system() == 'Windows':
            try:
                return bool(ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000)
            except Exception:
                pass
        return any('ctrl' in marker for marker in self._pressed)

    def local_scroll(self, steps):
        """Safe fallback for Qt wheel events inside the ORBITclip windows."""
        with self._lock:
            self._move_locked(steps)


    def diagnostics(self):
        return {
            'backend':self.backend or 'none', 'enabled':bool(self.enabled),
            'error':self.error, 'native_error':self._native_error,
            'raw_wheel':self.raw_wheel_count,
            'ctrl_wheel':self.raw_ctrl_wheel_count,
            'moves':self.move_count,
            'mac_global_tap':self._mac_tap_location or 'не создан',
            'mac_tap_enabled':self._mac_tap_enabled,
            'mac_events':self._mac_event_count,
            'seconds_since_move':round(time.monotonic()-self.last_move,1) if self.last_move else None,
        }

    def simulate_one_step(self):
        """Test event dispatch and bubble independently of OS-level hooks."""
        with self._lock:
            self._move_locked(-1)

    def on_click(self, x, y, button, pressed):
        if pressed:
            self.events.put(('pointer_down',(int(x),int(y))))

    def on_scroll(self, x, y, dx, dy):
        # pynput fallback shared by all desktop platforms.
        with self._lock:
            self.raw_wheel_count += 1
            if not dy or not self._ctrl_held() or (self.activation_mode == 'ctrl_alt' and not self._selected):
                return
            self.raw_ctrl_wheel_count += 1
            self._move_locked(dy)

    def _move_locked(self, steps):
        if not steps:
            return
        # Trackpads often provide fractional wheel deltas; first gesture should
        # always give immediate visual feedback. Rate-limit tiny deltas so one
        # physical gesture does not jump through dozens of records.
        now=time.monotonic()
        if abs(steps)<0.9 and not self._selected:
            steps=1 if steps>0 else -1
        elif abs(steps)<0.9 and now-self._last_step<0.050:
            return
        self._last_step=now
        self._wheel_accum += steps
        count = 0
        while self._wheel_accum >= 0.9:
            count += 1
            self._wheel_accum -= 1.0
        while self._wheel_accum <= -0.9:
            count -= 1
            self._wheel_accum += 1.0
        if count:
            self.move_count += abs(count)
            self.last_move = now
            self.received_last_at = now
            self._selected = True
            # Wheel down = older entry; up = newer entry.
            self.events.put(('move', -count))

    def _cancel_locked(self):
        self._selected = False
        self._wheel_accum = 0.0
        self._trackpad_accum=0.0
        self.events.put(('cancel', 0))

    def _commit_locked(self):
        self._wheel_accum = 0.0
        self._trackpad_accum=0.0
        if self._selected:
            self._selected = False
            self.events.put(('commit', 0))

    def _windows_safe_thread(self):
        try:
            self._windows_hook_thread()
        except Exception as exc:
            self.error = f'Windows hook: {type(exc).__name__}: {exc}'
            self._native_error = self.error
            self.enabled = False
            self._ready.set()

    def _windows_hook_thread(self):
        from ctypes import wintypes
        user = ctypes.windll.user32
        kernel = ctypes.windll.kernel32
        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
        LRESULT = ctypes.c_ssize_t
        CALLBACK = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [('pt', wintypes.POINT), ('mouseData', wintypes.DWORD),
                        ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                        ('dwExtraInfo', ULONG_PTR)]

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [('vkCode', wintypes.DWORD), ('scanCode', wintypes.DWORD),
                        ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                        ('dwExtraInfo', ULONG_PTR)]

        user.SetWindowsHookExW.argtypes = [ctypes.c_int, CALLBACK, wintypes.HINSTANCE, wintypes.DWORD]
        user.SetWindowsHookExW.restype = wintypes.HHOOK
        user.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user.CallNextHookEx.restype = LRESULT
        user.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user.UnhookWindowsHookEx.restype = wintypes.BOOL
        kernel.GetCurrentThreadId.restype = wintypes.DWORD
        kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel.GetModuleHandleW.restype = wintypes.HMODULE
        user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user.GetAsyncKeyState.restype = ctypes.c_short
        user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT]
        user.GetMessageW.restype = ctypes.c_int
        user.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user.PostThreadMessageW.argtypes = [wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        self._native_thread = kernel.GetCurrentThreadId()

        def mouse_proc(code, msg, data):
            if code >= 0 and msg in (0x0201, 0x0204, 0x0207):
                try:
                    m = ctypes.cast(data, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    self.events.put(('pointer_down',(m.pt.x,m.pt.y)))
                except Exception:
                    pass
            if code >= 0 and msg == 0x020A:  # WM_MOUSEWHEEL
                try:
                    self.raw_wheel_count += 1
                    ctrl = bool(user.GetAsyncKeyState(0x11) & 0x8000)
                    if not ctrl:
                        with self._lock:
                            self._win_ctrl_keys.clear()
                            self._win_ctrl = False
                            self._commit_locked()
                    if ctrl and (self.activation_mode == 'wheel' or self._selected):
                        self.raw_ctrl_wheel_count += 1
                        m = ctypes.cast(data, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        delta = ctypes.c_short((m.mouseData >> 16) & 0xFFFF).value
                        steps = int(delta / 120) if delta else 0
                        if steps == 0 and delta:
                            steps = 1 if delta > 0 else -1
                        with self._lock:
                            self._move_locked(steps)
                        return 1  # do not zoom underlying app on Ctrl+scroll
                except Exception as exc:
                    self._native_error = 'Windows mouse callback: '+repr(exc)
            return user.CallNextHookEx(None, code, msg, data)

        def keyboard_proc(code, msg, data):
            if code >= 0 and msg in (0x0100, 0x0101, 0x0104, 0x0105):
                try:
                    key = ctypes.cast(data, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.vkCode
                    down = msg in (0x0100, 0x0104)
                    with self._lock:
                        if key in (0x11, 0xA2, 0xA3):
                            if down:
                                self._win_ctrl_keys.add(key)
                                self._win_ctrl = True
                            else:
                                self._win_ctrl_keys.discard(key)
                                self._win_ctrl = bool(self._win_ctrl_keys)
                                if not self._win_ctrl:
                                    self._commit_locked()
                        elif key in (0x12,0xA4,0xA5):
                            if down and key not in self._win_alt_keys:
                                self._win_alt_keys.add(key)
                                if bool(user.GetAsyncKeyState(0x11) & 0x8000):
                                    if self.activation_mode == 'ctrl_alt' and not self._selected:
                                        self._move_locked(1)
                                    elif self._selected:
                                        self.events.put(('category',1))
                            elif not down:
                                self._win_alt_keys.discard(key)
                        elif key == 0x1B and down and self._selected:
                            self._cancel_locked()
                except Exception as exc:
                    self._native_error = 'Windows keyboard callback: '+repr(exc)
            return user.CallNextHookEx(None, code, msg, data)

        self._win_mouse_proc = CALLBACK(mouse_proc)
        self._win_keyboard_proc = CALLBACK(keyboard_proc)
        mh = user.SetWindowsHookExW(14, self._win_mouse_proc, kernel.GetModuleHandleW(None), 0)
        kh = user.SetWindowsHookExW(13, self._win_keyboard_proc, kernel.GetModuleHandleW(None), 0)
        self._win_hook_mouse = mh
        self._win_hook_keyboard = kh
        self.enabled = bool(mh and kh)
        self.backend = 'Windows native hook' if self.enabled else ''
        if not self.enabled:
            self.error = 'Windows не разрешил установить системный перехват мыши/клавиатуры'
        self._ready.set()
        try:
            if self.enabled:
                # GetMessageW message buffer: larger than MSG on x86/x64.
                msg = wintypes.MSG()
                while not self._stop_event.is_set():
                    result = user.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if result <= 0:
                        break
                    user.TranslateMessage(ctypes.byref(msg))
                    user.DispatchMessageW(ctypes.byref(msg))
        finally:
            if mh:
                user.UnhookWindowsHookEx(mh)
            if kh:
                user.UnhookWindowsHookEx(kh)
            self._win_hook_mouse = self._win_hook_keyboard = None

    def stop(self):
        self._stop_event.set()
        if self._native_thread and platform.system() == 'Windows':
            try: ctypes.windll.user32.PostThreadMessageW(self._native_thread, 0x0012, 0, 0)
            except Exception: pass
        for listener in (self.mouse_listener, self.keyboard_listener):
            if listener:
                try: listener.stop()
                except Exception: pass
        self.mouse_listener = self.keyboard_listener = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.9)
        self._thread = None
        self._native_thread = None
        self._mac_tap = None
        self._mac_callback = None
        self._mac_ctrl = False
        self._mac_alt = False
        with self._lock:
            self._pressed.clear()
            self._selected = False
            self._win_ctrl = False
            self._win_ctrl_keys.clear()
            self._win_alt_keys.clear()
        self.enabled = False
