# -*- coding: utf-8 -*-
"""
Worker process สำหรับ NeMo ASR บน Windows

เมื่อรัน Streamlit + pyannote ใน process เดียวกัน บางเครื่องจะโหลด
onnx.onnx_cpp2py_export (ไฟล์ .pyd) ไม่สำเร็จ (DLL initialization failed)
เพราะลำดับ/ชุด DLL ชนกัน — แยก interpreter นี้ไว้โหลดแค่ NeMo เพื่อหลีกเลี่ยงปัญหา

โปรโตคอล stdin บรรทัดละ JSON (UTF-8):
  {"op": "transcribe", "path": "C:/.../tmp.wav"}
ตอบ stdout บรรทัดละ JSON:
  {"ok": true, "text": "..."} หรือ {"ok": false, "error": "..."}
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TQDM_DISABLE", "1")

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _reply(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _transcribe_with_muted_stdio(wav_path: str, model, asr_text_fn) -> str:
    """กด tqdm / log ของ NeMo ไม่ให้ไปปน stdout (โปรโตคอล JSON บรรทัดเดียว)."""
    dn = open(os.devnull, "w", encoding="utf-8")
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout = dn
        sys.stderr = dn
        try:
            out = model.transcribe([wav_path], batch_size=1, return_hypotheses=False)
        except TypeError:
            out = model.transcribe(paths2audio_files=[wav_path], batch_size=1)
        return asr_text_fn(out)
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
        dn.close()


def main() -> None:
    model = None

    def ensure_model():
        nonlocal model
        if model is not None:
            return
        dn = open(os.devnull, "w", encoding="utf-8")
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout = dn
            sys.stderr = dn
            from speech_to_text import load_nemo_asr_model

            bundle = load_nemo_asr_model()
            model = bundle["model"]
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
            dn.close()

    from speech_to_text import _asr_text_from_nemo_output

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            _reply({"ok": False, "error": f"JSON decode: {e}"})
            continue

        op = msg.get("op")
        if op == "quit":
            break

        if op != "transcribe":
            _reply({"ok": False, "error": f"unknown op: {op!r}"})
            continue

        wav_path = msg.get("path")
        if not wav_path or not Path(wav_path).is_file():
            _reply({"ok": False, "error": f"bad path: {wav_path!r}"})
            continue

        try:
            ensure_model()
            text = _transcribe_with_muted_stdio(
                wav_path, model, _asr_text_from_nemo_output
            )
            _reply({"ok": True, "text": text})
        except Exception as e:
            _reply(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
            )


if __name__ == "__main__":
    main()
