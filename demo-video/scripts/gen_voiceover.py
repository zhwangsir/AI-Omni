#!/usr/bin/env python3
"""M40 演示视频旁白生成：调用 Workstation IndexTTS2 服务（雪莉默认音色）。

契约与 ``omni_voice/backends/indextts2_tts.py`` 一致：
``POST /tts`` multipart/form-data（text/language/emo_alpha/top_p/temperature），
返回 RIFF/WAV 字节，本脚本无损落盘到 ``demo-video/public/voiceover/``。

用法：
    python3 demo-video/scripts/gen_voiceover.py            # 生成全部 8 段
    python3 demo-video/scripts/gen_voiceover.py --force    # 无视已存在重新生成
    python3 demo-video/scripts/gen_voiceover.py --only scene-01-intro.wav
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import uuid
import wave
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from voiceover_script import SCENES  # noqa: E402

OUT_DIR = SCRIPT_DIR.parent / "public" / "voiceover"
DEFAULT_ENDPOINT = "http://192.168.71.127:9200"

# 采样参数与 omni_voice IndexTTS2 后端默认值对齐（雪莉日常对话音色克隆档）
EMO_ALPHA = 0.8
TOP_P = 0.75
TEMPERATURE = 0.65


def synthesize(endpoint: str, text: str) -> bytes:
    """POST /tts，返回服务原始 WAV 字节。"""
    boundary = f"----omnidemo-{uuid.uuid4().hex}"
    fields = {
        "text": text,
        "language": "zh",
        "emo_alpha": str(EMO_ALPHA),
        "top_p": str(TOP_P),
        "temperature": str(TEMPERATURE),
    }
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/tts",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def wav_duration_s(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--force", action="store_true", help="已存在也重新生成")
    parser.add_argument("--only", help="只生成指定文件名（如 scene-01-intro.wav）")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for filename, _from, _duration, text in SCENES:
        if args.only and filename != args.only:
            continue
        out_path = OUT_DIR / filename
        if out_path.exists() and not args.force:
            print(f"[skip] {filename} 已存在（--force 重新生成）")
            continue
        print(f"[tts ] {filename} ← {text}")
        try:
            wav_bytes = synthesize(args.endpoint, text)
        except Exception as exc:  # noqa: BLE001 —— 生成脚本需汇总全部失败
            print(f"[fail] {filename}: {exc}")
            failures += 1
            continue
        out_path.write_bytes(wav_bytes)
        print(f"[ ok ] {filename}  {wav_duration_s(wav_bytes):.2f}s  {len(wav_bytes)/1024:.0f}KB")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
