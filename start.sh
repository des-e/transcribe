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

# ── Проверка git ──────────────────────────────────────────────────────────────
# Тестируем git напрямую — если xcrun повреждён, git падает с ошибкой архитектуры
if command -v git &>/dev/null; then
    if ! git --version &>/dev/null 2>&1; then
        echo ""
        echo "  [!] git не работает."
        echo "      Вероятная причина: Xcode Command Line Tools несовместимы с архитектурой (Intel → M-чип)."
        echo ""
        echo "  ── Исправление ────────────────────────────────────────────"
        echo ""
        echo "    sudo rm -rf /Library/Developer/CommandLineTools"
        echo "    xcode-select --install"
        echo ""
        echo "  После установки запусти start.sh снова."
        echo ""
        echo "  ── Альтернатива (без git) ─────────────────────────────────"
        echo ""
        echo "  Скачай архив и распакуй вручную:"
        echo "    https://github.com/des-e/transcribe/archive/refs/heads/master.zip"
        echo ""
        read -r -p "Нажми Enter для закрытия..." _
        exit 1
    fi
fi

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
