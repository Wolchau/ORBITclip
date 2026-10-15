#!/usr/bin/env python3
"""Verify system-wide Ctrl+wheel capture independently of ORBITclip / Qt."""
import queue
import time
import platform
import argparse
from orbit_switcher import ClipboardWheel


def main():
    parser=argparse.ArgumentParser(description='Диагностика Ctrl+колесо')
    parser.add_argument('--simulate',action='store_true',help='проверка очереди без глобального перехвата')
    opts=parser.parse_args()
    hook=ClipboardWheel()
    if opts.simulate:
        hook.simulate_one_step()
        print('Тест очереди событий:',hook.events.get_nowait())
        print('Диагностика:',hook.diagnostics())
        return 0
    ok=hook.start()
    print('ORBITclip: диагностика Ctrl + колесо')
    print('Система:',platform.platform())
    print('Обработчик:',hook.backend or 'не запущен')
    print('Статус:', 'запущен' if ok else 'ОШИБКА')
    if hook.error:print('Подробнее:',hook.error)
    if not ok:
        print('macOS: проверь разрешения Универсальный доступ и Мониторинг ввода для Python/Terminal.')
        return 1
    print('\nВ течение 12 секунд удерживай Ctrl и прокрути колесо над ДРУГИМ приложением.')
    print('Затем нажми Alt для переключения категории и отпусти Ctrl для копирования.')
    seen=[]
    end=time.monotonic()+12
    try:
        while time.monotonic()<end:
            try:
                ev=hook.events.get(timeout=.25)
                seen.append(ev)
                print('EVENT:',ev)
            except queue.Empty:
                pass
    finally:
        print('Счётчики:',hook.diagnostics())
        hook.stop()
    if not any(tag=='move' for tag,_ in seen):
        print('\nСобытия прокрутки не получены. Если raw_wheel=0 — нет захвата колеса;')
        print('если raw_wheel>0, но ctrl_wheel=0 — не обнаружена клавиша Ctrl.')
        print('Если moves>0, но нет облачка в приложении — проблема Qt/UI.')
        print('Проверь разрешения системы,')
        print('а на macOS — параметр масштабирования Control+scroll в настройках Универсального доступа.')
        return 2
    if not any(tag=='commit' for tag,_ in seen):
        print('\nПрокрутка получена, но событие отпускания Ctrl не зарегистрировано.')
        return 3
    print('\nСобытия Ctrl+колесо и отпускания Ctrl получены успешно.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
