#!/bin/bash
# ──────────────────────────────────────────────────────────────
#  Transcribe — лаунчер для Mac
#
#  Первый запуск: правый клик → Открыть → Открыть
#  Далее: двойной клик
# ──────────────────────────────────────────────────────────────

# Держать окно открытым при любом завершении
trap 'echo ""; read -r -p "Нажми Enter для закрытия..." _' EXIT

# Перейти в папку со скриптом
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || { echo "[!] Не удалось открыть папку: $SCRIPT_DIR"; exit 1; }

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║   Transcribe — запуск            ║"
echo "  ╚══════════════════════════════════╝"
echo ""
echo "  Папка: $SCRIPT_DIR"
echo ""

# ── Найти uv ──────────────────────────────────────────────────
UV=""
if command -v uv &>/dev/null; then
    UV="$(command -v uv)"
elif [ -f "$HOME/.local/bin/uv" ]; then
    UV="$HOME/.local/bin/uv"
elif [ -f "$HOME/.cargo/bin/uv" ]; then
    UV="$HOME/.cargo/bin/uv"
fi

# ── Установить uv если не найден ──────────────────────────────
if [ -z "$UV" ]; then
    echo "[→] Устанавливаю uv (менеджер пакетов)..."
    if ! command -v curl &>/dev/null; then
        echo "[!] curl не найден. Установи Homebrew: https://brew.sh"
        exit 1
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Перезагрузить PATH после установки
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    UV="$HOME/.local/bin/uv"
fi

if [ ! -f "$UV" ]; then
    echo "[!] uv не найден после установки."
    echo "    Закрой окно и запусти start.command снова."
    exit 1
fi

echo "[✓] uv: $UV"

# ── Запустить launch.py
#    uv сам скачает Python 3.11 если его нет
# ─────────────────────────────────────────────────────────────
export UV_PATH="$UV"
echo "[→] Запускаю..."
echo ""

# Отключаем trap перед запуском — сервер сам держит окно открытым
trap - EXIT

"$UV" run --python 3.11 "$SCRIPT_DIR/launch.py"
EXIT_CODE=$?

# Если сервер завершился — показать сообщение и подождать
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "Сервер остановлен."
else
    echo "[!] Завершено с ошибкой (код $EXIT_CODE)"
fi
read -r -p "Нажми Enter для закрытия..." _
