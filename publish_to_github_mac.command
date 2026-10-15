#!/bin/bash
cd "$(dirname "$0")" || exit 1
python3 publish_first_time.py
result=$?
if [ "$result" -ne 0 ]; then echo 'Проверь ошибку выше'; read -r -p 'Enter для закрытия... ' _; fi
exit "$result"
