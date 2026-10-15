#!/usr/bin/env python3
"""One-time safe, non-force push of the full ORBITclip 7.2.2 source tree.

Requires Git installed and GitHub credentials configured in Git Credential Manager.
Works when remote has only the expected initial placeholder/Docs/Actions bootstrap.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REMOTE = 'https://github.com/Wolchau/ORBITclip.git'

def git(*args: str, capture=False):
    command=['git','-C',str(ROOT),*args]
    if capture:
        return subprocess.check_output(command, text=True).strip()
    subprocess.run(command,check=True)


def main() -> int:
    print('ORBITclip - первая публикация исходников в GitHub')
    print('Цель:', REMOTE)
    print('Токен Render в client_defaults.json: только для закрытого тестового репозитория.')
    if not (ROOT/'orbitclip.py').is_file() or not (ROOT/'orbit_version.py').is_file():
        print('ОШИБКА: скрипт нужно запускать из полного набора исходников.')
        return 2
    try:
        subprocess.run(['git','--version'],check=True)
        if not (ROOT/'.git').exists():
            git('init','-b','main')
        git('config','user.name','Wolchau')
        git('config','user.email','51812968+Wolchau@users.noreply.github.com')
        try:
            configured=git('remote','get-url','origin',capture=True)
            if configured.rstrip('/') != REMOTE.rstrip('/'):
                print('ОШИБКА: в папке настроен другой origin:',configured)
                return 2
        except subprocess.CalledProcessError:
            git('remote','add','origin',REMOTE)
        # Read remote BEFORE creating a local commit to avoid touching unexpected projects.
        git('fetch','origin','main')
        remote_files=git('ls-tree','-r','--name-only','FETCH_HEAD',capture=True).splitlines()
        allowed={
            'README.md','.github/workflows/ci.yml','.github/workflows/release.yml',
            'docs/CONTRIBUTING.md','docs/INITIAL_UPLOAD.md'
        }
        unexpected=set(remote_files)-allowed
        if unexpected:
            print('ОШИБКА: удалённая main уже содержит проектные файлы:',', '.join(sorted(unexpected)[:8]))
            print('Остановка без перезаписи. Попроси проверить новую версию репозитория.')
            return 2
        # Safe against running from an old checkout with uncommitted work.
        git('add','-A')
        state=git('status','--porcelain',capture=True)
        if state:
            git('commit','-m','Bootstrap ORBITclip 7.2.2 from verified client and installer patch')
        git('branch','-M','main')
        # Repository was just created; keep the initial remote commit in history without
        # discarding any unrelated remote files (checked against a strict allowlist above).
        local=git('rev-parse','HEAD',capture=True)
        remote=git('rev-parse','FETCH_HEAD',capture=True)
        ancestry=subprocess.run(['git','-C',str(ROOT),'merge-base','--is-ancestor',remote,local],check=False)
        if ancestry.returncode:
            git('merge','--allow-unrelated-histories','-s','ours','--no-edit',remote,
                '-m','Attach ORBITclip sources to initialized GitHub repository')
        git('push','-u','origin','main')
        print('\nГОТОВО: https://github.com/Wolchau/ORBITclip')
        print('GitHub Actions должен автоматически создать тестовый релиз v7.2.2.')
        return 0
    except FileNotFoundError:
        print('ОШИБКА: Git не установлен. Установи Git for Windows или Xcode Command Line Tools.')
    except subprocess.CalledProcessError as exc:
        print('Git завершился с ошибкой:',exc)
        print('Если это ошибка авторизации, войди в GitHub Desktop либо настрой Git Credential Manager.')
    return 1

if __name__=='__main__':
    sys.exit(main())
