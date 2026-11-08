"""Audio loading, resampling and silence-aware chunking shared by every STT engine."""
from __future__ import annotations

import io
from typing import List, Tuple

import numpy as np

TARGET_SR = 16000


def _resample(y: np.ndarray, sr: int, target: int = TARGET_SR) -> np.ndarray:
    if sr == target or y.size == 0:
        return y.astype(np.float32)
    try:
        import librosa  # high-quality resampler when available
        return librosa.resample(y.astype(np.float32), orig_sr=sr, target_sr=target).astype(np.float32)
    except Exception:
        n_out = int(round(len(y) * target / sr))
        x_old = np.linspace(0.0, 1.0, num=len(y), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        return np.interp(x_new, x_old, y).astype(np.float32)


def load_audio(source, target_sr: int = TARGET_SR) -> np.ndarray:
    """Load a path or raw bytes into mono float32 at target_sr. Raises ValueError for unreadable audio."""
    import soundfile as sf
    try:
        if isinstance(source, (bytes, bytearray)):
            if not source:
                raise ValueError("ไฟล์เสียงว่างเปล่า")
            y, sr = sf.read(io.BytesIO(bytes(source)), dtype="float32", always_2d=False)
        else:
            y, sr = sf.read(str(source), dtype="float32", always_2d=False)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"อ่านไฟล์เสียงไม่ได้ (รองรับ WAV/FLAC/OGG): {exc}") from exc
    if y.ndim > 1:
        y = y.mean(axis=1)
    return _resample(np.asarray(y, dtype=np.float32), int(sr), target_sr)


def frame_db(y: np.ndarray, sr: int = TARGET_SR, frame_s: float = 0.03) -> np.ndarray:
    n = max(1, int(sr * frame_s))
    k = len(y) // n
    if k == 0:
        return np.array([-100.0])
    fr = y[: k * n].reshape(k, n)
    rms = np.sqrt(np.mean(fr * fr, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-12)


def split_on_silence(
    y: np.ndarray,
    sr: int = TARGET_SR,
    max_s: float = 25.0,
    min_s: float = 8.0,
    frame_s: float = 0.03,
) -> List[Tuple[int, int]]:
    """Cut audio into chunks of at most max_s seconds, each cut placed at the quietest
    stretch (~0.3 s smoothed) between min_s and max_s. Returns (start, end) sample indices."""
    total = len(y)
    if total <= int(max_s * sr):
        return [(0, total)]
    db = frame_db(y, sr, frame_s)
    win = max(1, int(0.3 / frame_s))
    smooth = np.convolve(db, np.ones(win) / win, mode="same")
    hop = int(sr * frame_s)
    spans: List[Tuple[int, int]] = []
    start = 0
    while total - start > int(max_s * sr):
        lo = (start + int(min_s * sr)) // hop
        hi = min(len(smooth) - 1, (start + int(max_s * sr)) // hop)
        if hi <= lo:
            cut = start + int(max_s * sr)
        else:
            cut = (lo + int(np.argmin(smooth[lo:hi]))) * hop
        spans.append((start, cut))
        start = cut
    spans.append((start, total))
    return spans


def is_silent(seg: np.ndarray, sr: int = TARGET_SR, thresh_db: float = -45.0) -> bool:
    """True when no 30 ms frame rises above thresh_db (prevents Whisper hallucinating on silence)."""
    if seg.size < sr * 0.2:
        return True
    return float(np.max(frame_db(seg, sr))) < thresh_db
