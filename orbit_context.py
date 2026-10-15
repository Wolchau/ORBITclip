"""Best-effort foreground application name at copy time; never records window titles."""
import ctypes
import os
import platform
import subprocess


def foreground_app():
    name=platform.system()
    if name=='Windows':
        try:
            user32=ctypes.windll.user32
            pid=ctypes.c_ulong()
            hwnd=user32.GetForegroundWindow()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            rights=0x1000
            kernel32=ctypes.windll.kernel32
            kernel32.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
            kernel32.OpenProcess.restype=ctypes.c_void_p
            proc=kernel32.OpenProcess(rights,False,pid.value)
            if not proc:return 'Неизвестно'
            try:
                buf=ctypes.create_unicode_buffer(4096)
                size=ctypes.c_ulong(len(buf))
                if kernel32.QueryFullProcessImageNameW(ctypes.c_void_p(proc),0,buf,ctypes.byref(size)):
                    return os.path.splitext(os.path.basename(buf.value))[0][:60] or 'Неизвестно'
            finally:kernel32.CloseHandle(ctypes.c_void_p(proc))
        except (OSError,AttributeError,ValueError):pass
    if name=='Darwin':
        try:
            result=subprocess.run(['osascript','-e',
                'tell application "System Events" to get name of first application process whose frontmost is true'],
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=1.0)
            if result.returncode==0:return result.stdout.strip()[:60] or 'Неизвестно'
        except (OSError,subprocess.TimeoutExpired):pass
    return 'Неизвестно'
