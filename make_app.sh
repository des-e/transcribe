#!/bin/bash
# ──────────────────────────────────────────────────────────────
#  Создаёт Transcribe.app — ярлык для запуска одним кликом
#
#  Использование (один раз после клонирования):
#    bash make_app.sh
#
#  Результат: Transcribe.app рядом с этим скриптом.
#  Перетащи его в Dock — запускай одним кликом.
# ──────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/Transcribe.app"

echo ""
echo "  Создаю Transcribe.app..."

rm -rf "$APP_PATH"

# osacompile — встроенный инструмент macOS, компилирует AppleScript в .app
osacompile -o "$APP_PATH" << 'APPLESCRIPT'
-- Папка проекта = папка где лежит Transcribe.app
set appPath to POSIX path of (path to me)
set projectPath to do shell script "dirname " & quoted form of appPath
set startScript to projectPath & "/start.sh"

-- Снять карантин и выставить права
do shell script "chmod +x " & quoted form of startScript
do shell script "xattr -d com.apple.quarantine " & quoted form of startScript & " 2>/dev/null; true"

-- Открыть Terminal и запустить
tell application "Terminal"
    activate
    do script "bash " & quoted form of startScript
end tell
APPLESCRIPT

if [ $? -eq 0 ]; then
    xattr -cr "$APP_PATH" 2>/dev/null
    echo "  [✓] Готово!"
    echo ""
    echo "  Transcribe.app создан рядом со скриптом."
    echo "  Перетащи его в Dock — и запускай одним кликом."
    echo ""
else
    echo "  [!] Ошибка. Убедись что запускаешь на Mac."
fi
