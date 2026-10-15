"""Local-only aggregate usage measurements. No payload, host or secrets stored."""
from __future__ import annotations

from pathlib import Path
import csv
import sqlite3
import time
import os
from datetime import datetime, timedelta

DEFAULT_PATH = Path.home() / '.orbitclip_analytics.sqlite3'
EVENTS = ('clip_capture','clip_manual','clip_copy','history_open','chat_open','chat_in','chat_out',
          'file_in','file_out','space_open','space_clip_in','space_chat_in','ocr_run',
          'screenshot','smart_action','sql_open','notification_open','wheel_commit')


def safe_source(value):
    name = str(value or 'Не определено').strip()
    return name[:80] or 'Не определено'


class AnalyticsStore:
    def __init__(self, path=DEFAULT_PATH, enabled=True):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.enabled=bool(enabled)
        self.db=sqlite3.connect(str(self.path))
        if os.name!='nt':os.chmod(self.path,0o600)
        self.db.execute('PRAGMA busy_timeout=3000')
        self.db.execute('''CREATE TABLE IF NOT EXISTS counters (
            day TEXT NOT NULL, event TEXT NOT NULL, source TEXT NOT NULL,
            count INTEGER NOT NULL, PRIMARY KEY(day,event,source))''')
        self.db.commit()
        self.prune()

    def record(self, event, source='', now=None):
        if not self.enabled:return
        if event not in EVENTS:raise ValueError('Unexpected analytics event')
        day=datetime.fromtimestamp(float(now if now is not None else time.time())).date().isoformat()
        source = safe_source(source) if event=='clip_capture' else ''
        self.db.execute('''INSERT INTO counters(day,event,source,count) VALUES(?,?,?,1)
           ON CONFLICT(day,event,source) DO UPDATE SET count=count+1''',(day,event,source))
        self.db.commit()

    def summary(self, days=30, now=None):
        days=max(1,min(365,int(days)))
        today=(datetime.fromtimestamp(float(now)).date() if now is not None else datetime.now().date())
        first=(today-timedelta(days=days-1)).isoformat()
        rows=self.db.execute('SELECT day,event,source,count FROM counters WHERE day>=? ORDER BY day', (first,)).fetchall()
        totals={event:0 for event in EVENTS}
        sources={};activity={}
        for day,event,source,n in rows:
            totals[event]+=n
            if event=='clip_capture':sources[source]=sources.get(source,0)+n
            activity[day]=activity.get(day,0)+n
        return {'totals':totals,'sources':sorted(sources.items(),key=lambda x:(-x[1],x[0]))[:12],
                'days':[(today-timedelta(days=i)).isoformat() for i in range(days-1,-1,-1)],
                'activity':activity}

    def export_csv(self,path):
        rows=self.db.execute('SELECT day,event,source,count FROM counters ORDER BY day,event,source').fetchall()
        with Path(path).open('w',encoding='utf-8-sig',newline='') as file:
            writer=csv.writer(file);writer.writerow(('day','event','source','count'));writer.writerows(rows)

    def prune(self, now=None):
        today=datetime.fromtimestamp(float(now)).date() if now is not None else datetime.now().date()
        self.db.execute('DELETE FROM counters WHERE day<?', ((today-timedelta(days=365)).isoformat(),));self.db.commit()

    def reset(self):
        self.db.execute('DELETE FROM counters');self.db.commit()

    def close(self):self.db.close()
