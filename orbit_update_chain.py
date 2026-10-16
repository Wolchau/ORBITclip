"""Multi-release updater for ORBITclip 7.8.1+.

Plans by manifest dependencies, not by adjacent version numbers. Every ZIP and
the complete chain are verified on a disposable replica BEFORE touching the
installed app. A whole-chain backup permits rollback if a later step fails.
No scripts contained in release ZIPs are executed.
"""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile

from orbit_update import (
    API, UpdateError, _get_bytes, version_tuple, read_version, safe_path,
    download_release, stage_archive, install_staged, digest, log_update,
    _process_alive, _write_status
)

MAX_RELEASES = 80
MAX_STEPS = 40
MAX_TOTAL_DOWNLOAD = 60_000_000
BACKUP_FOLDER = '.orbitclip_patch_backups'


def list_releases(current, token=None):
    """Read paged stable GitHub releases; do not assume a version is consecutive."""
    output = []
    for page in range(1, 5):
        url = f'{API}/releases?per_page=100&page={page}'
        releases = json.loads(_get_bytes(url, maximum=2_000_000, token=token))
        if not isinstance(releases, list):
            raise UpdateError('GitHub вернул некорректный список релизов')
        for release in releases:
            if release.get('draft') or release.get('prerelease'):
                continue
            value = str(release.get('tag_name', '')).removeprefix('v')
            try:
                if version_tuple(value) <= version_tuple(current):
                    continue
            except UpdateError:
                continue
            filename = 'ORBITclip_Patch_v' + value.replace('.', '_') + '.zip'
            asset = next((a for a in release.get('assets', [])
                          if a.get('name') == filename), None)
            if asset is None:
                output.append({'version': value, 'url': None, 'size': 0, 'digest': ''})
                continue
            output.append({'version': value, 'url': str(asset.get('url','')),
                           'size': int(asset.get('size',0)),
                           'digest': str(asset.get('digest') or '')})
        if len(releases) < 100:
            break
    unique = {}
    for value in output:
        unique.setdefault(value['version'], value)
    ordered = sorted(unique.values(), key=lambda x: version_tuple(x['version']))
    if len(ordered) > MAX_RELEASES:
        raise UpdateError('Пропущено слишком много релизов для автоматической установки')
    return ordered


def inspect_zip_manifest(archive):
    """Read just manifest for dependency graph; full ZIP validation comes later."""
    if Path(archive).stat().st_size > 12_000_000:
        raise UpdateError('Слишком большой архив патча')
    with ZipFile(archive) as z:
        if len(z.infolist())>120 or sum(e.file_size for e in z.infolist())>24_000_000:
            raise UpdateError('Архив превышает лимит распаковки')
        paths = [name for name in z.namelist() if name.endswith('/manifest.json')]
        if len(paths) != 1:
            raise UpdateError('Неверный состав ZIP-патча')
        manifest = json.loads(z.read(paths[0]))
    if not isinstance(manifest,dict) or manifest.get('app') != 'ORBITclip':
        raise UpdateError('Неверный манифест ORBITclip')
    old = str(manifest.get('from_version',''))
    new = str(manifest.get('to_version',''))
    if version_tuple(new) <= version_tuple(old):
        raise UpdateError('Неверный порядок версий в патче')
    if not isinstance(manifest.get('changes'),list):
        raise UpdateError('Повреждён список файлов патча')
    return manifest


def shortest_path(start, destination, available):
    """BFS graph edges are manifests (from_version -> to_version)."""
    frontier = deque([(start, [])])
    visited = {start}
    by_source = {}
    for manifest, archive in available:
        begin = manifest['from_version']
        end = manifest['to_version']
        if version_tuple(end) > version_tuple(destination):
            continue
        by_source.setdefault(begin, []).append((end,manifest,archive))
    while frontier:
        version, route = frontier.popleft()
        if version == destination:
            return route
        for next_version,manifest,archive in sorted(
                by_source.get(version,[]),key=lambda x:version_tuple(x[0]),reverse=True):
            if next_version not in visited:
                visited.add(next_version)
                frontier.append((next_version,route+[(next_version,manifest,archive)]))
    raise UpdateError(f'От {start} до {destination} нет полной цепочки патчей. '
                      'Используй полную установку с сохранением пользовательских данных.')


