# -*- coding: utf-8 -*-
"""Compare STT engines on every recording that has a ground-truth transcript.
Results: logs/stt_compare.jsonl (one line per file/engine) and logs/stt_compare.md (summary)."""
from __future__ import annotations
import glob, json, os, re, subprocess, sys, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LOGS = ROOT / "logs"; LOGS.mkdir(exist_ok=True)
OUT = LOGS / "stt_compare.jsonl"
PROG = open(LOGS / "stt_compare_progress.txt", "a", encoding="utf-8")

def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(map(str, a)); print(s, flush=True); PROG.write(s + "\n"); PROG.flush()

def lev(a, b):
    if len(a) < len(b): a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]

def norm(s): return re.sub(r"[\s\.,!?\-–—:;\"'()\[\]…]", "", s or "")

def cer(hyp, ref):
    ref = norm(ref); return round(lev(norm(hyp), ref) / max(1, len(ref)), 4)

def read_gt(p):
    out = []
    for ln in Path(p).read_text(encoding="utf-8").splitlines():
        ln = re.sub(r"^\s*\[[^\]]*\]\s*", "", ln.strip())
        m = re.match(r"^(เภสัช\S*|คนไข้\S*|ผู้ป่วย\S*)\s*[:：]\s*(.*)", ln)
        if m: out.append(m.group(2))
    return " ".join(out)

