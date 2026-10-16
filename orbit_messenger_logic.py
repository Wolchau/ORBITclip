"""No-Qt attachment metadata checks before a messenger file send."""
from pathlib import Path
from kinetic_remote import MAX_FILE_SIZE


def validate_dropped_files(paths, limit=10):
    valid=[]
    rejected=[]
    for raw in list(paths)[:100]:
        p=Path(raw)
        try:
            if not p.is_file():
                rejected.append((p.name,"Не файл"));continue
            size=p.stat().st_size
            if size>MAX_FILE_SIZE:
                rejected.append((p.name,"Больше 3 МБ"));continue
            if len(valid)>=limit:
                rejected.append((p.name,"Не больше 10 за отправку"));continue
            valid.append((p,size))
        except (OSError,ValueError) as e:
            rejected.append((p.name,str(e)[:80]))
    return valid,rejected
