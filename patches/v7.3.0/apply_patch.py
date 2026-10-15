#!/usr/bin/env python3
"""ORBITclip standard-library patch installer (Windows and macOS).

Does not access the network, execute copied application code, or touch user data.
Verifies patch payload SHA-256, app version and original file hashes. Creates
rollback backup and performs atomic replacement on same filesystem.
"""
from __future__ import annotations
import argparse
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

HERE=Path(__file__).resolve().parent
MANIFEST=HERE/'patch_manifest.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def installed_version(app):
    file=app/'orbit_version.py'
    if not (app/'orbitclip.py').is_file() or not file.is_file():return None
    try:
        for node in ast.parse(file.read_text(encoding='utf-8')).body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CLIENT_VERSION' for t in node.targets):
                return ast.literal_eval(node.value)
    except (OSError,SyntaxError,ValueError):pass
    return None


def candidates():
    search=[HERE.parent,HERE.parent.parent]
    result=[]
    for base in search:
        if not base.exists():continue
        for folder in [base]+[p for p in base.iterdir() if p.is_dir()]:
            if folder==HERE or folder==HERE/'payload':continue
            if installed_version(folder) and folder not in result:result.append(folder)
    return result


def select_target(specified):
    if specified:
        target=Path(specified).expanduser().resolve()
        if not installed_version(target):raise RuntimeError('В указанной папке не найден ORBITclip: '+str(target))
        return target
    found=candidates()
    if not found:raise RuntimeError('Не найдена папка установленного ORBITclip рядом с патчем. Запусти: python apply_patch.py --target "ПУТЬ_К_ORBITclip"')
    if len(found)==1:return found[0]
    print('\nОбнаружено несколько установок ORBITclip:')
    for index,target in enumerate(found,1):print(f' {index}. {target} [v{installed_version(target)}]')
    while True:
        try:choice=input('Выбери номер установки: ').strip()
        except EOFError:raise RuntimeError('Невозможно автоматически выбрать установку; укажи --target')
        if choice.isdigit() and 1<=int(choice)<=len(found):return found[int(choice)-1]


def patch(target, manifest):
    before=manifest['from_version'];after=manifest['to_version']
    current=installed_version(target)
    if current==after:
        print('ORBITclip уже обновлён до v'+after+'. Повторная установка не требуется.')
        return None
    if current!=before:raise RuntimeError(f'Патч рассчитан на v{before}, найдена v{current or "?"}. Обновление отменено.')
    planned=[]
    for record in manifest['files']:
        rel=Path(record['path'])
        if rel.is_absolute() or '..' in rel.parts or str(rel).startswith('.'):
            raise RuntimeError('Небезопасный путь в манифесте: '+str(rel))
        src=HERE/'payload'/rel
        if not src.is_file() or digest(src)!=record['sha256']:
            raise RuntimeError('Нарушена целостность файла патча: '+str(rel))
        dest=target/rel
        if dest.is_symlink():raise RuntimeError('Символьная ссылка вместо файла: '+str(dest))
        expected=record.get('base_sha256')
        if expected and (not dest.is_file() or digest(dest)!=expected):
            raise RuntimeError('Файл изменён относительно v'+before+': '+str(rel)+'; перезапись отменена.')
        if not expected and dest.exists():raise RuntimeError('Неожиданный файл уже существует: '+str(rel))
        planned.append((src,dest,rel))

    backup_dir=target/'.orbitclip_patch_backups'/('v'+before+'_to_v'+after+'_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    if backup_dir.exists():raise RuntimeError('Папка резервной копии уже существует: '+str(backup_dir))
    backup_dir.mkdir(parents=True)
    tempdir=Path(tempfile.mkdtemp(prefix='.orbitclip_patch_',dir=target))
    completed=[]
    try:
        # Stage all files before touching installation.
        for src,dest,rel in planned:
            staged=tempdir/rel;staged.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,staged)
            if digest(staged)!=digest(src):raise RuntimeError('Ошибка подготовки: '+str(rel))
            if dest.exists():
                saved=backup_dir/rel;saved.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(dest,saved)
        for _,dest,rel in planned:
            dest.parent.mkdir(parents=True,exist_ok=True)
            os.replace(tempdir/rel,dest)
            completed.append((dest,rel))
        if installed_version(target)!=after:raise RuntimeError('После замены файлов версия не совпадает с манифестом')
        (backup_dir/'HOW_TO_RESTORE.txt').write_text(
            'ORBITclip был обновлён с v'+before+' до v'+after+'.\n'
            'При необходимости закрой ORBITclip и скопируй файлы из этой папки обратно,\n'
            'сохраняя относительные пути. Файлы, отсутствующие в копии, были новыми.\n',encoding='utf-8')
        print('\nУспешно обновлено до ORBITclip v'+after)
        print('Папка:',target)
        print('Резервная копия:',backup_dir)
        print('Личные JSON, история и токен не изменялись. Запусти приложение обычным способом.')
        return backup_dir
    except Exception:
        print('Ошибка обновления: восстановление предыдущих файлов...',file=sys.stderr)
        for dest,rel in reversed(completed):
            saved=backup_dir/rel
            if saved.exists():shutil.copy2(saved,dest)
            elif dest.exists():dest.unlink()
        raise
    finally:
        shutil.rmtree(tempdir,ignore_errors=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Применить ORBITclip v7.2.2 к существующей версии v7.2.1')
    parser.add_argument('--target',help='Путь к папке с orbitclip.py')
    args=parser.parse_args(argv)
    manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if manifest.get('app')!='ORBITclip':raise RuntimeError('Неподходящий манифест')
    target=select_target(args.target)
    print('Найдена установка:',target,'версия:',installed_version(target))
    print('Перед установкой полностью закрой ORBITclip на этом компьютере.')
    patch(target,manifest)
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as ex:
        print('\nОШИБКА:',ex,file=sys.stderr)
        sys.exit(1)