def pairs():
    audio = {}
    for p in glob.glob(str(ROOT / "ไฟล์เสียงทั้งหมด" / "**" / "*.wav"), recursive=True) + glob.glob(str(ROOT / "lab" / "sample_audio" / "*.wav")):
        m = re.search(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", p)
        if m: audio.setdefault(m.group(1), p)
    ps = [(g, audio[g.stem]) for g in sorted((ROOT / "ground_truth").glob("*.txt")) if g.stem in audio]
    import soundfile as sf
    ps = sorted(ps, key=lambda x: sf.info(x[1]).duration)
    n = int(os.environ.get("STT_COMPARE_MAX_FILES", "0") or 0)  # quick trial: only the N shortest recordings
    return ps[:n] if n > 0 else ps

WHOLE_MAX_S = float(os.environ.get("STT_COMPARE_WHOLE_MAX_S", "130"))


def sf_dur(p):
    import soundfile as sf
    return sf.info(p).duration


def done_keys():
    s = set()
    if OUT.exists():
        for ln in OUT.read_text(encoding="utf-8").splitlines():
            try: d = json.loads(ln); s.add((d["file"], d["engine"]))
            except Exception: pass
    return s

def record(d):
    with open(OUT, "a", encoding="utf-8") as f: f.write(json.dumps(d, ensure_ascii=False) + "\n")

def whisper_blocker():
    """Reason Whisper cannot run on this machine, or '' when it can (large-v3: ~6.2 GB download, ~7 GB RAM in fp32)."""
    import shutil
    if os.environ.get("STT_COMPARE_SKIP_WHISPER") == "1":
        return "STT_COMPARE_SKIP_WHISPER=1"
    from unified_app.modules.stt_typhoon import WHISPER_MODEL_ID
    hub = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub")
    cached = any(hub.glob(f"models--{WHISPER_MODEL_ID.replace('/', '--')}/snapshots/*/*.safetensors"))
    free_gb = shutil.disk_usage(str(ROOT)).free / 1e9
    if not cached and free_gb < 9:
        return f"model {WHISPER_MODEL_ID} not downloaded and only {free_gb:.1f} GB disk free (needs ~6.2 GB + headroom)"
    try:
        ram_gb = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 1e9
    except Exception:
        ram_gb = 0
    cuda = False
    try:
        import torch
        cuda = torch.cuda.is_available()
    except Exception:
        pass
    if not cuda and ram_gb and ram_gb < 14 and os.environ.get("STT_COMPARE_FORCE_WHISPER") != "1":
        return f"only {ram_gb:.0f} GB RAM and no CUDA GPU (large-v3 fp32 needs ~7 GB free RAM; machine would swap heavily). Set STT_COMPARE_FORCE_WHISPER=1 to try anyway"
    return ""


def probe_whisper_mps(path, ref):
    """Run whisper on MPS in a subprocess with a timeout (MPS hung/garbled in earlier lab tests)."""
    code = (f"import sys,json;sys.path.insert(0,{str(ROOT)!r});"
            "from unified_app.modules.stt_typhoon import TyphoonASRRecognizer as R;"
            "r=R(engine='whisper');assert r.load_model(),r.load_error;"
            f"d=r.transcribe_detailed({path!r},apply_dictionary=False);print('JSON'+json.dumps(d,ensure_ascii=False))")
    env = dict(os.environ, PHARMALOG_WHISPER_DEVICE="mps")
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=420)
        line = next((l for l in p.stdout.splitlines() if l.startswith("JSON")), None)
        if not line: return {"ok": False, "why": (p.stderr or p.stdout)[-400:]}
        d = json.loads(line[4:]); return {"ok": True, "cer": cer(d["raw_text"], ref), "elapsed": round(time.time() - t0, 1), "text": d["raw_text"][:200]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": "timeout 420s (hung)"}

def main():
    from unified_app.modules.stt_typhoon import TyphoonASRRecognizer
    ps = pairs(); log(f"{len(ps)} recordings with ground truth")
    done = done_keys()
    # ---------- engine 1: realtime (chunked) + realtime whole-file (old behaviour)
    rt = TyphoonASRRecognizer(engine="realtime"); assert rt.load_model(), rt.load_error
    for g, a in ps:
        ref = read_gt(g); name = Path(a).name
        if (name, "realtime") not in done:
            try:
                d = rt.transcribe_detailed(a)
                record({"file": name, "engine": "realtime", "dur": d["duration_s"], "elapsed": d["elapsed_s"],
                        "cer_raw": cer(d["raw_text"], ref), "cer_dict": cer(d["text"], ref), "n_changes": len(d["changes"]),
                        "chunks": d["chunks"], "raw": d["raw_text"], "text": d["text"]})
                log("realtime", name, d["duration_s"], "s ->", d["elapsed_s"], "s  CER", cer(d["raw_text"], ref), "/ dict", cer(d["text"], ref))
            except Exception as e:
                record({"file": name, "engine": "realtime", "error": str(e)[:300]}); log("realtime ERROR", name, e)
        if (name, "realtime_whole") not in done and sf_dur(a) > WHOLE_MAX_S:
            record({"file": name, "engine": "realtime_whole", "skipped": f"> {WHOLE_MAX_S:.0f}s (whole-file decoding exhausts RAM on 8 GB Macs)"})
        elif (name, "realtime_whole") not in done:
            try:
                t0 = time.time(); txt = rt.model.transcribe([a], batch_size=1, verbose=False)
                if isinstance(txt, tuple): txt = txt[0]
                from unified_app.modules.stt_typhoon import _hyp_text
                txt = _hyp_text(txt[0]) if txt else ""
                record({"file": name, "engine": "realtime_whole", "elapsed": round(time.time() - t0, 2), "cer_raw": cer(txt, ref)})
                log("realtime_whole", name, "CER", cer(txt, ref))
            except Exception as e:
                record({"file": name, "engine": "realtime_whole", "error": str(e)[:300]}); log("realtime_whole ERROR", name, str(e)[:200])
    del rt
    import gc; gc.collect()
    # ---------- engine 2: whisper large v3 (probe MPS once, else CPU)
    why_skip = whisper_blocker()
    if why_skip:
        log("whisper SKIPPED:", why_skip)
        record({"file": "-", "engine": "whisper_skipped", "why": why_skip}); summarize(); return
    try:  # download once up front so the MPS probe timeout does not include a 6 GB download
        from huggingface_hub import snapshot_download
        from unified_app.modules.stt_typhoon import WHISPER_MODEL_ID
        log("downloading/checking", WHISPER_MODEL_ID); snapshot_download(WHISPER_MODEL_ID, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken"]); log("model files ready")
    except Exception as e:
        log("model download failed:", str(e)[:300]); record({"file": "-", "engine": "whisper_skipped", "why": f"download failed: {e}"[:300]}); summarize(); return
    if not os.environ.get("PHARMALOG_WHISPER_DEVICE"):
        g0, a0 = ps[min(2, len(ps) - 1)]  # probe on a short file
        pr = probe_whisper_mps(a0, read_gt(g0)); log("MPS probe:", json.dumps(pr, ensure_ascii=False)[:400])
        record({"file": Path(a0).name, "engine": "whisper_mps_probe", **pr})
        os.environ["PHARMALOG_WHISPER_DEVICE"] = "mps" if pr.get("ok") and pr.get("cer", 9) < 0.6 else "cpu"
    log("whisper device:", os.environ["PHARMALOG_WHISPER_DEVICE"])
    wh = TyphoonASRRecognizer(engine="whisper"); assert wh.load_model(), wh.load_error
    tot_d = tot_e = 0.0; n_done = 0
    for g, a in ps:
        ref = read_gt(g); name = Path(a).name
        if (name, "whisper") in done: continue
        if (n_done >= 8 and tot_e / max(1e-9, tot_d) > 1.5) or (n_done >= 2 and tot_e / max(1e-9, tot_d) > 3.0):
            log(f"whisper RTF {tot_e / tot_d:.2f} after {n_done} files: too slow for production, stopping whisper run")
            record({"file": "-", "engine": "whisper_stopped", "rtf": round(tot_e / tot_d, 3), "after_files": n_done}); break
        try:
            d = wh.transcribe_detailed(a)
            record({"file": name, "engine": "whisper", "model": wh.model_name, "device": wh.device, "dur": d["duration_s"], "elapsed": d["elapsed_s"],
                    "cer_raw": cer(d["raw_text"], ref), "cer_dict": cer(d["text"], ref), "n_changes": len(d["changes"]),
                    "chunks": d["chunks"], "raw": d["raw_text"], "text": d["text"]})
            log("whisper", name, d["duration_s"], "s ->", d["elapsed_s"], "s  CER", cer(d["raw_text"], ref), "/ dict", cer(d["text"], ref))
            tot_d += d["duration_s"]; tot_e += d["elapsed_s"]; n_done += 1
        except Exception as e:
            record({"file": name, "engine": "whisper", "error": str(e)[:300]}); log("whisper ERROR", name, e)
    summarize()

def summarize():
    rows = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    by = {}
    for r in rows: by.setdefault(r["engine"], []).append(r)
    L = ["# STT comparison", "", "| engine | files | mean CER raw | mean CER +dict | total audio s | total time s | RTF |", "|---|---|---|---|---|---|---|"]
    for e, rs in by.items():
        ok = [r for r in rs if "cer_raw" in r]
        if not ok: continue
        m = lambda k: round(sum(r.get(k, 0) or 0 for r in ok) / len(ok), 4) if all(k in r for r in ok) else "-"
        dur = round(sum(r.get("dur", 0) or 0 for r in ok)); el = round(sum(r.get("elapsed", 0) or 0 for r in ok))
        L.append(f"| {e} | {len(ok)} | {m('cer_raw')} | {m('cer_dict')} | {dur} | {el} | {round(el / dur, 3) if dur else '-'} |")
    (LOGS / "stt_compare.md").write_text("\n".join(L), encoding="utf-8"); log("\n".join(L)); log("COMPARE_DONE")

if __name__ == "__main__":
    try: main()
    except Exception:
        log("FATAL", traceback.format_exc()); summarize()
