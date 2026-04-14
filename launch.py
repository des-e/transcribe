"""
Предстартовая проверка — запускается через:
  uv run --python 3.11 launch.py

Что делает:
  1. Проверяет обновления из репозитория
  2. Проверяет / предлагает установить ffmpeg
  3. Запускает app.py через uv run
     (uv сам управляет зависимостями из заголовка app.py)
"""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE   = Path(__file__).parent
SYSTEM = platform.system()  # "Windows", "Darwin", "Linux"

# Репозиторий для автообновления
_ro = "https://github.com/des-e/transcribe.git"


# ──────────────────────────────────────────────────────────────────────────────
# Найти uv (передаётся из shell-скрипта через UV_PATH)
# ──────────────────────────────────────────────────────────────────────────────

def find_uv() -> str | None:
    uv = os.environ.get("UV_PATH")
    if uv and Path(uv).exists():
        return uv
    uv = shutil.which("uv")
    if uv:
        return uv
    home = Path.home()
    for c in [
        home / ".local/bin/uv",
        home / ".cargo/bin/uv",
        home / "AppData/Roaming/uv/bin/uv.exe",
        home / ".local/bin/uv.exe",
    ]:
        if c.exists():
            return str(c)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Автообновление
# ──────────────────────────────────────────────────────────────────────────────

def check_for_updates():
    """Тихо проверяет обновления. При любой ошибке — пропускает."""

    # git должен быть установлен
    if not shutil.which("git"):
        return

    # Должны быть в git-репозитории
    r = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=HERE, capture_output=True,
    )
    if r.returncode != 0:
        return

    print("[→] Проверяю обновления...")

    try:
        # Fetch напрямую по URL — не трогаем remote origin (чтобы не сломать push)
        fetch = subprocess.run(
            ["git", "fetch", _ro, "master:refs/remotes/origin/master", "--quiet"],
            cwd=HERE, capture_output=True, timeout=8,
        )
        if fetch.returncode != 0:
            print("[~] Нет подключения — пропускаю проверку обновлений")
            return

        # Сравниваем локальный и удалённый коммиты
        local = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=HERE, capture_output=True, text=True,
        ).stdout.strip()

        remote = subprocess.run(
            ["git", "rev-parse", "origin/master"],
            cwd=HERE, capture_output=True, text=True,
        ).stdout.strip()

        if local == remote:
            print("[✓] Последняя версия")
            return

        # Есть обновления — получаем список изменённых файлов
        changed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "origin/master"],
            cwd=HERE, capture_output=True, text=True,
        ).stdout.strip()

        print(f"[→] Найдено обновление, применяю...")

        pull = subprocess.run(
            ["git", "pull", "origin", "master", "--quiet"],
            cwd=HERE, capture_output=True, text=True,
        )

        if pull.returncode != 0:
            print("[~] Не удалось обновить, запускаю текущую версию")
            return

        print("[✓] Обновление применено!")

        # Если обновился сам launch.py — перезапускаем процесс
        if "launch.py" in changed:
            print("[→] Перезапускаю...")
            subprocess.Popen([sys.executable] + sys.argv)
            sys.exit(0)

    except subprocess.TimeoutExpired:
        print("[~] Таймаут соединения — пропускаю проверку обновлений")
    except Exception:
        pass  # Никогда не блокируем запуск из-за обновления


# ──────────────────────────────────────────────────────────────────────────────
# ffmpeg
# ──────────────────────────────────────────────────────────────────────────────

def ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def handle_ffmpeg():
    if ffmpeg_available():
        print("[✓] ffmpeg найден")
        return

    print()
    print("[!] ffmpeg не найден.")
    print("    ffmpeg нужен для видеофайлов (MP4, MKV, MOV, AVI).")
    print("    Без него работают только аудиофайлы (MP3, WAV, M4A).")
    print()

    if SYSTEM == "Windows":
        print("    Установка через winget:")
        print("      winget install Gyan.FFmpeg")
        print()
        if input("    Установить сейчас? [y/N]: ").strip().lower() == "y":
            result = subprocess.run(["winget", "install", "--id", "Gyan.FFmpeg", "-e"])
            if result.returncode == 0:
                print("\n[✓] ffmpeg установлен.")
                print("    Перезапусти start.bat — ffmpeg появится в PATH после перезапуска.")
            else:
                print("\n[!] Не удалось установить автоматически.")
                print("    Установи вручную: https://ffmpeg.org/download.html")
            _pause_exit()

    elif SYSTEM == "Darwin":
        print("    Вариант 1 — Homebrew:")
        print("      brew install ffmpeg")
        print()
        print("    Вариант 2 — готовый бинарник (без Homebrew):")
        print("      https://evermeet.cx/ffmpeg/  → скачать → распаковать → переместить в /usr/local/bin/")
        print()
        brew_ok = subprocess.run(["brew", "--version"], capture_output=True).returncode == 0
        if brew_ok:
            if input("    Установить через Homebrew сейчас? [y/N]: ").strip().lower() == "y":
                if subprocess.run(["brew", "install", "ffmpeg"]).returncode == 0:
                    print("[✓] ffmpeg установлен")
                    return
                print("[!] Не удалось. Попробуй вручную.")
        else:
            print("    Homebrew не найден.")
            print("    Быстрая установка: https://brew.sh")
            print("    Или скачай бинарник: https://evermeet.cx/ffmpeg/")

    else:  # Linux
        print("      sudo apt install ffmpeg        # Ubuntu / Debian")
        print("      sudo dnf install ffmpeg        # Fedora")
        print("      sudo pacman -S ffmpeg          # Arch")

    print()
    if input("    Продолжить без ffmpeg (только аудиофайлы)? [y/N]: ").strip().lower() != "y":
        print("Запусти снова после установки ffmpeg.")
        _pause_exit()
    print("[~] Продолжаем без ffmpeg — видеофайлы недоступны")


# ──────────────────────────────────────────────────────────────────────────────
# Запуск app.py через uv
# ──────────────────────────────────────────────────────────────────────────────

def run_app():
    uv = find_uv()
    if not uv:
        print("[!] uv не найден. Запусти через start.bat или start.command")
        _pause_exit()

    print()
    print("=" * 52)
    print("   Transcribe запущен → http://localhost:8000")
    print("   Для остановки нажми Ctrl+C")
    print("=" * 52)
    print()

    result = subprocess.run(
        [uv, "run", "--python", "3.11", str(HERE / "app.py")]
    )
    sys.exit(result.returncode)


# ──────────────────────────────────────────────────────────────────────────────

def _pause_exit():
    input("\nНажми Enter для выхода...")
    sys.exit(1)


if __name__ == "__main__":
    print()
    print("  ╔══════════════════════════════════╗")
    print("  ║   Transcribe — Инициализация     ║")
    print("  ╚══════════════════════════════════╝")
    print()
    print(f"[✓] Python {sys.version.split()[0]}")
    check_for_updates()
    handle_ffmpeg()
    run_app()
