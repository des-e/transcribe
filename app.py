# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastapi>=0.109.0",
#   "uvicorn[standard]>=0.27.0",
#   "faster-whisper>=1.0.0",
#   "python-multipart>=0.0.9",
#   "mlx-whisper>=0.4.1; sys_platform == 'darwin' and platform_machine == 'arm64'",
# ]
# ///
"""
Транскрибация созвонов — FastAPI + кастомный UI.

Бэкенд:
  - Apple Silicon (M1/M2/M3): mlx-whisper (быстро, через Neural Engine)
  - Всё остальное: faster-whisper (CPU, int8)

Запуск: start.bat (Windows) / start.command (Mac) / ./start.sh (Linux)
Откроется: http://localhost:8000
"""
import os
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import asyncio
import json
import platform
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

# ──────────────────────────────────────────────────────────────────────────────
# Платформа
# ──────────────────────────────────────────────────────────────────────────────

IS_APPLE_SILICON = platform.system() == "Darwin" and platform.machine() == "arm64"

# Имена моделей MLX Community для каждого размера
MLX_MODELS: dict[str, str] = {
    "tiny":   "mlx-community/whisper-tiny-mlx",
    "base":   "mlx-community/whisper-base-mlx",
    "small":  "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large":  "mlx-community/whisper-large-v3-mlx",
}

# ──────────────────────────────────────────────────────────────────────────────
# Конфигурация
# ──────────────────────────────────────────────────────────────────────────────

UPLOADS_DIR = Path(tempfile.gettempdir()) / "bx_transcribe"
UPLOADS_DIR.mkdir(exist_ok=True)

TEMPLATES_DIR = Path(__file__).parent / "templates"

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac", ".wma", ".opus"}

MAX_UPLOAD_MB = 2048  # 2 GB

# Кеш faster-whisper модели (только на не-Apple-Silicon)
_loaded_model: tuple[str, Any] | None = None
_model_lock = threading.Lock()

# Активные транскрибации: file_id → (cancel_event, queue)
_active: dict[str, tuple[threading.Event, asyncio.Queue]] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Предзагрузка модели при старте (только faster-whisper, MLX не нужно)
# ──────────────────────────────────────────────────────────────────────────────

def _preload_model():
    """На не-Apple-Silicon загружает faster-whisper модель в RAM при старте."""
    if IS_APPLE_SILICON:
        return
    global _loaded_model
    try:
        from faster_whisper import WhisperModel
        with _model_lock:
            if _loaded_model is None:
                _loaded_model = ("medium", WhisperModel("medium", device="cpu", compute_type="int8"))
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    cutoff = time.time() - 86_400
    for f in UPLOADS_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
    t = threading.Thread(target=_preload_model, daemon=True)
    t.start()
    yield


app = FastAPI(lifespan=lifespan)


# ──────────────────────────────────────────────────────────────────────────────
# Страница
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/info")
async def info():
    return JSONResponse({"backend": "mlx" if IS_APPLE_SILICON else "cpu"})


