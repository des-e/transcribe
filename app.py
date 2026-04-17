# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastapi>=0.109.0",
#   "uvicorn[standard]>=0.27.0",
#   "faster-whisper>=1.0.0",
#   "python-multipart>=0.0.9",
#   "mlx-whisper>=0.4.1; sys_platform == 'darwin' and platform_machine == 'arm64'",
#   "imageio-ffmpeg>=0.4.9",
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
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_VERBOSITY", "warning")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import asyncio
import json
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import uvicorn
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

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

try:
    UPLOADS_DIR = Path(tempfile.gettempdir()) / "bx_transcribe"
    UPLOADS_DIR.mkdir(exist_ok=True)
except OSError:
    # Fallback: папка рядом со скриптом (если /tmp недоступен)
    UPLOADS_DIR = Path(__file__).parent / "_uploads"
    UPLOADS_DIR.mkdir(exist_ok=True)

TEMPLATES_DIR = Path(__file__).parent / "templates"
HISTORY_DIR   = Path(__file__).parent / "history"
HISTORY_DIR.mkdir(exist_ok=True)

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac", ".wma", ".opus"}

MAX_UPLOAD_MB = 4096  # 4 GB

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
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


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
# Аудиоплеер
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/audio/{file_id}")
async def get_audio(file_id: str):
    """Отдаёт аудиофайл для плеера. Поддерживает Range-запросы (нужно для seek)."""
    for pattern in [f"{file_id}_audio.*", f"{file_id}.*"]:
        files = list(UPLOADS_DIR.glob(pattern))
        if files:
            return FileResponse(str(files[0]))
    return JSONResponse({"error": "not found"}, status_code=404)


