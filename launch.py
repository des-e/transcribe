"""
Предстартовая проверка — запускается через:
  uv run --python 3.11 launch.py

Что делает:
  1. Проверяет обновления из репозитория
  2. Запускает app.py через uv run
     (uv сам управляет зависимостями из заголовка app.py)
"""
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE   = Path(__file__).parent
SYSTEM = platform.system()  # "Windows", "Darwin", "Linux"

# Зеркало HuggingFace — ускоряет скачивание моделей в СНГ
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

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

    # Проверяем что git реально работает (xcrun может быть сломан)
    try:
        test = subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        if test.returncode != 0:
            print("[~] git недоступен — пропускаю проверку обновлений")
            return
    except Exception:
        print("[~] git недоступен — пропускаю проверку обновлений")
        return

    # Должны быть в git-репозитории
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=HERE, capture_output=True,
        )
        if r.returncode != 0:
            return
    except Exception:
        return

    # Обновляем только master — на feature-ветках не трогаем
    current_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=HERE, capture_output=True, text=True,
    ).stdout.strip()
    if current_branch != "master":
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

        print("[→] Найдено обновление, применяю...")

        # reset --hard надёжнее чем pull: не требует чистого рабочего дерева
        # и не зависит от настроек remote origin
        reset = subprocess.run(
            ["git", "reset", "--hard", "origin/master"],
            cwd=HERE, capture_output=True, text=True,
        )

        if reset.returncode != 0:
            print(f"[~] Не удалось обновить: {reset.stderr.strip()}")
            print("    Запускаю текущую версию.")
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
# Предзагрузка модели Whisper
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "medium"
IS_APPLE_SILICON = SYSTEM == "Darwin" and platform.machine() == "arm64"

# Имена MLX-моделей (те же что в app.py)
MLX_MODELS = {
    "tiny":   "mlx-community/whisper-tiny-mlx",
    "base":   "mlx-community/whisper-base-mlx",
    "small":  "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large":  "mlx-community/whisper-large-v3-mlx",
}


def model_is_cached(model_name: str) -> bool:
    """Проверяет, полностью ли скачана модель.

    Два критерия:
    - refs/main существует (HuggingFace записывает его только после полной загрузки)
    - суммарный размер blobs > 100 MB (защита от пустых/частичных загрузок)
    """
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    hub = hf_home / "hub"
    if IS_APPLE_SILICON:
        repo = f"whisper-{model_name}-mlx" if model_name != "large" else "whisper-large-v3-mlx"
        model_dir = hub / f"models--mlx-community--{repo}"
    else:
        model_dir = hub / f"models--Systran--faster-whisper-{model_name}"

    if not model_dir.exists():
        return False

    # refs/main — финальный маркер успешно завершённой загрузки HuggingFace
    if not (model_dir / "refs" / "main").exists():
        return False

    blobs = model_dir / "blobs"
    if not blobs.exists():
        return False
    try:
        total = sum(f.stat().st_size for f in blobs.iterdir() if f.is_file())
    except OSError:
        return False
    return total > 100 * 1024 * 1024


def warm_up_model():
    """Скачивает модель при первом запуске, чтобы первая транскрибация не висела."""
    try:
        _warm_up_model()
    except Exception as e:
        print(f"[~] Не удалось предзагрузить модель ({e})")
        print("    Модель скачается при первой транскрибации.")


def _warm_up_model():
    if model_is_cached(DEFAULT_MODEL):
        backend = "MLX" if IS_APPLE_SILICON else "faster-whisper"
        print(f"[✓] Модель «{DEFAULT_MODEL}» ({backend}) уже загружена")
        return

    uv = find_uv()
    if not uv:
        print("[~] uv не найден — пропускаю предзагрузку модели")
        return

    # Проверяем свободное место перед загрузкой
    required_gb = 1.0 if IS_APPLE_SILICON else 2.0
    try:
        free_gb = shutil.disk_usage(Path.home()).free / (1024 ** 3)
        if free_gb < required_gb:
            print()
            print(f"[!] Мало места на диске: {free_gb:.1f} ГБ свободно, нужно ~{required_gb:.0f} ГБ.")
            print("    Освободи место и запусти снова.")
            print()
            if input("    Пропустить предзагрузку? [y/N]: ").strip().lower() != "y":
                _pause_exit()
            print("[~] Пропускаю — модель скачается при первой транскрибации.")
            return
    except OSError:
        pass  # Не можем проверить — продолжаем

    print()
    if IS_APPLE_SILICON:
        mlx_repo = MLX_MODELS.get(DEFAULT_MODEL, f"mlx-community/whisper-{DEFAULT_MODEL}-mlx")
        print(f"[→] Скачиваю модель «{DEFAULT_MODEL}» (MLX, Apple Silicon)...")
        print("    Это нужно сделать один раз. Дальнейшие запуски мгновенные.")
        print()
        script = (
            f"from huggingface_hub import snapshot_download; "
            f"snapshot_download('{mlx_repo}'); "
            f"print('[✓] MLX модель загружена!')"
        )
    else:
        print(f"[→] Скачиваю модель «{DEFAULT_MODEL}» (~1.5 GB)...")
        print("    Это нужно сделать один раз. Дальнейшие запуски мгновенные.")
        print()
        script = (
            f"from faster_whisper import WhisperModel; "
            f"WhisperModel('{DEFAULT_MODEL}', device='cpu', compute_type='int8'); "
            f"print('[✓] Модель загружена!')"
        )

    with_pkg = "huggingface-hub" if IS_APPLE_SILICON else "faster-whisper"
    result = subprocess.run(
        [uv, "run", "--python", "3.11", "--with", with_pkg, "python", "-c", script],
        cwd=HERE,
    )

    if result.returncode != 0:
        print("[~] Не удалось скачать модель — скачается при первой транскрибации.")
    print()


# ──────────────────────────────────────────────────────────────────────────────
# Проверка порта
# ──────────────────────────────────────────────────────────────────────────────

def _port_free(port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def handle_port():
    if _port_free():
        return
    print()
    print("[!] Порт 8000 занят — возможно, Transcribe уже запущен в другом окне.")
    print()
    if SYSTEM == "Windows":
        print("    Найти PID:   netstat -ano | findstr :8000")
        print("    Завершить:   taskkill /PID <номер> /F")
    else:
        print("    Завершить:   kill -9 $(lsof -t -i :8000)")
    print()
    if input("    Запустить всё равно? [y/N]: ").strip().lower() != "y":
        _pause_exit()


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

    cmd = [uv, "run", "--python", "3.11", str(HERE / "app.py")]

    # На Mac: caffeinate не даёт системе уходить в сон во время транскрибации
    if SYSTEM == "Darwin" and shutil.which("caffeinate"):
        print("[✓] Режим без сна активен (caffeinate)")
        print()
        cmd = ["caffeinate", "-i"] + cmd

    result = subprocess.run(cmd)
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
    warm_up_model()
    handle_port()
    run_app()
