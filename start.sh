#!/bin/bash
# Лаунчер для Linux / Mac (терминал)
# Использование: ./start.sh  или  bash start.sh
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
    curl -LsSf https://astral.sh/uv/install.sh | sh
    UV="$HOME/.local/bin/uv"
fi

if [ ! -f "$UV" ]; then
    echo "[!] Не удалось найти uv. Попробуй: pip install uv"
    exit 1
fi

echo "[✓] uv: $UV"

# ── Запустить (uv скачает Python 3.11 если нужно) ─────────────
export UV_PATH="$UV"
"$UV" run --python 3.11 "$(dirname "$0")/launch.py"
