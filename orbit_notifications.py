"""Private, bounded, durable notification inbox. Never stores message bodies."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time
import os

DEFAULT_PATH = Path.home() / '.orbitclip_notifications.sqlite3'
KINDS = ('messages', 'files', 'spaces', 'system')


class NotificationStore:
    def __init__(self, path=DEFAULT_PATH, retention_days=90, max_entries=1500):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        if os.name!='nt':os.chmod(self.path,0o600)
        self.db.execute('PRAGMA busy_timeout = 3000')
        self.db.execute('''CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
            target TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0,
            dedupe TEXT NOT NULL DEFAULT '')''')
        self.db.execute('CREATE INDEX IF NOT EXISTS n_ts ON notifications(ts DESC)')
        self.db.commit()
        self.retention_days = max(1, int(retention_days))
        self.max_entries = max(100, int(max_entries))
        self.prune()

    def push(self, kind, title, description='', target='', dedupe='', now=None):
        if kind not in KINDS:
            raise ValueError('Unknown notification category')
        now = float(now if now is not None else time.time())
        # Never provide plaintext messages or credentials as description.
        description = str(description or '')[:150]
        if dedupe:
            row = self.db.execute('SELECT id FROM notifications WHERE dedupe=? AND ts>=? ORDER BY id DESC LIMIT 1',
                                  (str(dedupe)[:160], now - 5)).fetchone()
            if row:
                return None
        cur = self.db.execute('INSERT INTO notifications(ts,kind,title,description,target,dedupe) VALUES(?,?,?,?,?,?)',
                              (now, kind, str(title)[:100], description, str(target)[:160], str(dedupe)[:160]))
        self.db.commit()
        self.prune(now)
        return cur.lastrowid

    def list(self, kind=None, only_unread=False, limit=200):
        where = ['1=1']; args = []
        if kind:
            if kind not in KINDS: return []
            where.append('kind=?'); args.append(kind)
        if only_unread: where.append('seen=0')
        args.append(max(1, min(int(limit), 1000)))
        cur = self.db.execute('SELECT id,ts,kind,title,description,target,seen FROM notifications WHERE '
                              + ' AND '.join(where) + ' ORDER BY id DESC LIMIT ?', args)
        return [dict(zip(('id','ts','kind','title','description','target','seen'), r)) for r in cur]

    def unread(self):
        return int(self.db.execute('SELECT COUNT(*) FROM notifications WHERE seen=0').fetchone()[0])

    def mark_read(self, id=None):
        if id is None:self.db.execute('UPDATE notifications SET seen=1 WHERE seen=0')
        else:self.db.execute('UPDATE notifications SET seen=1 WHERE id=?', (int(id),))
        self.db.commit()

    def clear(self):
        self.db.execute('DELETE FROM notifications')
        self.db.commit()

    def prune(self, now=None):
        now = time.time() if now is None else float(now)
        self.db.execute('DELETE FROM notifications WHERE ts<?', (now - self.retention_days*86400,))
        self.db.execute('DELETE FROM notifications WHERE id NOT IN (SELECT id FROM notifications ORDER BY id DESC LIMIT ?)',
                        (self.max_entries,))
        self.db.commit()

    def close(self):
        self.db.close()
