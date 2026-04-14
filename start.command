#!/bin/bash
# ──────────────────────────────────────────────────────────────
#  Transcribe — лаунчер для Mac
#
#  Первый запуск: правый клик → Открыть → Открыть
#  Далее: двойной клик
#
#  Не требует установленного Python — uv скачает сам.
# ──────────────────────────────────────────────────────────────
cd "$(dirname "$0")"

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
    if command -v curl &>/dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        # curl нет — предложить Homebrew
        osascript -e 'display alert "Нужен curl или Homebrew" message "Установи Homebrew с brew.sh, затем запусти снова." as warning'
        echo "[!] Установи Homebrew: https://brew.sh"
        read -p "Нажми Enter для закрытия..."
        exit 1
    fi
    UV="$HOME/.local/bin/uv"
fi

if [ ! -f "$UV" ]; then
    echo "[!] Не удалось найти uv после установки."
    echo "    Закрой это окно и запусти start.command снова."
    read -p "Нажми Enter для закрытия..."
    exit 1
fi

echo "[✓] uv: $UV"

# ── Запустить launch.py
#    uv сам скачает Python 3.11 если его нет на компьютере
# ─────────────────────────────────────────────────────────────
export UV_PATH="$UV"
"$UV" run --python 3.11 "$(dirname "$0")/launch.py"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    read -p "Нажми Enter для закрытия..."
fi
