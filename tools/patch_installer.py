#!/usr/bin/env python3
"""Install a version-specific ORBITclip patch; never touches user data or runtime."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

HERE=Path(__file__).resolve().parent

def digest(data):
    return hashlib.sha256(data).hexdigest()

def version(folder):
    try:
        tree=ast.parse((folder/'orbit_version.py').read_text('utf-8'))
        for stmt in tree.body:
            if isinstance(stmt,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CLIENT_VERSION' for t in stmt.targets):
                return ast.literal_eval(stmt.value)
    except (OSError,ValueError,SyntaxError):
        pass
    return None

def install(folder):
    folder=folder.resolve()
    data=json.loads((HERE/'manifest.json').read_text('utf-8'))
    if data.get('app')!='ORBITclip' or version(folder)!=data['from_version']:
        raise RuntimeError('Версия ORBITclip не соответствует патчу: '+str(version(folder)))
    changes=data['changes']
    for item in changes:
        path=Path(item['path'])
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0].startswith('.'):
            raise RuntimeError('Недопустимый путь')
        destination=folder/path
        if destination.is_symlink():
            raise RuntimeError('Ссылка вместо файла: '+str(path))
        if item['before'] is not None:
            if not destination.is_file() or digest(destination.read_bytes())!=item['before']:
                raise RuntimeError('Файл изменён, обновление остановлено: '+str(path))
        elif destination.exists():
            raise RuntimeError('Новый путь уже существует: '+str(path))
        if item['after'] is not None:
            payload=HERE/'payload'/path
            if not payload.is_file() or digest(payload.read_bytes())!=item['after']:
                raise RuntimeError('Повреждён патч: '+str(path))
    backup=folder/'.orbitclip_patch_backups'/('v'+data['from_version']+'_to_v'+data['to_version'])
    if backup.exists():
        raise RuntimeError('Резервная копия предыдущей попытки уже существует: '+str(backup))
    backup.mkdir(parents=True)
    applied=[]
    try:
        for item in changes:
            rel=Path(item['path'])
            destination=folder/rel
            if destination.exists():
                saved=backup/rel
                saved.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(destination,saved)
        for item in changes:
            rel=Path(item['path'])
            destination=folder/rel
            if item['after'] is None:
                destination.unlink()
            else:
                destination.parent.mkdir(parents=True,exist_ok=True)
                fd,tmp=tempfile.mkstemp(prefix='.orbit_tmp_',dir=destination.parent)
                try:
                    with os.fdopen(fd,'wb') as stream:
                        stream.write((HERE/'payload'/rel).read_bytes())
                    os.replace(tmp,destination)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            applied.append(rel)
        if version(folder)!=data['to_version']:
            raise RuntimeError('Версия после установки не совпала')
    except Exception:
        for rel in reversed(applied):
            destination=folder/rel
            saved=backup/rel
            if saved.is_file():
                shutil.copy2(saved,destination)
            elif destination.is_file():
                destination.unlink()
        raise
    print('Обновлено до ORBITclip',data['to_version'])
    print('Резервные копии:',backup)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',help='Папка ORBITclip; по умолчанию — рядом с патчем')
    args=parser.parse_args()
    candidates=[
        HERE.parent/'ORBITclip', HERE.parent,
        HERE.parent.parent/'ORBITclip', HERE.parent.parent,
    ]
    target=Path(args.target).expanduser() if args.target else next(
        (p for p in candidates if version(p)=='7.5.0'),None)
    if target is None:
        try:
            entered=input('Введите полный путь к папке ORBITclip 7.5.0: ').strip().strip('"')
        except EOFError:
            entered=''
        if not entered:
            raise SystemExit('Укажи путь: python apply_patch.py --target ПУТЬ')
        target=Path(entered).expanduser()
    install(target)