# ──────────────────────────────────────────────────────────────────────────────
# Загрузка файла
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix.lower()
    dest = UPLOADS_DIR / f"{file_id}{ext}"

    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                dest.unlink(missing_ok=True)
                return JSONResponse(
                    {"error": f"Файл слишком большой. Максимум {MAX_UPLOAD_MB} MB."},
                    status_code=413,
                )
            f.write(chunk)

    size_mb = size / 1024 / 1024
    return JSONResponse({
        "file_id": file_id,
        "filename": file.filename,
        "size": f"{size_mb:.1f} MB",
        "is_audio": ext in AUDIO_EXTENSIONS,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Отмена транскрибации
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/cancel")
async def cancel_transcription(file_id: str):
    if file_id in _active:
        event, queue = _active[file_id]
        event.set()
        await queue.put({"type": "cancelled"})
        await queue.put(None)
    return JSONResponse({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# Транскрибация (SSE-поток)
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/stream")
async def stream_transcription(
    file_id: str,
    model: str = "medium",
    extract_audio: bool = True,
    language: str = "ru",
):
    files = list(UPLOADS_DIR.glob(f"{file_id}*"))
    if not files:
        async def _err():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Файл не найден'})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    file_path = files[0]

    if file_path.suffix.lower() in AUDIO_EXTENSIONS:
        extract_audio = False

    cancel_event = threading.Event()
    queue: asyncio.Queue = asyncio.Queue()
    _active[file_id] = (cancel_event, queue)
    loop = asyncio.get_running_loop()

    def _run():
        audio_tmp: str | None = None
        lang = None if language == "auto" else language
        t_start = time.time()

        try:
            transcribe_path = str(file_path)

            # ── Извлечь аудио из видео ────────────────────────────────────────
            if extract_audio:
                _put(loop, queue, {"type": "status", "message": "Извлечение аудиодорожки..."})
                tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                audio_tmp = tmp.name
                tmp.close()
                res = subprocess.run(
                    ["ffmpeg", "-y", "-i", transcribe_path,
                     "-vn", "-acodec", "mp3", "-ab", "64k", "-ar", "16000", audio_tmp],
                    capture_output=True,
                )
                if res.returncode != 0:
                    _put(loop, queue, {
                        "type": "error",
                        "message": f"ffmpeg error: {res.stderr.decode()[-300:]}",
                    })
                    return
                transcribe_path = audio_tmp

            if cancel_event.is_set():
                _put(loop, queue, {"type": "cancelled"})
                return

            # ── Выбор бэкенда ─────────────────────────────────────────────────
            if IS_APPLE_SILICON:
                _run_mlx(transcribe_path, model, lang, t_start, loop, queue, cancel_event)
            else:
                _run_faster_whisper(transcribe_path, model, lang, t_start, loop, queue, cancel_event)

        except Exception as e:
            _put(loop, queue, {"type": "error", "message": str(e)})
        finally:
            if audio_tmp:
                Path(audio_tmp).unlink(missing_ok=True)
            file_path.unlink(missing_ok=True)
            _active.pop(file_id, None)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    async def _generate():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Бэкенд: MLX Whisper (Apple Silicon)
# ──────────────────────────────────────────────────────────────────────────────

def _mlx_model_cached(model_name: str) -> bool:
    """Проверяет что MLX модель полностью скачана (проверяет размер blobs)."""
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    repo = f"whisper-{model_name}-mlx" if model_name != "large" else "whisper-large-v3-mlx"
    blobs_dir = hf_home / "hub" / f"models--mlx-community--{repo}" / "blobs"
    if not blobs_dir.exists():
        return False
    total = sum(f.stat().st_size for f in blobs_dir.iterdir() if f.is_file())
    return total > 100 * 1024 * 1024  # хотя бы 100 MB


def _run_mlx(path, model, lang, t_start, loop, queue, cancel_event):
    import mlx_whisper

    mlx_repo = MLX_MODELS.get(model, f"mlx-community/whisper-{model}-mlx")

    cached = _mlx_model_cached(model)
    t_begin = time.time()

    # Периодически обновляем статус — без этого UI выглядит замороженным
    # (MLX возвращает все сегменты разом, без стриминга)
    _timer: list = [None]

    def _tick():
        if cancel_event.is_set():
            return
        elapsed = time.time() - t_begin
        m, s = divmod(int(elapsed), 60)
        tick_str = f"{m}:{s:02d}" if m else f"{s}с"
        if cached:
            msg = f"Транскрибирую... {tick_str}"
        else:
            msg = f"Скачиваю модель «{model}» (~800 MB)... {tick_str}"
        _put(loop, queue, {"type": "status", "message": msg})
        t = threading.Timer(3.0, _tick)
        t.daemon = True
        _timer[0] = t
        t.start()

    _tick()

    result = mlx_whisper.transcribe(
        path,
        path_or_hf_repo=mlx_repo,
        language=lang,
        verbose=False,
    )

    if _timer[0]:
        _timer[0].cancel()

    segments = result.get("segments", [])
    count = 0
    for seg in segments:
        if cancel_event.is_set():
            _put(loop, queue, {"type": "cancelled"})
            return

        count += 1
        elapsed = time.time() - t_start
        speed = f"{seg['end'] / elapsed:.1f}×" if elapsed > 0.5 else ""

        _put(loop, queue, {
            "type":    "segment",
            "start":   _fmt(seg["start"]),
            "end":     _fmt(seg["end"]),
            "start_s": round(seg["start"], 3),
            "end_s":   round(seg["end"], 3),
            "text":    seg["text"].strip(),
            "speed":   speed,
        })

    elapsed = time.time() - t_start
    duration = segments[-1]["end"] if segments else 0
    total_speed = f"{duration / elapsed:.1f}×" if elapsed > 1 else ""
    detected_lang = (result.get("language") or "?").upper()

    _put(loop, queue, {
        "type":        "done",
        "segments":    count,
        "language":    detected_lang,
        "probability": "Apple Silicon",
        "speed":       total_speed,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Бэкенд: faster-whisper (Windows / Linux / Intel Mac)
# ──────────────────────────────────────────────────────────────────────────────

def _run_faster_whisper(path, model, lang, t_start, loop, queue, cancel_event):
    global _loaded_model
    from faster_whisper import WhisperModel

    _put(loop, queue, {"type": "status", "message": f"Загрузка модели «{model}»..."})
    with _model_lock:
        if _loaded_model is None or _loaded_model[0] != model:
            _loaded_model = (model, WhisperModel(model, device="cpu", compute_type="int8"))
        whisper = _loaded_model[1]

    if cancel_event.is_set():
        _put(loop, queue, {"type": "cancelled"})
        return

    _put(loop, queue, {"type": "status", "message": "Транскрибирую..."})
    segments, info = whisper.transcribe(path, language=lang)

    count = 0
    for seg in segments:
        if cancel_event.is_set():
            _put(loop, queue, {"type": "cancelled"})
            return

        count += 1
        elapsed = time.time() - t_start
        speed = f"{seg.end / elapsed:.1f}×" if elapsed > 0.5 else ""

        _put(loop, queue, {
            "type":    "segment",
            "start":   _fmt(seg.start),
            "end":     _fmt(seg.end),
            "start_s": round(seg.start, 3),
            "end_s":   round(seg.end, 3),
            "text":    seg.text.strip(),
            "speed":   speed,
        })

    elapsed = time.time() - t_start
    total_speed = f"{info.duration / elapsed:.1f}×" if elapsed > 1 else ""
    _put(loop, queue, {
        "type":        "done",
        "segments":    count,
        "language":    info.language.upper(),
        "probability": f"{info.language_probability:.0%}",
        "speed":       total_speed,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────────────────────

def _put(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, item: dict) -> None:
    loop.call_soon_threadsafe(queue.put_nowait, item)


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ──────────────────────────────────────────────────────────────────────────────
# Запуск
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)
