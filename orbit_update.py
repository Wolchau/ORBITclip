"""ORBITclip self-update engine (stdlib only, executable payload is NEVER run).

The GUI only stages a verified delta; a fresh helper process waits for the
running client to quit before replacing files. Source and payload SHA-256
are checked twice, and all changed files are backed up before replacement.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from zipfile import ZipFile

REPO = "Wolchau/ORBITclip"
API = "https://api.github.com/repos/" + REPO
MAX_ARCHIVE = 12_000_000
MAX_UNPACKED = 24_000_000
STATUS_FILE = Path.home() / ".orbitclip_update_status.json"


class UpdateError(RuntimeError):
    pass


def version_tuple(text):
    found = re.fullmatch(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})", str(text or ""))
    if not found:
        raise UpdateError("Неизвестный формат версии: " + str(text))
    return tuple(map(int, found.groups()))


def read_version(root):
    try:
        tree = ast.parse((Path(root) / "orbit_version.py").read_text(encoding="utf-8"))
        return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(x, ast.Name) and x.id == "CLIENT_VERSION" for x in n.targets))
    except (StopIteration, OSError, ValueError, SyntaxError) as exc:
        raise UpdateError("Не удалось определить установленную версию") from exc


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _headers(*, binary=False):
    header = {"User-Agent": "ORBITclip-updater/1.0",
              "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
              "X-GitHub-Api-Version": "2022-11-28"}
    # Used only from the environment, never stored in settings/logs.
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        header["Authorization"] = "Bearer " + token
    return header


def _get_bytes(url, binary=False, maximum=MAX_ARCHIVE):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ("api.github.com",
                                                           "github.com",
                                                           "release-assets.githubusercontent.com"):
        raise UpdateError("Недопустимый адрес загрузки")
    request = urllib.request.Request(url, headers=_headers(binary=binary))
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            data = response.read(maximum + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Не удалось связаться с GitHub: " + str(exc)) from exc
    if len(data) > maximum:
        raise UpdateError("Размер файла превышает допустимый лимит")
    return data


def latest_release(current):
    """Return verified GitHub metadata, not a guessed download URL."""
    data = json.loads(_get_bytes(API + "/releases/latest", maximum=1_000_000))
    tag = str(data.get("tag_name", "")).removeprefix("v")
    if version_tuple(tag) <= version_tuple(current):
        return None
    name = "ORBITclip_Patch_v" + tag.replace(".", "_") + ".zip"
    asset = next((a for a in data.get("assets", []) if a.get("name") == name), None)
    return {
        "version": tag,
        "url": (str(asset["url"]) if asset else None),
        "size": (int(asset.get("size", 0)) if asset else 0),
        "digest": (str(asset.get("digest") or "") if asset else ""),
        "page": "https://github.com/" + REPO + "/releases/tag/v" + tag,
    }


def download_release(release):
    url = release.get("url")
    if not url:
        raise UpdateError("Для релиза не опубликован патч. Доступна ручная установка.")
    if not url.startswith(API + "/releases/assets/"):
        raise UpdateError("Адрес ZIP не принадлежит официальному релизу")
    result = _get_bytes(url, binary=True)
    expected = release.get("digest", "")
    if expected.startswith("sha256:") and digest(result) != expected[7:].lower():
        raise UpdateError("Контрольная сумма загруженного архива не совпала")
    if not result.startswith(b"PK"):
        raise UpdateError("GitHub не вернул ZIP. Проверь доступ к репозиторию.")
    folder = Path(tempfile.mkdtemp(prefix="orbitclip-download-"))
    output = folder / "update.zip"
    output.write_bytes(result)
    return output


def safe_path(text):
    if not isinstance(text, str) or "\\" in text:
        raise UpdateError("Недопустимый путь в архиве")
    p = PurePosixPath(text)
    if (p.is_absolute() or not p.parts or any(x in ("", ".", "..") for x in p.parts)
            or p.parts[0].startswith(".")):
        raise UpdateError("Недопустимый путь обновления: " + str(text))
    if len(p.parts) == 1:
        allowed = (p.suffix == ".py" and not p.name.startswith("test_")
                   and p.name != "orbit_capture.py") or p.name in {
            "requirements-client.txt", "start_windows.bat", "start_mac.command"}
    else:
        allowed = p.parts[0] == "assets" and p.suffix.lower() in {
            ".png", ".svg", ".ico", ".icns", ".gif", ".jpg", ".jpeg", ".webp"}
    if not allowed:
        raise UpdateError("Патч пытается изменить пользовательский или служебный файл: " + text)
    return p


def validate_manifest(data, target):
    if not isinstance(data, dict) or data.get("app") != "ORBITclip":
        raise UpdateError("Это не патч ORBITclip")
    old = str(data.get("from_version", ""))
    new = str(data.get("to_version", ""))
    if read_version(target) != old:
        raise UpdateError(f"Патч предназначен для {old}, установлена {read_version(target)}")
    if version_tuple(new) <= version_tuple(old):
        raise UpdateError("Патч не должен понижать версию")
    changes = data.get("changes")
    if not isinstance(changes, list) or not changes:
        raise UpdateError("Пустой манифест")
    if not any(x.get("path") == "orbit_version.py" for x in changes if isinstance(x, dict)):
        raise UpdateError("В патче отсутствует изменение версии")
    seen = set()
    for x in changes:
        if not isinstance(x, dict):
            raise UpdateError("Ошибка записи манифеста")
        path = safe_path(x.get("path"))
        if str(path) in seen:
            raise UpdateError("Повторяющийся путь: " + str(path))
        seen.add(str(path))
        for key in ("before", "after"):
            checksum = x.get(key)
            if checksum is not None and not re.fullmatch(r"[a-f0-9]{64}", str(checksum)):
                raise UpdateError("Некорректная контрольная сумма")
        if x.get("before") is None and x.get("after") is None:
            raise UpdateError("Пустая операция")
        destination = Path(target) / Path(*path.parts)
        for section in (destination, *destination.parents):
            if section == Path(target).resolve().parent:
                break
            if section.is_symlink():
                raise UpdateError("Ссылка в пути файла: " + str(path))
        if x.get("before") is not None:
            if not destination.is_file() or digest(destination.read_bytes()) != x["before"]:
                raise UpdateError("Локальный файл изменён: " + str(path))
        elif destination.exists():
            raise UpdateError("Новый файл уже существует: " + str(path))
    return data


def stage_archive(archive, target):
    """Validate both GitHub and manually selected ZIPs without executing ZIP code."""
    archive = Path(archive)
    if archive.stat().st_size > MAX_ARCHIVE:
        raise UpdateError("Архив слишком велик")
    stage = Path(tempfile.mkdtemp(prefix="orbitclip-update-stage-"))
    try:
        with ZipFile(archive) as z:
            items = z.infolist()
            if sum(i.file_size for i in items) > MAX_UNPACKED:
                raise UpdateError("Распакованные данные слишком велики")
            if len(items) > 120:
                raise UpdateError("В архиве слишком много файлов")
            manifests = [i for i in items if i.filename.endswith("/manifest.json")]
            if len(manifests) != 1:
                raise UpdateError("В архиве отсутствует единственный манифест")
            prefix = manifests[0].filename[:-len("manifest.json")]
            if not re.fullmatch(r"ORBITclip_Patch_v\d+_\d+_\d+/", prefix):
                raise UpdateError("Неверная структура патча")
            data = json.loads(z.read(manifests[0]))
            validate_manifest(data, Path(target).resolve())
            expected = {prefix + "manifest.json"}
            for operation in data["changes"]:
                if operation.get("after") is None:
                    continue
                relative = safe_path(operation["path"])
                entry = prefix + "payload/" + relative.as_posix()
                expected.add(entry)
                try:
                    info = z.getinfo(entry)
                except KeyError as exc:
                    raise UpdateError("В архиве нет модуля: " + str(relative)) from exc
                if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise UpdateError("Недопустимый объект в архиве")
                content = z.read(info)
                if digest(content) != operation["after"]:
                    raise UpdateError("Повреждён файл патча: " + str(relative))
                path = stage / "payload" / Path(*relative.parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            # apply_patch.py from the ZIP is deliberately IGNORED, never invoked.
            (stage / "manifest.json").write_text(json.dumps(data, ensure_ascii=False),
                                                  encoding="utf-8")
            if not expected.issubset({i.filename for i in items}):
                raise UpdateError("Недостающие файлы")
        return stage, data
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def install_staged(stage, target):
    """Transactional installation. Validates again after the GUI closes."""
    stage = Path(stage).resolve()
    target = Path(target).resolve()
    data = validate_manifest(json.loads((stage / "manifest.json").read_text("utf-8")), target)
    for change in data["changes"]:
        if change["after"] is not None:
            relative = safe_path(change["path"])
            payload = stage / "payload" / Path(*relative.parts)
            if not payload.is_file() or digest(payload.read_bytes()) != change["after"]:
                raise UpdateError("Файл в кэше обновления повреждён: " + str(relative))
    backups = target / ".orbitclip_patch_backups"
    if backups.is_symlink():
        raise UpdateError("Резервная папка не должна быть символической ссылкой")
    backup = backups / ("v" + data["from_version"] + "_to_v" + data["to_version"])
    if backup.exists() or backup.is_symlink():
        raise UpdateError("Резервная копия такого обновления уже существует")
    backup.mkdir(parents=True)
    applied = []
    try:
        for x in data["changes"]:
            rel = safe_path(x["path"])
            source = target / Path(*rel.parts)
            if source.exists():
                dest = backup / Path(*rel.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
        for x in data["changes"]:
            rel = safe_path(x["path"])
            dest = target / Path(*rel.parts)
            previous = backup / Path(*rel.parts)
            applied.append((dest, previous))
            if x["after"] is None:
                dest.unlink()
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            mode = stat.S_IMODE(dest.stat().st_mode) if dest.exists() else (
                0o755 if dest.suffix == ".command" else 0o644)
            fd, temporary = tempfile.mkstemp(prefix=".orbit_tmp_", dir=dest.parent)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write((stage / "payload" / Path(*rel.parts)).read_bytes())
                if os.name != "nt":
                    os.chmod(temporary, mode)
                os.replace(temporary, dest)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            if digest(dest.read_bytes()) != x["after"]:
                raise UpdateError("Записанный файл повреждён: " + str(rel))
        if read_version(target) != data["to_version"]:
            raise UpdateError("Версия после установки не совпала")
    except BaseException:
        for dest, previous in reversed(applied):
            if previous.is_file():
                shutil.copy2(previous, dest)
            elif dest.is_file():
                dest.unlink()
        raise
    return data["to_version"]


def _process_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x100000, 0, int(pid))
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def launch_after_exit(stage, target, pid):
    args = [sys.executable, str(Path(__file__).resolve()), "--apply",
            str(stage), "--target", str(target), "--wait-pid", str(pid)]
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


def _write_status(ok, message):
    STATUS_FILE.write_text(json.dumps({"ok": bool(ok), "message": str(message)[:300],
                                        "timestamp": time.time()}, ensure_ascii=False),
                           encoding="utf-8")


def consume_status():
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        STATUS_FILE.unlink(missing_ok=True)
        return data
    except (OSError, ValueError):
        return None


def apply_after_exit(stage, target, pid):
    try:
        until = time.monotonic() + 35
        while _process_alive(pid) and time.monotonic() < until:
            time.sleep(.20)
        if _process_alive(pid):
            raise UpdateError("ORBITclip не завершился; обновление не применено")
        installed = install_staged(stage, target)
        _write_status(True, "ORBITclip обновлён до " + installed)
        # Start through the shared-runtime launcher; never overwrite venv.
        entry = Path(target) / "launcher.py"
        if entry.is_file():
            subprocess.Popen([sys.executable, str(entry)], cwd=target,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=os.name != "nt")
    except Exception as exc:
        _write_status(False, str(exc))
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply")
    parser.add_argument("--target")
    parser.add_argument("--wait-pid", type=int, default=0)
    args = parser.parse_args()
    if args.apply and args.target and args.wait_pid:
        try:
            apply_after_exit(args.apply, args.target, args.wait_pid)
        except Exception as exc:
            with (Path.home() / ".orbitclip_update_error.log").open("a", encoding="utf-8") as log:
                log.write(str(time.time()) + " " + str(exc) + "\n")
            raise SystemExit(1)
