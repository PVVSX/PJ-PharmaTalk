# -*- coding: utf-8 -*-
"""
EvalLab EMR model comparison engine.

Runs the SAME prompt (reused read-only from the main system) against several
LLM providers so their EMR extraction can be compared side by side.
API keys are only kept in memory / passed in by the UI; nothing is written to disk
except the (key-free) result cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# Standalone EMR helpers from modules/
try:
    from modules.emr_groq import (
        EMR_FIELDS,
        _build_prompt,
        _call_groq,
        _parse_fields,
    )
except ImportError:
    from emr_groq import (  # noqa: E402
        EMR_FIELDS,
        _build_prompt,
        _call_groq,
        _parse_fields,
    )

EMR_CACHE_DIR = APP_DIR / "cache_emr"
EMR_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_ground_truth_dir() -> Path:
    """คืนพาธไดเรกทอรี ground_truth โดยค้นหาทั้งใน lab/ และใน root ของโปรเจกต์"""
    gt = APP_DIR / "ground_truth"
    if gt.exists() and any(gt.glob("*.txt")):
        return gt
    return APP_DIR.parent / "ground_truth"


GROUND_TRUTH_DIR = get_ground_truth_dir()

REQUEST_TIMEOUT = 90

# provider id -> display label, default model, suggested models, key file, env var
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "groq": {
        "label": "Groq (ระบบปัจจุบัน)",
        "default_model": "openai/gpt-oss-120b",
        "suggestions": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "qwen/qwen3-32b", "openai/gpt-oss-20b"],
        "key_file": ".groq_api_key",
        "env": "GROQ_API_KEY",
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "default_model": "claude-sonnet-4-5",
        "suggestions": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-5-haiku-latest"],
        "key_file": ".anthropic_api_key",
        "env": "ANTHROPIC_API_KEY",
    },
    "gemini": {
        "label": "Google Gemini",
        "default_model": "gemini-2.5-flash",
        "suggestions": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "key_file": ".gemini_api_key",
        "env": "GEMINI_API_KEY",
    },
}


def load_saved_key(provider: str) -> str:
    """Key from env var or key file in directory."""
    spec = PROVIDERS[provider]
    key = os.environ.get(spec["env"], "").strip()
    if not key:
        candidates = [
            APP_DIR / spec["key_file"],
            APP_DIR.parent / spec["key_file"],
            APP_DIR.parent / "pharmalog_offline_assets" / spec["key_file"],
            APP_DIR.parent / "pharmalog_offline_assets" / "api_keys" / spec["key_file"],
        ]
        for p in candidates:
            if p.exists():
                key = p.read_text(encoding="utf-8").strip()
                if key:
                    break
    return key


# ── Provider calls ────────────────────────────────────────────────────────
def _call_claude(api_key: str, model: str, prompt: str) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Claude API {resp.status_code}: {resp.text[:300]}")
    blocks = resp.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _call_gemini(api_key: str, model: str, prompt: str) -> str:
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "content-type": "application/json"},
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API {resp.status_code}: {resp.text[:300]}")
    cands = resp.json().get("candidates", [])
    if not cands:
        raise RuntimeError("Gemini ไม่คืนผลลัพธ์ (อาจถูกกรองเนื้อหา)")
    parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def _call_provider(provider: str, api_key: str, model: str, prompt: str) -> str:
    if provider == "groq":
        return _call_groq(api_key, model, prompt)
    if provider == "claude":
        return _call_claude(api_key, model, prompt)
    if provider == "gemini":
        return _call_gemini(api_key, model, prompt)
    raise ValueError(f"unknown provider: {provider}")


# ── Scoring ───────────────────────────────────────────────────────────────
def score_result(fields: Dict[str, str]) -> Dict[str, Any]:
    """Completeness of the 5 clinical fields (the dialogue field is excluded)."""
    clinical = [f for f in EMR_FIELDS if f != "บทสนทนาที่จัดเรียงแล้ว"]
    filled = [f for f in clinical if str(fields.get(f, "-")).strip() not in ("", "-")]
    return {
        "filled": len(filled),
        "total": len(clinical),
        "percent": round(100 * len(filled) / len(clinical)) if clinical else 0,
        "empty_fields": [f for f in clinical if f not in filled],
    }


# ── Cache ─────────────────────────────────────────────────────────────────
def text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def _cache_path(thash: str, provider: str, model: str) -> Path:
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", model)
    return EMR_CACHE_DIR / f"{thash}__{provider}__{safe_model}.json"


def get_cached(thash: str, provider: str, model: str) -> Optional[Dict[str, Any]]:
    p = _cache_path(thash, provider, model)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cached(thash: str, provider: str, model: str, data: Dict[str, Any]) -> None:
    try:
        _cache_path(thash, provider, model).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        print(f"EMR cache write failed: {exc}")


# ── Run ───────────────────────────────────────────────────────────────────
def run_one(provider: str, model: str, api_key: str, conversation: str, use_cache: bool = True) -> Dict[str, Any]:
    thash = text_hash(conversation)
    if use_cache:
        cached = get_cached(thash, provider, model)
        if cached:
            cached["from_cache"] = True
            return cached

    label = PROVIDERS[provider]["label"]
    base = {"provider": provider, "label": label, "model": model, "from_cache": False}

    if not api_key:
        return {**base, "ok": False, "error": "ยังไม่ได้ใส่ API Key", "latency": 0.0, "fields": {}, "score": None}

    start = time.time()
    try:
        raw = _call_provider(provider, api_key, model, _build_prompt(conversation))
        fields = _parse_fields(raw)
        latency = round(time.time() - start, 2)
        if not fields:
            return {**base, "ok": False, "error": "โมเดลตอบกลับมาไม่เป็น JSON ที่อ่านได้", "latency": latency,
                    "fields": {}, "score": None, "raw": (raw or "")[:1500]}
        result = {**base, "ok": True, "error": "", "latency": latency, "fields": fields,
                  "score": score_result(fields)}
        _save_cached(thash, provider, model, result)
        return result
    except Exception as exc:
        return {**base, "ok": False, "error": str(exc)[:400], "latency": round(time.time() - start, 2),
                "fields": {}, "score": None}


def run_comparison(conversation: str, jobs: List[Dict[str, str]], use_cache: bool = True) -> List[Dict[str, Any]]:
    """jobs: [{"provider","model","api_key"}]. Runs in parallel, keeps input order."""
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [
            pool.submit(run_one, j["provider"], j["model"], j["api_key"], conversation, use_cache)
            for j in jobs
        ]
        return [f.result() for f in futures]


# ── Conversation sources ──────────────────────────────────────────────────
_TS_PREFIX = re.compile(r"^\s*\[[^\]]*\]\s*")


def list_ground_truth() -> List[Path]:
    gt_dir = get_ground_truth_dir()
    return sorted(gt_dir.glob("*.txt")) if gt_dir.exists() else []


def read_ground_truth(path: Path) -> str:
    """Ground-truth files carry '[ 0.0s-0.03s ]' prefixes; strip them."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = _TS_PREFIX.sub("", line).strip()
        if s:
            lines.append(s)
    return "\n".join(lines)


def match_ground_truth(audio_filename: str) -> Optional[Path]:
    """recording_2025-10-10_10-05-37.wav -> ground_truth/2025-10-10_10-05-37.txt"""
    m = re.search(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", audio_filename or "")
    if not m:
        return None
    gt_dir = get_ground_truth_dir()
    p = gt_dir / f"{m.group(1)}.txt"
    return p if p.exists() else None


def turns_to_text(turns: List[Dict[str, str]]) -> str:
    return "\n".join(f"{t.get('speaker', '')}: {t.get('text', '')}" for t in turns)
