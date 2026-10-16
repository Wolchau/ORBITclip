"""Optional global Flow shortcuts using the existing pynput dependency.

Listener never touches Qt; GUI thread drains events. Failure leaves menu access.
"""
import queue


class FlowShortcuts:
    def __init__(self):
        self.events=queue.Queue()
        self.listener=None
        self.error=''

    def start(self):
        try:
            from pynput.keyboard import GlobalHotKeys
            self.listener=GlobalHotKeys({
                '<ctrl>+<shift>+<space>':lambda:self.events.put('palette'),
                '<ctrl>+<alt>+j':lambda:self.events.put('queue_next'),
            })
            self.listener.daemon=True
            self.listener.start()
        except Exception as exc:
            self.error=str(exc)
            self.listener=None

    def stop(self):
        if self.listener is not None:
            try:self.listener.stop()
            except Exception:pass
            self.listener=None
