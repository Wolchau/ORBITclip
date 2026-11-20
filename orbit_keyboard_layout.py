"""Best-effort system keyboard input source label; never reads keystrokes."""
import ctypes
import platform


def current_layout():
    system = platform.system()
    try:
        if system == 'Windows':
            user32 = ctypes.windll.user32
            thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
            language = user32.GetKeyboardLayout(thread) & 0xffff
            return {0x0409: 'EN', 0x0419: 'RU', 0x0422: 'UK', 0x0407: 'DE',
                    0x040c: 'FR', 0x0c0a: 'ES'}.get(language, f'{language:04X}')
        if system == 'Darwin':
            carbon = ctypes.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
            core = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
            carbon.TISCopyCurrentKeyboardInputSource.restype = ctypes.c_void_p
            carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
            core.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
            core.CFStringGetCString.restype = ctypes.c_bool
            core.CFRelease.argtypes = [ctypes.c_void_p]
            key = ctypes.c_void_p.in_dll(carbon, 'kTISPropertyInputSourceID')
            source = carbon.TISCopyCurrentKeyboardInputSource()
            if not source:
                return ''
            try:
                value = carbon.TISGetInputSourceProperty(source, key)
                buf = ctypes.create_string_buffer(256)
                if value and core.CFStringGetCString(value, buf, len(buf), 0x08000100):
                    ident = buf.value.decode('utf-8', 'replace').lower()
                    for name, marker in [('RU','russian'),('EN','us'),('EN','british'),
                                         ('DE','german'),('FR','french'),('ES','spanish')]:
                        if marker in ident:
                            return name
                    return ident.rsplit('.', 1)[-1][:8].upper()
            finally:
                core.CFRelease(source)
    except (OSError, AttributeError, ValueError):
        pass
    return ''
