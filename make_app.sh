#!/bin/bash
# ──────────────────────────────────────────────────────────────
#  Создаёт Transcribe.app — ярлык для запуска одним кликом
#
#  Использование (один раз после клонирования):
#    bash make_app.sh
#
#  Результат: Transcribe.app в папке проекта.
#  Перетащи его в Dock — и запускай одним кликом навсегда.
# ──────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/Transcribe.app"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║   Создаю Transcribe.app          ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# Убрать старую версию
rm -rf "$APP_PATH"

# Создать структуру .app
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# ── Info.plist ────────────────────────────────────────────────
cat > "$APP_PATH/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>    <string>Transcribe</string>
    <key>CFBundleIdentifier</key>    <string>com.transcribe.launcher</string>
    <key>CFBundleName</key>          <string>Transcribe</string>
    <key>CFBundleDisplayName</key>   <string>Transcribe</string>
    <key>CFBundleVersion</key>       <string>1.0</string>
    <key>CFBundlePackageType</key>   <string>APPL</string>
    <key>CFBundleSignature</key>     <string>????</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
PLIST

# ── Исполняемый файл внутри .app ──────────────────────────────
# Находит папку проекта относительно себя (3 уровня вверх от Contents/MacOS/)
# и открывает Terminal с запуском start.sh
cat > "$APP_PATH/Contents/MacOS/Transcribe" << 'LAUNCHER'
#!/bin/bash
PROJECT="$(cd "$(dirname "$0")/../../.." && pwd)"
START="$PROJECT/start.sh"

if [ ! -f "$START" ]; then
    osascript -e "display alert \"Transcribe\" message \"Не найден start.sh в папке:\n$PROJECT\" as warning"
    exit 1
fi

# Снять карантин и выставить права
xattr -d com.apple.quarantine "$START" 2>/dev/null
chmod +x "$START"

# Открыть Terminal и запустить
osascript << OSASCRIPT
tell application "Terminal"
    activate
    do script "bash '$START'"
end tell
OSASCRIPT
LAUNCHER

chmod +x "$APP_PATH/Contents/MacOS/Transcribe"

# Снять карантин с самого .app
xattr -cr "$APP_PATH" 2>/dev/null

echo "[✓] Готово!"
echo ""
echo "  Transcribe.app создан в папке проекта."
echo ""
echo "  Что дальше:"
echo "  1. Перетащи Transcribe.app в Dock — запуск одним кликом"
echo "  2. Или двойной клик прямо из Finder в любой момент"
echo ""
echo "  При первом запуске macOS спросит разрешение — нажми 'Открыть'"
echo ""