@app.post("/clear/{file_id}")
async def clear_file(file_id: str):
    """Удаляет файлы транскрибации по запросу фронтенда."""
    for pattern in [f"{file_id}_audio.*", f"{file_id}.*"]:
        for f in UPLOADS_DIR.glob(pattern):
            f.unlink(missing_ok=True)
    return JSONResponse({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# Транскрибация (SSE-поток)
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/stream")
async def stream_transcription(
    request: Request,
    file_id: str,
    filename: str = "transcript",
    model: str = "medium",
    language: str = "ru",
):
    files = list(UPLOADS_DIR.glob(f"{file_id}*"))
    if not files:
        async def _err():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Файл не найден'})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    file_path = files[0]
    extract_audio = file_path.suffix.lower() not in AUDIO_EXTENSIONS

    cancel_event = threading.Event()
    queue: asyncio.Queue = asyncio.Queue()
    _active[file_id] = (cancel_event, queue)
    loop = asyncio.get_running_loop()

    def _run():
        lang = None if language == "auto" else language
        t_start = time.time()
        delete_original = False

        try:
            transcribe_path = str(file_path)

            # ── Извлечь аудио из видео ────────────────────────────────────────
            if extract_audio:
                _put(loop, queue, {"type": "status", "message": "Извлечение аудиодорожки..."})
                audio_out = UPLOADS_DIR / f"{file_id}_audio.mp3"
                res = subprocess.run(
                    [FFMPEG, "-y", "-i", transcribe_path,
                     "-vn", "-acodec", "mp3", "-ab", "128k", "-ar", "44100",
                     str(audio_out)],
                    capture_output=True,
                )
                if res.returncode != 0:
                    _put(loop, queue, {
                        "type": "error",
                        "message": f"ffmpeg error: {res.stderr.decode()[-300:]}",
                    })
                    return
                transcribe_path = str(audio_out)
                delete_original = True  # оригинальное видео больше не нужно

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
            if delete_original:
                file_path.unlink(missing_ok=True)
            # Аудиофайл остаётся в UPLOADS_DIR для /audio/{file_id}
            # Удаляется через /clear/{file_id} или 24ч cleanup при старте
            _active.pop(file_id, None)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    async def _generate():
        collected_segments: list = []
        done_data: dict | None   = None
        try:
            while True:
                # Ждём следующий сегмент с таймаутом — чтобы проверять разрыв соединения
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        cancel_event.set()
                        break
                    continue

                if item is None:
                    break

                if item.get("type") == "segment":
                    collected_segments.append(item)
                elif item.get("type") == "done":
                    done_data = item

                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        except GeneratorExit:
            # Браузер закрыл вкладку / страницу — останавливаем фоновый поток
            cancel_event.set()
        finally:
            _active.pop(file_id, None)
            if done_data and collected_segments:
                threading.Thread(
                    target=_save_history,
                    args=(file_id, filename, collected_segments, done_data),
                    daemon=True,
                ).start()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Бэкенд: MLX Whisper (Apple Silicon)
# ──────────────────────────────────────────────────────────────────────────────

def _mlx_model_cached(model_name: str) -> bool:
    """Проверяет что MLX модель полностью скачана.

    Два критерия:
    - refs/main существует (HuggingFace пишет его только после полной загрузки)
    - суммарный размер blobs > 100 MB
    """
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    repo = f"whisper-{model_name}-mlx" if model_name != "large" else "whisper-large-v3-mlx"
    model_dir = hf_home / "hub" / f"models--mlx-community--{repo}"
    if not model_dir.exists():
        return False
    if not (model_dir / "refs" / "main").exists():
        return False
    blobs_dir = model_dir / "blobs"
    if not blobs_dir.exists():
        return False
    try:
        total = sum(f.stat().st_size for f in blobs_dir.iterdir() if f.is_file())
    except OSError:
        return False
    return total > 100 * 1024 * 1024


def _run_mlx(path, model, lang, t_start, loop, queue, cancel_event):
    try:
        import mlx_whisper
    except ImportError as e:
        _put(loop, queue, {
            "type": "error",
            "message": (
                f"Не удалось загрузить MLX Whisper: {e}\n"
                "Перезапусти приложение — зависимости установятся автоматически."
            ),
        })
        return

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
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        _put(loop, queue, {
            "type": "error",
            "message": (
                f"Не удалось загрузить faster-whisper: {e}\n"
                "Перезапусти приложение — зависимости установятся автоматически."
            ),
        })
        return

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


def _to_srt_time(s: float) -> str:
    ms = round((s % 1) * 1000)
    ss = int(s) % 60
    mm = int(s // 60) % 60
    hh = int(s // 3600)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _save_history(file_id: str, filename: str, segments: list, done_data: dict) -> None:
    """Сохраняет завершённую транскрибацию в папку history/."""
    try:
        entry_id  = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        entry_dir = HISTORY_DIR / entry_id
        entry_dir.mkdir(parents=True, exist_ok=True)
        base_name = Path(filename).stem

        # meta.json
        meta = {
            "id":        entry_id,
            "filename":  filename,
            "base_name": base_name,
            "date":      time.strftime("%d.%m.%Y %H:%M"),
            "segments":  done_data.get("segments", 0),
            "language":  done_data.get("language", "?"),
            "speed":     done_data.get("speed", ""),
        }
        (entry_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

        # transcript.txt
        txt = "\n\n".join(
            f"[{s['start']} --> {s['end']}]\n{s['text']}" for s in segments
        )
        (entry_dir / "transcript.txt").write_text(txt, encoding="utf-8")

        # transcript.srt
        srt_blocks = [
            f"{i}\n{_to_srt_time(s['start_s'])} --> {_to_srt_time(s['end_s'])}\n{s['text']}"
            for i, s in enumerate(segments, 1)
        ]
        (entry_dir / "transcript.srt").write_text(
            "\n\n".join(srt_blocks), encoding="utf-8"
        )

        # audio — копируем из UPLOADS_DIR
        for pattern in [f"{file_id}_audio.*", f"{file_id}.*"]:
            for src in UPLOADS_DIR.glob(pattern):
                if src.suffix.lower() in AUDIO_EXTENSIONS:
                    shutil.copy2(src, entry_dir / f"audio{src.suffix.lower()}")
                    break
            else:
                continue
            break

    except Exception:
        pass  # история не должна ронять основной поток


# ──────────────────────────────────────────────────────────────────────────────
# История транскрибаций
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/history")
async def list_history():
    entries = []
    if HISTORY_DIR.exists():
        for entry_dir in sorted(HISTORY_DIR.iterdir(), reverse=True):
            meta_file = entry_dir / "meta.json"
            if not entry_dir.is_dir() or not meta_file.exists():
                continue
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["has_audio"] = any(
                (entry_dir / f"audio{ext}").exists() for ext in AUDIO_EXTENSIONS
            )
            entries.append(meta)
    return JSONResponse(entries)


def _history_meta(entry_id: str) -> dict | None:
    meta_file = HISTORY_DIR / entry_id / "meta.json"
    if not meta_file.exists():
        return None
    return json.loads(meta_file.read_text(encoding="utf-8"))


@app.get("/history/{entry_id}/txt")
async def history_txt(entry_id: str):
    path = HISTORY_DIR / entry_id / "transcript.txt"
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    meta = _history_meta(entry_id)
    fname = f"{meta['base_name']}.txt" if meta else "transcript.txt"
    return FileResponse(str(path), filename=fname, media_type="text/plain; charset=utf-8")


@app.get("/history/{entry_id}/srt")
async def history_srt(entry_id: str):
    path = HISTORY_DIR / entry_id / "transcript.srt"
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    meta = _history_meta(entry_id)
    fname = f"{meta['base_name']}.srt" if meta else "transcript.srt"
    return FileResponse(str(path), filename=fname, media_type="text/plain; charset=utf-8")


@app.get("/history/{entry_id}/audio")
async def history_audio(entry_id: str):
    entry_dir = HISTORY_DIR / entry_id
    for ext in AUDIO_EXTENSIONS:
        path = entry_dir / f"audio{ext}"
        if path.exists():
            meta = _history_meta(entry_id)
            fname = f"{meta['base_name']}{ext}" if meta else f"audio{ext}"
            return FileResponse(str(path), filename=fname)
    return JSONResponse({"error": "not found"}, status_code=404)


@app.delete("/history/{entry_id}")
async def delete_history_entry(entry_id: str):
    entry_dir = HISTORY_DIR / entry_id
    if entry_dir.exists() and entry_dir.is_dir():
        shutil.rmtree(entry_dir)
    return JSONResponse({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# Запуск
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)
