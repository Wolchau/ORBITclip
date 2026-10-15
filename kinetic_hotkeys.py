"""Global favorite hotkeys.

Windows: RegisterHotKey / WM_HOTKEY, so digit chords work even when another
application owns focus. macOS / Linux X11: pynput GlobalHotKeys fallback.
Queues are polled on the Tk UI thread. Paste is delayed until the modifier keys
have been released to avoid sending Ctrl+Alt+V by accident.
"""
import ctypes
import platform
import queue
import threading

class Hotkeys:
    def __init__(self):
        self.events=queue.Queue()
        self.error=''
        self.enabled=False
        self.platform=platform.system()
        self.listener=None
        self._thread=None
        self._thread_id=None
        self._stop=threading.Event()
        self._ready=threading.Event()
        self.bindings={}
        self.backend=''
        self.registered_count=0
        self.kb=None
        try:
            from pynput import keyboard
            self.kb=keyboard
        except Exception as exc:
            self.error='Не удалось загрузить управление вставкой: '+str(exc)

    def configure(self,items):
        self.stop()
        self.error=''
        self.bindings={i['hotkey']:i['id'] for i in items if i.get('pinned') and i.get('hotkey')}
        if not self.bindings:
            self.enabled=True
            return
        if self.platform=='Windows':
            self._stop.clear()
            self._ready.clear()
            self._thread=threading.Thread(target=self._run_win,daemon=True,name='orbit-favorite-hotkeys')
            self._thread.start()
            self._ready.wait(2.0)
            self.enabled = self.registered_count>0
            self.backend='Windows RegisterHotKey'
            return
        if self.kb is None:
            self.enabled=False
            return
        try:
            mapping={}
            for chord,item_id in self.bindings.items():
                hotkey=chord.replace('ctrl+','<ctrl>+').replace('cmd+','<cmd>+').replace('alt+','<alt>+')
                mapping[hotkey]=lambda ident=item_id:self.events.put(ident)
            self.listener=self.kb.GlobalHotKeys(mapping)
            self.listener.daemon=True
            self.listener.start()
            self.enabled=True
            self.backend='pynput'
        except Exception as exc:
            self.error='Не удалось назначить сочетания: '+str(exc)
            self.enabled=False

    def _run_win(self):
        from ctypes import wintypes
        user=ctypes.windll.user32
        kernel=ctypes.windll.kernel32
        MOD_ALT=0x0001; MOD_CONTROL=0x0002; MOD_NOREPEAT=0x4000
        WM_HOTKEY=0x0312; WM_QUIT=0x0012
        user.RegisterHotKey.argtypes=(wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT)
        user.RegisterHotKey.restype=wintypes.BOOL
        user.UnregisterHotKey.argtypes=(wintypes.HWND,ctypes.c_int)
        user.UnregisterHotKey.restype=wintypes.BOOL
        kernel.GetCurrentThreadId.restype=wintypes.DWORD
        user.PeekMessageW.argtypes=(ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT,wintypes.UINT)
        user.GetMessageW.argtypes=(ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT)
        user.GetMessageW.restype=ctypes.c_int
        user.PostThreadMessageW.argtypes=(wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM)
        self._thread_id=kernel.GetCurrentThreadId()
        msg=wintypes.MSG()
        user.PeekMessageW(ctypes.byref(msg),None,0,0,0) # create message queue
        registered={}
        try:
            for key,(chord,item_id) in enumerate(self.bindings.items(),start=1):
                parts=chord.split('+')
                if not (parts[0]=='ctrl' and parts[1]=='alt'):
                    self.error+='Не поддерживается в Windows: '+chord+'; '
                    continue
                virtual_key=ord(parts[2].upper())
                ok=user.RegisterHotKey(None,key,MOD_CONTROL|MOD_ALT|MOD_NOREPEAT,virtual_key)
                if ok:registered[key]=item_id
                else:self.error+='Занято системой или другим приложением: '+chord+'; '
            self.registered_count=len(registered)
            self._ready.set()
            if not registered:return
            while not self._stop.is_set():
                result=user.GetMessageW(ctypes.byref(msg),None,0,0)
                if result <= 0:break
                if msg.message==WM_HOTKEY and int(msg.wParam) in registered:
                    self.events.put(registered[int(msg.wParam)])
        finally:
            self._ready.set()
            for key in registered:user.UnregisterHotKey(None,key)
            self._thread_id=None

    def stop(self):
        self._stop.set()
        if self._thread_id and self.platform=='Windows':
            try:ctypes.windll.user32.PostThreadMessageW(self._thread_id,0x0012,0,0)
            except Exception:pass
        if self.listener:
            try:self.listener.stop()
            except Exception:pass
        self.listener=None
        if self._thread and self._thread.is_alive():self._thread.join(timeout=1.5)
        self._thread=None
        self.enabled=False

    def modifiers_held(self):
        if self.platform=='Windows':
            u=ctypes.windll.user32
            return any(u.GetAsyncKeyState(k)&0x8000 for k in (0x11,0x12,0xA2,0xA3,0xA4,0xA5))
        if self.platform=='Darwin':
            try:
                cg=ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
                cg.CGEventSourceFlagsState.restype=ctypes.c_uint64
                cg.CGEventSourceFlagsState.argtypes=(ctypes.c_uint32,)
                flags=cg.CGEventSourceFlagsState(0)
                return bool(flags & ((1<<18)|(1<<19)|(1<<20)))
            except Exception:return False
        return False

    def paste(self):
        if self.kb is None:
            self.error='Для автоматической вставки требуется pynput'
            return
        modifier=self.kb.Key.cmd if self.platform=='Darwin' else self.kb.Key.ctrl
        try:
            ctl=self.kb.Controller()
            with ctl.pressed(modifier):
                ctl.press('v'); ctl.release('v')
        except Exception as exc:
            self.error='Ошибка вставки: '+str(exc)
