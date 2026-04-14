"""
Транскрибация видео/аудио через faster-whisper.
Бесплатно, локально, поддержка русского языка.

Установка зависимостей:
    pip install -r requirements.txt
    ffmpeg должен быть установлен: winget install Gyan.FFmpeg

Первый запуск скачает модель (~1.5 GB для medium).

Использование:
    python transcribe.py meeting.mp4
    python transcribe.py meeting.mp4 --model large
    python transcribe.py meeting.mp4 --output C:/transcripts/meet.txt
    python transcribe.py meeting.mp4 --extract-audio
    python transcribe.py meeting.mp4 --extract-audio --keep-audio
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Извлечение аудио
# ──────────────────────────────────────────────────────────────────────────────

def extract_audio(video_path: Path, output_path: Path | None = None) -> Path:
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        output_path = Path(tmp.name)
        tmp.close()

    print(f"Извлекаю аудио: {video_path.name} → {output_path.name}")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "mp3",
        "-ab", "64k",
        "-ar", "16000",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Ошибка ffmpeg:")
        print(result.stderr[-1000:])
        sys.exit(1)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"Готово: {output_path.name} ({size_mb:.1f} MB)")
    return output_path


# ──────────────────────────────────────────────────────────────────────────────
# Транскрибация
# ──────────────────────────────────────────────────────────────────────────────

def transcribe(
    input_path: str,
    model_size: str = "medium",
    output_path: str | None = None,
    extract_audio_first: bool = False,
    keep_audio: bool = False,
) -> Path:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("Установи: pip install faster-whisper")
        sys.exit(1)

    input_file = Path(input_path)
    if not input_file.exists():
        print(f"Файл не найден: {input_path}")
        sys.exit(1)

    if output_path is None:
        output_path = input_file.with_suffix(".txt")
    output_file = Path(output_path)

    audio_tmp: Path | None = None
    transcribe_file = input_file

    if extract_audio_first:
        audio_out = input_file.with_suffix(".mp3") if keep_audio else None
        transcribe_file = extract_audio(input_file, audio_out)
        if not keep_audio:
            audio_tmp = transcribe_file

    print(f"Загрузка модели '{model_size}'...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    print(f"Транскрибирую: {transcribe_file.name}")
    segments, info = model.transcribe(str(transcribe_file), language="ru")

    print(f"Язык: {info.language} (вероятность {info.language_probability:.2%})")
    print("Обрабатываю...")

    lines = []
    for segment in segments:
        start = _fmt_time(segment.start)
        end   = _fmt_time(segment.end)
        text  = segment.text.strip()
        line  = f"[{start} --> {end}] {text}"
        print(line)
        lines.append(line)

    output_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nСохранено: {output_file}")

    if audio_tmp and audio_tmp.exists():
        audio_tmp.unlink()

    return output_file


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Транскрибация видео/аудио через Whisper")
    parser.add_argument("input", help="Путь к видео или аудио файлу")
    parser.add_argument("--model", default="medium",
                        choices=["tiny", "base", "small", "medium", "large"],
                        help="Модель Whisper (default: medium)")
    parser.add_argument("--output", default=None,
                        help="Путь для сохранения текста (default: рядом с файлом)")
    parser.add_argument("--extract-audio", action="store_true",
                        help="Извлечь аудио через ffmpeg перед транскрибацией")
    parser.add_argument("--keep-audio", action="store_true",
                        help="Сохранить .mp3 рядом с видео (только с --extract-audio)")
    args = parser.parse_args()

    transcribe(
        args.input,
        model_size=args.model,
        output_path=args.output,
        extract_audio_first=args.extract_audio,
        keep_audio=args.keep_audio,
    )
