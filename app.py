# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastapi>=0.109.0",
#   "uvicorn[standard]>=0.27.0",
#   "faster-whisper>=1.0.0",
#   "python-multipart>=0.0.9",
# ]
# ///
"""
Транскрибация созвонов — FastAPI + кастомный UI.

Запуск: start.bat (Windows) / start.command (Mac) / ./start.sh (Linux)
Откроется: http://localhost:8000
"""
import os
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import asyncio
import json
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

# ──────────────────────────────────────────────────────────────────────────────
# Конфигурация
# ──────────────────────────────────────────────────────────────────────────────

UPLOADS_DIR = Path(tempfile.gettempdir()) / "bx_transcribe"
UPLOADS_DIR.mkdir(exist_ok=True)

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Расширения, для которых ffmpeg не нужен
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac", ".wma", ".opus"}

executor = ThreadPoolExecutor(max_workers=2)

# Кешируем только одну модель — при смене модели старая выгружается
_loaded_model: tuple[str, Any] | None = None
_model_lock = threading.Lock()

# Флаги отмены: file_id → Event
_cancel_flags: dict[str, threading.Event] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Жизненный цикл приложения
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: удалить загруженные файлы старше 24 часов
    cutoff = time.time() - 86_400
    for f in UPLOADS_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
    yield


app = FastAPI(lifespan=lifespan)


# ──────────────────────────────────────────────────────────────────────────────
# Страница
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Загрузка файла
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix.lower()
    dest = UPLOADS_DIR / f"{file_id}{ext}"
    content = await file.read()
    dest.write_bytes(content)
    size_mb = len(content) / 1024 / 1024
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
    if file_id in _cancel_flags:
        _cancel_flags[file_id].set()
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

    # Для аудиофайлов ffmpeg не нужен — пропускаем независимо от параметра
    if file_path.suffix.lower() in AUDIO_EXTENSIONS:
        extract_audio = False

    cancel_event = threading.Event()
    _cancel_flags[file_id] = cancel_event

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _run():
        global _loaded_model
        audio_tmp: str | None = None
        lang = None if language == "auto" else language
        t_start = time.time()

        try:
            from faster_whisper import WhisperModel

            transcribe_path = str(file_path)

            # Извлечь аудио из видео
            if extract_audio:
                _put(loop, queue, {"type": "status", "message": "Извлечение аудиодорожки..."})
                tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                audio_tmp = tmp.name
                tmp.close()
                cmd = [
                    "ffmpeg", "-y", "-i", transcribe_path,
                    "-vn", "-acodec", "mp3", "-ab", "64k", "-ar", "16000",
                    audio_tmp,
                ]
                res = subprocess.run(cmd, capture_output=True)
                if res.returncode != 0:
                    _put(loop, queue, {
                        "type": "error",
                        "message": f"ffmpeg error: {res.stderr.decode()[-300:]}",
                    })
                    return
                transcribe_path = audio_tmp

            # Загрузить модель (держим только одну в памяти)
            _put(loop, queue, {"type": "status", "message": f"Загрузка модели «{model}»..."})
            with _model_lock:
                if _loaded_model is None or _loaded_model[0] != model:
                    _loaded_model = (model, WhisperModel(model, device="cpu", compute_type="int8"))
                whisper = _loaded_model[1]

            if cancel_event.is_set():
                _put(loop, queue, {"type": "cancelled"})
                return

            # Транскрибировать
            _put(loop, queue, {"type": "status", "message": "Транскрибирую..."})
            segments, info = whisper.transcribe(transcribe_path, language=lang)

            count = 0
            for seg in segments:
                if cancel_event.is_set():
                    _put(loop, queue, {"type": "cancelled"})
                    return

                count += 1
                elapsed = time.time() - t_start
                speed = f"{seg.end / elapsed:.1f}×" if elapsed > 0.5 else ""

                _put(loop, queue, {
                    "type": "segment",
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

        except Exception as e:
            _put(loop, queue, {"type": "error", "message": str(e)})
        finally:
            if audio_tmp:
                Path(audio_tmp).unlink(missing_ok=True)
            file_path.unlink(missing_ok=True)  # удалить загруженный файл
            _cancel_flags.pop(file_id, None)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(executor, _run)

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
    webbrowser.open("http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
