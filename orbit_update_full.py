"""One-hop ORBITclip updater from any managed full-install baseline (7.8.2+).

The archive is a *complete application snapshot* with a manifest of managed
runtime files. Never execute any included ZIP scripts. Never update user data
or configuration. Preflight all files; keep backups of all affected files.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile

from orbit_update import (
    API, MAX_ARCHIVE, MAX_UNPACKED, UpdateError, _get_bytes, _process_alive,
    _write_status, digest, download_release, log_update, read_version,
    safe_path, version_tuple,
)

MANIFEST = "update-manifest.json"
BACKUPS = ".orbitclip_patch_backups"
MANIFEST_SCHEMA = 1
MAX_FILES = 160


def _json_bytes(obj):
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def validate_snapshot_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise UpdateError("Неизвестный формат полного обновления")
    if manifest.get("app") != "ORBITclip":
        raise UpdateError("Это не пакет ORBITclip")
    version_tuple(manifest.get("version"))
    files = manifest.get("files")
    if not isinstance(files, dict) or not (2 <= len(files) <= MAX_FILES):
        raise UpdateError("Повреждён список программных файлов")
    if "orbit_version.py" not in files or "launcher.py" not in files:
        raise UpdateError("Полный пакет не содержит обязательные модули")
    for name, spec in files.items():
        # Existing narrow allowlist prevents overwriting client_defaults.json,
        # .venv, user JSON data, docs or anything outside shipped runtime.
        path = safe_path(name)
        if path.as_posix() != name or not isinstance(spec, dict):
            raise UpdateError("Некорректный путь полного обновления")
        if set(spec) != {"sha256", "size"}:
            raise UpdateError("Некорректные данные файла " + name)
        if not isinstance(spec["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", spec["sha256"]):
            raise UpdateError("Некорректный SHA-256 файла " + name)
        if not isinstance(spec["size"], int) or not (0 <= spec["size"] <= MAX_UNPACKED):
            raise UpdateError("Некорректный размер файла " + name)
    return manifest


def latest_snapshot_release(current, token=None):
    metadata = json.loads(_get_bytes(API + "/releases/latest", maximum=1_000_000, token=token))
    version = str(metadata.get("tag_name", "")).removeprefix("v")
    if version_tuple(version) <= version_tuple(current):
        return None
    name = "ORBITclip_CleanInstall_v" + version.replace(".", "_") + ".zip"
    asset = next((a for a in metadata.get("assets", []) if a.get("name") == name), None)
    if not asset:
        raise UpdateError("В последнем релизе отсутствует полный пакет. Попробуй позднее.")
    return {"version":version, "url":str(asset.get("url","")),
            "size":int(asset.get("size",0)),
            "digest":str(asset.get("digest") or "")}


def _no_symlinks(path, target):
    target = Path(target).resolve()
    path = Path(path)
    for part in (path, *path.parents):
        if part == target.parent:
            break
        if part.is_symlink():
            raise UpdateError("Символьная ссылка в пути обновления")


def _manifest_current(target):
    path = Path(target) / MANIFEST
    if not path.is_file() or path.is_symlink():
        raise UpdateError(
            "Приложение установлено до введения накопительных обновлений. "
            "Сначала установи полный базовый выпуск 7.8.2 или новее.")
    current = validate_snapshot_manifest(json.loads(path.read_text(encoding="utf-8")))
    if current["version"] != read_version(target):
        raise UpdateError("Список файлов не соответствует установленной версии")
    return current


def stage_snapshot(archive, target):
    """Verify an entire clean-install ZIP and all local changes before shutdown."""
    target = Path(target).resolve()
    current = _manifest_current(target)
    archive = Path(archive)
    if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE:
        raise UpdateError("Полный пакет отсутствует или слишком велик")
    folder = Path(tempfile.mkdtemp(prefix="orbitclip-full-stage-"))
    try:
        with ZipFile(archive) as zipfile:
            entries = [item for item in zipfile.infolist() if not item.is_dir()]
            if len(entries) > MAX_FILES + 3 or sum(x.file_size for x in entries) > MAX_UNPACKED:
                raise UpdateError("Неверный размер распакованного пакета")
            names = [x.filename for x in entries]
            if len(set(names)) != len(names):
                raise UpdateError("В архиве повторяются имена файлов")
            manifest_name = "ORBITclip/" + MANIFEST
            try:
                raw = zipfile.read(manifest_name)
            except KeyError as exc:
                raise UpdateError("Отсутствует манифест полного обновления") from exc
            if len(raw) > 150_000:
                raise UpdateError("Манифест слишком велик")
            new = validate_snapshot_manifest(json.loads(raw))
            if version_tuple(new["version"]) <= version_tuple(current["version"]):
                raise UpdateError("Новая версия должна быть выше установленной")
            expected = {"ORBITclip/" + name for name in new["files"]}
            expected.update({manifest_name, "ORBITclip/client_defaults.json"})
            if set(names) != expected:
                raise UpdateError("В полном пакете отсутствуют обязательные или есть лишние файлы")
            for info in entries:
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise UpdateError("ZIP содержит символьную ссылку")
            staged = folder / "payload"
            for name, spec in new["files"].items():
                raw_file = zipfile.read("ORBITclip/" + name)
                if len(raw_file) != spec["size"] or digest(raw_file) != spec["sha256"]:
                    raise UpdateError("Контрольная сумма архива не совпала: " + name)
                dst = staged / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(raw_file)
            # Do not even stage client_defaults.json: local credentials and
            # settings must never be substituted with download defaults.
            (staged / MANIFEST).write_bytes(raw)

        old_files = current["files"]
        new_files = new["files"]
        changes = {}
        for name in sorted(set(old_files) | set(new_files)):
            old = old_files.get(name)
            fresh = new_files.get(name)
            if old == fresh:
                continue
            dest = target / name
            _no_symlinks(dest, target)
            if old is not None:
                if (not dest.is_file() or dest.stat().st_size != old["size"] or
                        digest(dest.read_bytes()) != old["sha256"]):
                    raise UpdateError("Изменён программный файл: " + name)
            elif dest.exists():
                raise UpdateError("Новый программный файл уже существует: " + name)
            changes[name] = {"before": old, "after": fresh}
        old_manifest_raw = (target / MANIFEST).read_bytes()
        changes[MANIFEST] = {"before": {"sha256":digest(old_manifest_raw),"size":len(old_manifest_raw)},
                             "after": {"sha256":digest((staged / MANIFEST).read_bytes()),
                                       "size":(staged / MANIFEST).stat().st_size}}
        if "orbit_version.py" not in changes:
            raise UpdateError("В обновлении отсутствует новая версия")
        plan = {"format": "snapshot", "from_version":current["version"],
                "to_version":new["version"], "changes":changes}
        (folder / "plan.json").write_bytes(_json_bytes(plan))
        return folder, plan
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def _checked_plan(folder, target):
    """Recheck hashes and local files after the running app has exited."""
    folder = Path(folder).resolve()
    target = Path(target).resolve()
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    if plan.get("format") != "snapshot" or read_version(target) != plan.get("from_version"):
        raise UpdateError("Версия изменилась после подготовки обновления")
    version_tuple(plan["from_version"])
    version_tuple(plan["to_version"])
    if version_tuple(plan["to_version"]) <= version_tuple(plan["from_version"]):
        raise UpdateError("Невозможно понизить версию")
    changes = plan.get("changes")
    if not isinstance(changes, dict) or MANIFEST not in changes:
        raise UpdateError("Повреждён список изменений")
    current = _manifest_current(target)
    new = validate_snapshot_manifest(json.loads((folder / "payload" / MANIFEST).read_text("utf-8")))
    if current["version"] != plan["from_version"] or new["version"] != plan["to_version"]:
        raise UpdateError("Версии полного пакета не совпадают")
    expected = {}
    for name in sorted(set(current["files"]) | set(new["files"])):
        old=current["files"].get(name)
        after=new["files"].get(name)
        if old != after:
            expected[name]={"before":old,"after":after}
    expected[MANIFEST] = changes[MANIFEST]
    if set(expected) != set(changes):
        raise UpdateError("Манифест изменений был изменён")
    for name, record in changes.items():
        if name != MANIFEST:
            safe_path(name)
        if record != expected[name]:
            raise UpdateError("План обновления изменён: " + name)
        path=target / name
        _no_symlinks(path,target)
        if record["before"] is not None:
            old=record["before"]
            if not path.is_file() or path.stat().st_size!=old["size"] or digest(path.read_bytes())!=old["sha256"]:
                raise UpdateError("Локальный программный файл изменён: " + name)
        elif path.exists():
            raise UpdateError("Путь будущего файла уже существует: " + name)
        if record["after"] is not None:
            spec=record["after"]
            payload=folder / "payload" / name
            if not payload.is_file() or payload.is_symlink() or payload.stat().st_size!=spec["size"] or digest(payload.read_bytes())!=spec["sha256"]:
                raise UpdateError("Файл обновления был изменён: " + name)
    return plan


def install_snapshot(folder, target):
    """Atomic per-file replacement and whole-operation rollback on exception."""
    folder = Path(folder).resolve()
    target = Path(target).resolve()
    plan = _checked_plan(folder,target)
    base=target/BACKUPS
    _no_symlinks(base,target)
    dest=base/"snapshots"/("v"+plan["from_version"]+"_to_v"+plan["to_version"])
    _no_symlinks(dest,target)
    if dest.exists():
        raise UpdateError("Резервная копия такого обновления уже существует")
    changes=plan["changes"]
    dest.mkdir(parents=True)
    completed=[]
    try:
        # Back up EVERYTHING before the first write (including updater itself).
        for name,record in changes.items():
            if record["before"] is not None:
                saved=dest/"files"/name
                saved.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(target/name,saved)
        (dest/"transaction.json").write_bytes(_json_bytes({
            "state":"prepared","from_version":plan["from_version"],
            "to_version":plan["to_version"],
            "paths":{name:record["before"] is not None for name,record in changes.items()}
        }))
        for name,record in changes.items():
            target_file=target/name
            completed.append(name) # BEFORE replacement, so rollback cannot miss file
            if record["after"] is None:
                target_file.unlink()
                continue
            target_file.parent.mkdir(parents=True,exist_ok=True)
            if target_file.exists():
                permissions = stat.S_IMODE(target_file.stat().st_mode)
            else:
                permissions = 0o755 if name.endswith(".command") else 0o644
            fd,tmp=tempfile.mkstemp(prefix=".orbit_swap_",dir=target_file.parent)
            try:
                with os.fdopen(fd,"wb") as writer:
                    writer.write((folder/"payload"/name).read_bytes())
                    writer.flush()
                    os.fsync(writer.fileno())
                if os.name != "nt":
                    os.chmod(tmp,permissions)
                os.replace(tmp,target_file)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            new_spec=record["after"]
            if digest(target_file.read_bytes())!=new_spec["sha256"]:
                raise UpdateError("Повреждён файл после записи: " + name)
        if read_version(target)!=plan["to_version"]:
            raise UpdateError("Версия после установки не совпала")
        (dest/"transaction.json").write_bytes(_json_bytes({
            "state":"committed","from_version":plan["from_version"],
            "to_version":plan["to_version"],
            "paths":{name:record["before"] is not None for name,record in changes.items()}
        }))
        return plan["to_version"]
    except BaseException:
        try:
            for name in reversed(completed):
                record=changes[name]
                original=dest/"files"/name
                existing=target/name
                if record["before"] is not None:
                    existing.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(original,existing)
                elif existing.is_file():
                    existing.unlink()
            (dest/"transaction.json").write_bytes(_json_bytes({
                "state":"rolled_back","from_version":plan["from_version"],
                "to_version":plan["to_version"],
                "paths":{name:record["before"] is not None for name,record in changes.items()}
            }))
        except BaseException as exc:
            raise UpdateError("Откат не завершился; требуется ручное восстановление из " + str(dest)) from exc
        raise


def launch_snapshot_after_exit(stage,target,pid):
    args=[sys.executable,str(Path(__file__).resolve()),"--apply-snapshot",str(stage),
          "--target",str(target),"--wait-pid",str(pid)]
    kwargs={"stdin":subprocess.DEVNULL,"stdout":subprocess.DEVNULL,
            "stderr":subprocess.DEVNULL,"close_fds":True}
    if os.name=="nt":
        kwargs["creationflags"]=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"]=True
    subprocess.Popen(args,**kwargs)


def apply_snapshot_after_exit(stage,target,pid):
    plan=json.loads((Path(stage)/"plan.json").read_text("utf-8"))
    old,new=plan["from_version"],plan["to_version"]
    try:
        log_update("waiting","Ожидание завершения клиента",old_version=old,new_version=new)
        deadline=time.monotonic()+45
        while _process_alive(pid) and time.monotonic()<deadline:
            time.sleep(.2)
        if _process_alive(pid):
            raise UpdateError("ORBITclip не завершился. Установка отменена.")
        log_update("install","Полный пакет: сохранение исходных файлов",old_version=old,new_version=new)
        result=install_snapshot(stage,target)
        log_update("success","Полное обновление установлено",old_version=old,new_version=new)
        _write_status(True,"ORBITclip обновлён до "+result)
        entry=Path(target)/"launcher.py"
        if entry.is_file():
            subprocess.Popen([sys.executable,str(entry)],cwd=target,
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,start_new_session=os.name!="nt")
    except Exception as error:
        log_update("failure","Не удалось завершить полное обновление",
                   old_version=old,new_version=new)
        _write_status(False,str(error))
        raise
    finally:
        shutil.rmtree(stage,ignore_errors=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply-snapshot")
    parser.add_argument("--target")
    parser.add_argument("--wait-pid",type=int,default=0)
    args=parser.parse_args()
    if args.apply_snapshot and args.target and args.wait_pid:
        try:
            apply_snapshot_after_exit(args.apply_snapshot,args.target,args.wait_pid)
        except Exception as error:
            with (Path.home()/".orbitclip_update_error.log").open("a",encoding="utf-8") as log:
                log.write(str(round(time.time()))+" "+str(error)+"\n")
            raise SystemExit(1)
