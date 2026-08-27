"""Gerador administrativo de thumbnails para origens directory do save.json."""
import argparse
import json
import random
from pathlib import Path
import cv2

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi"}

def process_source(source):
    root = Path(source["options"]["path"]).expanduser().resolve(strict=True)
    created = skipped = failed = 0
    for video in root.rglob("*"):
        if any(part.startswith(".") for part in video.relative_to(root).parts[:-1]) or not video.is_file() or video.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        target = video.parent / ".previews" / f"{video.stem}_banner.png"
        if target.exists(): skipped += 1; continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            capture = cv2.VideoCapture(str(video))
            if not capture.isOpened(): raise RuntimeError("não foi possível abrir o vídeo")
            frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)); capture.set(cv2.CAP_PROP_POS_FRAMES, random.randint(max(0, int(frames * .1)), max(0, int(frames * .7))))
            ok, frame = capture.read(); capture.release()
            if not ok or not cv2.imwrite(str(target), frame): raise RuntimeError("não foi possível gravar a imagem")
            created += 1
        except Exception as exc: failed += 1; print(f"[{source['id']}] Falha em {video.name}: {exc}")
    return created, skipped, failed

def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--config", default="save.json"); parser.add_argument("--source-id"); args = parser.parse_args()
    with open(args.config, encoding="utf-8") as stream: sources = json.load(stream).get("sources", [])
    selected = [source for source in sources if source.get("enabled", True) and source.get("type") == "directory" and (not args.source_id or source.get("id") == args.source_id)]
    if args.source_id and not selected: parser.error("source_id não corresponde a uma origem directory habilitada")
    totals = [0, 0, 0]
    for source in selected:
        try: result = process_source(source)
        except Exception as exc: result = (0, 0, 1); print(f"[{source.get('id', '?')}] Falha na origem: {exc}")
        totals = [left + right for left, right in zip(totals, result)]
    print(f"Resumo: {totals[0]} criados, {totals[1]} existentes, {totals[2]} falhas."); return 1 if totals[2] else 0

if __name__ == "__main__": raise SystemExit(main())