def _copy_initial_files(target, replica, manifests):
    """Replica contains only existing files involved in the chain."""
    source = Path(target).resolve()
    replica = Path(replica)
    paths = {'orbit_version.py'}
    for manifest in manifests:
        for item in manifest['changes']:
            paths.add(str(safe_path(item['path'])))
    for relative in paths:
        item = source / relative
        if item.is_symlink() or any(parent.is_symlink() for parent in item.parents
                                    if parent == source or source in parent.parents):
            raise UpdateError('Символьная ссылка в файлах обновления: ' + relative)
        if item.is_file():
            dest = replica / relative
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(item,dest)
        elif item.exists():
            raise UpdateError('Недопустимый тип файла: '+relative)


def _simulate(stages,target):
    """Full real installer run against a throw-away target for preflight."""
    with tempfile.TemporaryDirectory(prefix='orbit-chain-audit-') as temporary:
        shadow=Path(temporary)/'app'
        shadow.mkdir()
        manifests=[json.loads((Path(stage)/'manifest.json').read_text('utf-8'))
                   for stage in stages]
        _copy_initial_files(target,shadow,manifests)
        for stage in stages:
            install_staged(stage,shadow)
        return read_version(shadow)


def prepare_chain_from_archives(current, target, archives, destination):
    """Offline entry point also used by tests. All archives must be local ZIPs."""
    available=[]
    for version,archive in archives:
        manifest=inspect_zip_manifest(archive)
        if manifest['to_version'] != version:
            raise UpdateError('Имя релиза не совпадает с содержимым патча: '+str(version))
        available.append((manifest,Path(archive)))
    route=shortest_path(current,destination,available)
    if not route:
        raise UpdateError('Обновление не требуется')
    if len(route)>MAX_STEPS:
        raise UpdateError('Цепочка обновлений слишком длинная')
    plan=Path(tempfile.mkdtemp(prefix='orbitclip-chain-'))
    stages=[]
    try:
        # Stage payload hashes without executing bundled scripts. Existing
        # stage_archive checks the *initial* target, so for later patches a
        # throwaway shadow is used to verify each pre/post hash in order.
        for i,(_,manifest,archive) in enumerate(route):
            folder=plan/f'step-{i:03}'
            folder.mkdir()
            # Extract ONLY manifest and named payload bytes, never ZIP scripts.
            with ZipFile(archive) as z:
                if len(z.infolist())>120 or sum(e.file_size for e in z.infolist())>24_000_000:
                    raise UpdateError('Архив превышает лимит распаковки')
                prefix='ORBITclip_Patch_v'+manifest['to_version'].replace('.','_')+'/'
                if prefix+'manifest.json' not in z.namelist():
                    raise UpdateError('Неверная структура ZIP')
                declared=json.loads(z.read(prefix+'manifest.json'))
                if declared != manifest:
                    raise UpdateError('Патч изменён')
                for change in manifest['changes']:
                    rel=safe_path(change['path'])
                    if change.get('after') is not None:
                        entry=prefix+'payload/'+rel.as_posix()
                        content=z.read(entry)
                        if digest(content) != change['after']:
                            raise UpdateError('Несовпадение SHA-256: '+rel.as_posix())
                        dest=folder/'payload'/Path(*rel.parts)
                        dest.parent.mkdir(parents=True,exist_ok=True)
                        dest.write_bytes(content)
                (folder/'manifest.json').write_text(
                    json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            stages.append(folder)
        if _simulate(stages,target) != destination:
            raise UpdateError('Ошибка проверки итоговой версии обновления')
        (plan/'plan.json').write_text(json.dumps({
            'app':'ORBITclip', 'from_version':current, 'to_version':destination,
            'steps':[s.name for s in stages]},ensure_ascii=False),encoding='utf-8')
        return plan, [manifest for _,manifest,_ in route]
    except BaseException:
        shutil.rmtree(plan,ignore_errors=True)
        raise


def download_and_prepare(releases,target,token=None,progress=None):
    """Fetch available patches, resolve graph, stage & simulate before reboot."""
    current=read_version(target)
    if not releases:
        raise UpdateError('Новых релизов нет')
    target_version=max((v['version'] for v in releases),
                       key=version_tuple)
    if version_tuple(target_version)<=version_tuple(current):
        raise UpdateError('Обновление не требуется')
    candidates=[x for x in releases if x.get('url')]
    if len(candidates)>MAX_RELEASES:
        raise UpdateError('Превышен лимит количества патчей')
    total_size=sum(max(0,int(x.get('size',0))) for x in candidates)
    if total_size>MAX_TOTAL_DOWNLOAD:
        raise UpdateError('Суммарный размер цепочки слишком велик')
    archives=[]
    allocated=[]
    try:
        for i,item in enumerate(candidates):
            if progress:progress(i,len(candidates),0,int(item.get('size',0)))
            archive=download_release(item,token=token,
                 progress=(lambda done,total,index=i:progress(index,len(candidates),done,total))
                 if progress else None)
            allocated.append(archive.parent)
            archives.append((item['version'],archive))
            if progress:progress(i+1,len(candidates),0,0)
        return prepare_chain_from_archives(current,target,archives,target_version)
    finally:
        for folder in allocated:
            shutil.rmtree(folder,ignore_errors=True)


def _plan_stages(plan):
    plan=Path(plan).resolve()
    info=json.loads((plan/'plan.json').read_text('utf-8'))
    if info.get('app')!='ORBITclip':
        raise UpdateError('Неверный план обновления')
    names=info.get('steps')
    if not isinstance(names,list) or not (1<=len(names)<=MAX_STEPS):
        raise UpdateError('Некорректное число этапов')
    if names != [f'step-{i:03}' for i in range(len(names))]:
        raise UpdateError('Недопустимые каталоги обновления')
    stages=[plan/name for name in names]
    chain=[json.loads((step/'manifest.json').read_text('utf-8'))
           for step in stages]
    expected=info['from_version']
    for manifest in chain:
        if manifest.get('from_version')!=expected:
            raise UpdateError('Разрыв цепочки обновлений')
        expected=manifest['to_version']
    if expected!=info['to_version']:
        raise UpdateError('Версия последнего шага не совпадает')
    return info,stages,chain


def install_chain(plan,target, on_step=None):
    """One logical transaction, including restoration of *all* prior steps."""
    target=Path(target).resolve()
    info,stages,chain=_plan_stages(plan)
    if read_version(target)!=info['from_version']:
        raise UpdateError('Установленная версия изменилась после подготовки')
    # Double preflight just after GUI closes. No writes until all steps pass.
    if _simulate(stages,target)!=info['to_version']:
        raise UpdateError('Предварительная проверка всей цепочки не прошла')
    backups=target/BACKUP_FOLDER
    if backups.is_symlink():
        raise UpdateError('Резервная папка является ссылкой')
    chains_directory=backups/'chains'
    if chains_directory.is_symlink():
        raise UpdateError('Папка резервных цепочек является ссылкой')
    global_backup=chains_directory/('v'+info['from_version']+'_to_v'+info['to_version'])
    if global_backup.exists() or global_backup.is_symlink():
        raise UpdateError('Такая резервная копия уже существует')
    paths=sorted({str(safe_path(item['path'])) for manifest in chain
                  for item in manifest['changes']})
    prior_backups=[]
    for m in chain:
        intermediate=backups/('v'+m['from_version']+'_to_v'+m['to_version'])
        if intermediate.exists():
            raise UpdateError('Один из промежуточных патчей уже применялся')
        prior_backups.append(intermediate)
    global_backup.mkdir(parents=True)
    original={}
    applied=False
    try:
        for rel in paths:
            src=target/rel
            original[rel]=src.is_file()
            if original[rel]:
                dst=global_backup/'files'/rel
                dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,dst)
        (global_backup/'original.json').write_text(
            json.dumps({'from_version':info['from_version'],
                        'to_version':info['to_version'],'files':original},ensure_ascii=False),
            encoding='utf-8')
        applied=True
        for i,stage in enumerate(stages,1):
            if on_step:on_step(i,len(stages))
            install_staged(stage,target)
        if read_version(target)!=info['to_version']:
            raise UpdateError('Некорректная итоговая версия')
        return info['to_version']
    except BaseException:
        if applied:
            try:
                for rel,existed in original.items():
                    dst=target/rel
                    previous=global_backup/'files'/rel
                    if existed:
                        dst.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copy2(previous,dst)
                    elif dst.is_file():
                        dst.unlink()
                for intermediate in prior_backups:
                    if intermediate.exists():
                        shutil.rmtree(intermediate)
                # Keep the snapshot for diagnostics/recovery without blocking
                # the user from retrying a newly downloaded chain.
                failed=backups/'failed'
                if failed.is_symlink():
                    raise UpdateError('Папка аварийных копий является ссылкой')
                failed.mkdir(exist_ok=True)
                destination=failed/(global_backup.name+'-'+str(time.time_ns()))
                global_backup.rename(destination)
            except BaseException as recovery_error:
                raise UpdateError(
                    'Автоматическое восстановление не завершилось. '
                    'Не запускай программу до ручной проверки резервной копии: '
                    +str(global_backup)) from recovery_error
        raise


