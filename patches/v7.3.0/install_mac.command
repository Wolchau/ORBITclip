#!/bin/zsh
cd "$(dirname "$0")"
python3 ./apply_patch.py "$@"
status=$?
echo ""
if [[ $status -eq 0 ]]; then
  echo "Готово. Можно закрыть Terminal."
else
  echo "Патч не применён. Прочитай ошибку выше."
fi
echo "Нажми Enter, чтобы закрыть окно..."
read -r answer
exit $status
