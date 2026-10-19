"""Filtering and paged presentation of ORBITclip's existing clipboard history.

Pure, local and side-effect free. Never decrypts protected entries, never
persists search results, and never truncates the user's stored history.
"""
from __future__ import annotations
import time

from kinetic_clipboard import LABELS
from orbit_semantic import find as semantic_find

PAGE_SIZE=40
MAX_PAGE_SIZE=5000
PERIODS=("all","today","week","month")


def period_start(period,now=None):
    """Local calendar-day bounds for Today, sliding 7/30 days for Week/Month."""
    if period not in PERIODS:
        raise ValueError("Неизвестный период истории")
    if period=="all":return None
    now=time.time() if now is None else float(now)
    if period=="today":
        d=time.localtime(now)
        return time.mktime((d.tm_year,d.tm_mon,d.tm_mday,0,0,0,0,0,-1))
    return now-(7 if period=="week" else 30)*86400


def history_matches(items,needle="",source="",period="all",semantic=False,
                    category_match=None,now=None):
    """Return ordered matches. Exact search scans all text; semantic is opt-in.

    Preserve current vault ordering; no sorting large payloads on every input.
    Protected records match only safe metadata such as title and source.
    """
    if category_match is None:
        category_match=lambda item:True
    cutoff=period_start(period,now)
    needle=str(needle or "").strip().casefold()
    out=[]
    for entry in items:
        if not category_match(entry):continue
        if source and (entry.get("source_app") or "Неизвестно")!=source:continue
        try:ts=float(entry.get("ts",0))
        except (ValueError,TypeError):ts=0
        if cutoff is not None and ts<cutoff:continue
        if needle and not semantic:
            title=str(entry.get("title") or "")
            category=str(entry.get("category") or "")
            kind=str(entry.get("kind") or "text")
            kind_label=LABELS.get(kind,("","Текст"))[1]
            application=str(entry.get("source_app") or "")
            content="" if entry.get("encrypted") else str(entry.get("text") or "")
            if needle not in " ".join((title,category,kind,kind_label,application,content)).casefold():
                continue
        if semantic and entry.get("encrypted"):
            # Semantic index must never process protected records.
            continue
        out.append(entry)
    if semantic and needle:
        out=semantic_find(needle,out,limit=1500)
    return out


def visible_page(matches,limit=PAGE_SIZE):
    try:n=int(limit)
    except (ValueError,TypeError):n=PAGE_SIZE
    n=max(1,min(n,MAX_PAGE_SIZE))
    return matches[:n],max(0,len(matches)-n)