def launch_chain_after_exit(plan,target,pid):
    path=Path(__file__).resolve()
    args=[sys.executable,str(path),'--apply-plan',str(plan),
          '--target',str(target),'--wait-pid',str(pid)]
    kwargs={'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,
            'stderr':subprocess.DEVNULL,'close_fds':True}
    if os.name=='nt':
        kwargs['creationflags']=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session']=True
    subprocess.Popen(args,**kwargs)


def apply_after_exit(plan,target,pid):
    info,stages,chain=_plan_stages(plan)
    old,new=info['from_version'],info['to_version']
    try:
        log_update('waiting','Ожидание закрытия ORBITclip',old_version=old,new_version=new)
        deadline=time.monotonic()+45
        while _process_alive(pid) and time.monotonic()<deadline:
            time.sleep(.2)
        if _process_alive(pid):
            raise UpdateError('ORBITclip не завершился; обновление не выполнено')
        def feedback(i,count):
            log_update('install',f'Этап {i} из {count}',
                       old_version=chain[i-1]['from_version'],
                       new_version=chain[i-1]['to_version'])
        updated=install_chain(plan,target,on_step=feedback)
        log_update('success',f'Применено патчей: {len(stages)}',
                   old_version=old,new_version=new)
        _write_status(True,'ORBITclip обновлён до '+updated)
        entry=Path(target)/'launcher.py'
        if entry.is_file():
            subprocess.Popen([sys.executable,str(entry)],cwd=target,
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=os.name!='nt')
    except Exception as exc:
        log_update('rollback','Цепочка прервана; проверь сохранность данных и резервную копию',
                   old_version=old,new_version=new)
        _write_status(False,str(exc))
        raise
    finally:
        shutil.rmtree(plan,ignore_errors=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply-plan')
    parser.add_argument('--target')
    parser.add_argument('--wait-pid',type=int,default=0)
    args=parser.parse_args()
    if args.apply_plan and args.target and args.wait_pid:
        try:
            apply_after_exit(args.apply_plan,args.target,args.wait_pid)
        except Exception as exc:
            with (Path.home()/'.orbitclip_update_error.log').open('a',encoding='utf-8') as log:
                log.write(str(round(time.time()))+' '+str(exc)+'\n')
            raise SystemExit(1)
