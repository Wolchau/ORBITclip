# ORBITclip

**Desktop clipboard manager, encrypted device messaging, shared workspaces and OCR.**

Текущая версия клиента: **7.2.2**. Приватный репозиторий проекта. Сервер релея — [Wolchau/kinetic-relay](https://github.com/Wolchau/kinetic-relay).

## Первичная загрузка исходников

Репозиторий создан; полная кодовая база подготовлена к первой загрузке в ZIP **ORBITclip_GitHub_Initial_Publish_v7_2_2.zip**.

1. Распакуй этот ZIP на Windows или macOS.
2. Убедись, что установлен Git и настроен вход в GitHub (можно через GitHub Desktop).
3. Запусти `publish_to_github_windows.bat` либо `publish_to_github_mac.command`.
4. Скрипт проверит удалённую ветку, отправит исходники в `main` без force-push, а GitHub Actions соберёт ZIP релиза `v7.2.2`.

После первичной загрузки разработка ведётся **только в ветках `feature/*` и `fix/*` через Pull Requests**. В следующих чатах проекта использовать актуальную версию из этого репозитория, а не старые ZIP.

## Токен Render — временное тестовое исключение

По решению владельца **общий тестовый токен хранится в `client_defaults.json`**, который будет загружен вместе с кодом. Не публикуй репозиторий и релизы открыто. Перед production необходимо **сменить токен на Render и очистить его из истории Git, тегов и релизных архивов**.

## Планируемая структура

- `orbitclip.py` — интерфейс PySide6.
- `orbit_*.py`, `kinetic_*.py` — функции клиента, шифрование, сетевые протоколы.
- `assets/` — иконки и ресурсы.
- `patches/v7.2.2/` — установочный патч с резервным копированием.
- `docs/CONTRIBUTING.md` — порядок работы из разных чатов.
- `.github/workflows/` — CI и публикация GitHub Release.
