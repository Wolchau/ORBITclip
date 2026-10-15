"""Safe on-receipt attachment storage, with no Qt dependency.

Incoming files are never executed automatically. Path names from peers are
untrusted and cannot influence the download directory.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import re

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
MAX_BASENAME = 120


def safe_attachment_name(name):
    """Constrain a remote display name to a harmless single filename."""
    # Treat both POSIX and Windows separators as path separators on every OS.
    name = str(name or 'attachment').replace('\\', '/').split('/')[-1]
    name = INVALID.sub('_', name).strip(' .')[:MAX_BASENAME].strip(' .')
    if not name or name in ('.', '..'):
        return 'attachment'
    if name.split('.')[0].upper() in ('CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))):
        name = '_'+name
    return name


def decode_attachment(data, max_size):
    encoded = data.get('bytes','')
    if not isinstance(encoded,str) or len(encoded) > ((max_size+2)//3)*4 + 8:
        raise ValueError('Некорректный размер вложения')
    try:
        raw = base64.b64decode(encoded,validate=True)
    except (ValueError,base64.binascii.Error) as e:
        raise ValueError('Неверное кодирование вложения') from e
    if len(raw)>max_size:
        raise ValueError('Файл превышает допустимый размер')
    return raw


def save_attachment(data, download_directory, max_size):
    """Store one incoming attachment exclusively; no overwrite, no traversal.

    Creates path in a dedicated directory, with collision suffix if needed.
    Returns a Path on success. Caller binds that path to message metadata.
    """
    raw = decode_attachment(data,max_size)
    root = Path(download_directory).expanduser()
    root.mkdir(parents=True,exist_ok=True)
    name = safe_attachment_name(data.get('name'))
    base = Path(name)
    for number in range(10000):
        candidate = root/(name if not number else f'{base.stem} ({number}){base.suffix}')
        try:
            with candidate.open('xb') as dest:
                try:os.chmod(candidate,0o600)
                except OSError:pass
                dest.write(raw)
            return candidate
        except FileExistsError:
            continue
    raise OSError('Слишком много одинаковых файлов в папке загрузок')
