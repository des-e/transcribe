#!/bin/bash
# ──────────────────────────────────────────────────────────────
#  Transcribe — запуск из терминала (Mac / Linux)
#
#  Mac:   двойной клик → используй start.command
#         из терминала → bash start.sh
#
#  Linux: bash start.sh
# ──────────────────────────────────────────────────────────────

# Держать окно открытым при любом завершении
trap 'echo ""; read -r -p "Нажми Enter для закрытия..." _' EXIT

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || { echo "[!] Не удалось открыть папку: $SCRIPT_DIR"; exit 1; }

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║   Transcribe — запуск            ║"
echo "  ╚══════════════════════════════════╝"
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
    echo "[→] Устанавливаю uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    UV="$HOME/.local/bin/uv"
fi

if [ ! -f "$UV" ]; then
    echo "[!] uv не найден. Установи вручную: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "[✓] uv найден"

# ── Запустить (uv скачает Python 3.11 если нужно) ─────────────
trap - EXIT
export UV_PATH="$UV"
"$UV" run --python 3.11 "$SCRIPT_DIR/launch.py"

echo ""
read -r -p "Нажми Enter для закрытия..." _
