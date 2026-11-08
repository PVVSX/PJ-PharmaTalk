# -*- coding: utf-8 -*-
"""
PharmaLog AI - end-to-end system check (v2).
Starts its own Bridge API (8500) and Core API (8080) with cloud writes DISABLED and a short consent TTL,
then exercises consent rules, uploads, real recordings vs ground truth, concurrency, EMR, dictionary, PDF and pages.
Output: logs/e2e_report.md, logs/e2e_results.json, live progress in logs/e2e_progress.txt
"""
from __future__ import annotations
import glob, json, os, re, socket, subprocess, sys, time, traceback, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["PHARMALOG_DISABLE_CLOUD"] = "1"      # never write to Firestore/Storage during tests
os.environ["PHARMALOG_CONSENT_TTL"] = "6"        # short TTL so expiry can be tested
os.environ["PHARMALOG_RECORDING_MAX_S"] = "8"    # short so an abandoned recording (closed browser) can be tested
LOGS = ROOT / "logs"; LOGS.mkdir(exist_ok=True)
PROG = open(LOGS / "e2e_progress.txt", "w", encoding="utf-8")
import requests

BRIDGE, CORE = "http://127.0.0.1:8500", "http://127.0.0.1:8080"
R = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "checks": [], "recordings": [], "roles": [], "dict_changes": [], "task_ids": []}


def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(s, flush=True); PROG.write(s + "\n"); PROG.flush()


def check(name, ok, detail=""):
    R["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:700]})
    log(("PASS " if ok else "FAIL ") + name + (" | " + str(detail)[:300] if detail != "" else ""))
    return ok


def port_busy(p):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) == 0


def post_state(**k):
    r = requests.post(BRIDGE + "/api/state", json=k, timeout=5)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)


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


def read_gt(p):
    out = []
    for ln in Path(p).read_text(encoding="utf-8").splitlines():
        ln = re.sub(r"^\s*\[[^\]]*\]\s*", "", ln.strip())
        m = re.match(r"^(เภสัช\S*|คนไข้\S*|ผู้ป่วย\S*)\s*[:：]\s*(.*)", ln)
        if m: out.append(("P" if "เภสัช" in m.group(1) else "C", m.group(2).strip()))
    return out


def upload(path_or_bytes, name, consent_id=None, source="test"):
    data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else Path(path_or_bytes).read_bytes()
    form = {"source": source}
    if consent_id: form["consent_id"] = consent_id
    return requests.post(CORE + "/upload-audio", files={"file": (name, data, "audio/wav")}, data=form, timeout=120)


def wait_task(tid, timeout=600):
    t0, seen = time.time(), []
    while time.time() - t0 < timeout:
        t = requests.get(f"{CORE}/task/{tid}", timeout=10).json()
        if not seen or seen[-1] != t["status"]:
            seen.append(t["status"]); log(f"   task {tid[:8]}: {t['status']} @ {round(time.time() - t0)}s")
        if t["status"] in ("COMPLETED", "ERROR"):
            t["elapsed"] = round(time.time() - t0, 1); t["statuses"] = seen; return t
        time.sleep(2)
    return {"task_id": tid, "status": "TIMEOUT", "elapsed": round(time.time() - t0, 1), "statuses": seen}


procs = []
state_file = ROOT / "record" / "shared_state.json"
orig_state = state_file.read_text(encoding="utf-8") if state_file.exists() else None
try:
    # ------------------------------------------------------------------ 1. services
    log("== 1. services")
    if port_busy(8500) or port_busy(8080):
        check("ports 8500/8080 free (close start_pharmalog first)", False, "พบระบบเปิดค้างอยู่ — ปิดหน้าต่าง start_pharmalog แล้วรันทดสอบใหม่")
        raise SystemExit(1)
    py = sys.executable
    procs.append(subprocess.Popen([py, "api.py"], cwd=ROOT, stdout=open(LOGS / "e2e_api.log", "w"), stderr=subprocess.STDOUT))
    procs.append(subprocess.Popen([py, "main.py"], cwd=ROOT / "core_api", stdout=open(LOGS / "e2e_core.log", "w"), stderr=subprocess.STDOUT))
    h, t0 = None, time.time()
    while time.time() - t0 < 600:
        try:
            h = requests.get(CORE + "/health", timeout=3).json()
            if h.get("asr_loaded") and requests.get(BRIDGE + "/api/state", timeout=3).ok: break
        except Exception: pass
        if procs[1].poll() is not None: break
        time.sleep(3)
    check("Core API ready with STT model loaded", bool(h and h.get("asr_loaded")), h)
    if not (h and h.get("asr_loaded")): raise SystemExit(1)
    if not check("cloud writes disabled during test", h.get("cloud_enabled") is False, h.get("cloud_enabled")): raise SystemExit(1)
    R["engine"] = h.get("stt_engine"); R["device"] = h.get("stt_device")

    # ------------------------------------------------------------------ 2. consent rules
    log("== 2. consent rules (bridge)")
    post_state(status="WAITING")
    c, _ = post_state(status="BOGUS"); check("invalid status -> 400", c == 400, c)
    c, _ = post_state(status="READY"); check("READY without consent -> 400", c == 400, c)
    c, _ = post_state(status="RECORDING"); check("RECORDING without consent -> 409", c == 409, c)
    a_id = "e2e-" + uuid.uuid4().hex[:8]
    c, d = post_state(status="READY", consent={"consent_id": a_id, "consent_version": "1.0"}); check("READY with fresh consent -> 200", c == 200, c)
    post_state(status="WAITING", reason="declined")
    c, _ = post_state(status="READY", consent={"consent_id": a_id}); check("re-using a consent_id -> 409", c == 409, c)
    st_ = requests.get(BRIDGE + "/api/state").json(); check("decline clears consent", st_["status"] == "WAITING" and not st_.get("consent"), st_)
    c, _ = post_state(status="RECORDING"); check("RECORDING after decline -> 409", c == 409, c)
    b_id = "e2e-" + uuid.uuid4().hex[:8]
    post_state(status="READY", consent={"consent_id": b_id}); time.sleep(7)
    st_ = requests.get(BRIDGE + "/api/state").json(); check("READY expires after TTL -> WAITING", st_["status"] == "WAITING", st_)
    c, _ = post_state(status="RECORDING"); check("RECORDING after expiry -> 409", c == 409, c)
    ab_id = "e2e-" + uuid.uuid4().hex[:8]
    post_state(status="READY", consent={"consent_id": ab_id}); post_state(status="RECORDING"); time.sleep(9)
    st_ = requests.get(BRIDGE + "/api/state").json()
    cons_ = {x["consent_id"]: x for x in requests.get(BRIDGE + "/api/consents?limit=200").json()}
    check("abandoned RECORDING is released -> WAITING (consent 'abandoned')",
          st_["status"] == "WAITING" and cons_.get(ab_id, {}).get("status") == "abandoned", (st_["status"], cons_.get(ab_id, {}).get("status")))
    rec_id = "e2e-" + uuid.uuid4().hex[:8]
    post_state(status="READY", consent={"consent_id": rec_id})
    c, _ = post_state(status="RECORDING"); check("RECORDING with valid consent -> 200", c == 200, c)
    c, _ = post_state(status="READY", consent={"consent_id": "e2e-" + uuid.uuid4().hex[:8]}); check("new READY while recording -> 409", c == 409, c)

    # ------------------------------------------------------------------ 3. upload validation
    log("== 3. upload validation")
    check("unknown task -> 404", requests.get(CORE + "/task/nope").status_code == 404)
    r = upload(b"this is not audio", "x.wav"); check("non-audio upload rejected with 400", r.status_code == 400, f"{r.status_code} {r.text[:150]}")
    r = upload(b"", "empty.wav"); check("empty upload rejected with 400", r.status_code == 400, f"{r.status_code} {r.text[:150]}")

    # ------------------------------------------------------------------ 4. consent-linked pharmacist case
    log("== 4. pharmacist case linked to consent")
    import soundfile as sf
    gts = {g.stem: g for g in (ROOT / "ground_truth").glob("*.txt")}
    audio = {}
    for p in glob.glob(str(ROOT / "ไฟล์เสียงทั้งหมด" / "**" / "*.wav"), recursive=True) + glob.glob(str(ROOT / "lab" / "sample_audio" / "*.wav")):
        m = re.search(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", p)
        if m and m.group(1) in gts: audio.setdefault(m.group(1), p)
    pairs = sorted(((gts[k], Path(v)) for k, v in audio.items()), key=lambda x: sf.info(str(x[1])).duration)
    log(f"{len(pairs)} recordings have ground truth")
    first = next(p for p in pairs if sf.info(str(p[1])).duration > 30)
    r = upload(first[1], first[1].name, consent_id=rec_id, source="pharmacist")
    t = wait_task(r.json()["task_id"]); R["task_ids"].append(t["task_id"])
    check("pharmacist case completes", t["status"] == "COMPLETED", t.get("error_message"))
    check("task stores consent_id", t.get("consent_id") == rec_id, t.get("consent_id"))
    c, _ = post_state(status="FINISHED", task_id=t["task_id"], audio_filename=first[1].name)
    cons = {x["consent_id"]: x for x in requests.get(BRIDGE + "/api/consents?limit=200").json()}
    check("consent record linked to task + audio", cons.get(rec_id, {}).get("task_id") == t["task_id"], cons.get(rec_id))
    if t["status"] == "COMPLETED":
        emr = json.loads(t["emr_json"])
        conf = dict(emr); conf["คำแนะนำจากเภสัช"] = (conf.get("คำแนะนำจากเภสัช") or "") + " [แก้โดยเภสัชกร]"
        rc = requests.post(f"{CORE}/task/{t['task_id']}/confirm", json={"emr": conf}, timeout=10)
        t2 = requests.get(f"{CORE}/task/{t['task_id']}").json()
        check("pharmacist confirmation is saved", rc.ok and "[แก้โดยเภสัชกร]" in (t2.get("confirmed_emr_json") or ""), rc.status_code)
        rr = requests.post(f"{CORE}/task/{t['task_id']}/retry"); check("retry refused for completed task (409)", rr.status_code == 409, rr.status_code)
    post_state(status="WAITING", reason="new_patient")

    # ------------------------------------------------------------------ 5. all recordings vs ground truth
    log("== 5. all recordings through the full pipeline")
    from unified_app.modules.emr_groq import DIALOGUE_FIELD, CLINICAL_FIELDS
    for g, a in pairs:
        gt = read_gt(g); ref = norm("".join(x for _, x in gt))
        try:
            r = upload(a, a.name)
            t = wait_task(r.json()["task_id"], timeout=max(600, 3 * sf.info(str(a)).duration)) if r.ok else {"status": "UPLOAD_" + str(r.status_code), "error_message": r.text[:200]}
        except Exception as e:
            t = {"status": "EXC", "error_message": str(e)[:200]}
        R["task_ids"].append(t.get("task_id"))
        emr = json.loads(t.get("emr_json") or "{}") if t.get("emr_json") else {}
        meta = json.loads(t.get("stt_meta") or "{}") if t.get("stt_meta") else {}
        dlg = re.sub(r"(?m)^(เภสัชกร|ผู้ป่วย):\s*", "", emr.get(DIALOGUE_FIELD, ""))
        row = {"file": a.name, "dur_s": round(sf.info(str(a)).duration), "status": t["status"], "elapsed_s": t.get("elapsed"),
               "stt_s": meta.get("elapsed_s"), "cer_raw": round(lev(norm(t.get("raw_stt_text")), ref) / max(1, len(ref)), 3) if t.get("raw_stt_text") else None,
               "cer_final": round(lev(norm(t.get("stt_text")), ref) / max(1, len(ref)), 3) if t.get("stt_text") else None,
               "dict_changes": len(meta.get("changes") or []), "dialogue_preserved": norm(dlg) == norm(t.get("stt_text")) if emr else None,
               "fields_filled": sum(1 for f in CLINICAL_FIELDS if str(emr.get(f, "-")).strip() not in ("", "-")),
               "safety": emr.get("ข้อควรระวังด้านความปลอดภัยของยา", "-"), "emr_model": (emr.get("_meta") or {}).get("model"),
               "emr_s": (emr.get("_meta") or {}).get("elapsed_s"), "warnings": (emr.get("_meta") or {}).get("warnings"),
               "error": (t.get("error_message") or "")[:200], "task_id": t.get("task_id")}
        R["recordings"].append(row); log(json.dumps({k: row[k] for k in ("file", "dur_s", "status", "elapsed_s", "cer_raw", "cer_final", "fields_filled", "dialogue_preserved")}, ensure_ascii=False))
    ok = [x for x in R["recordings"] if x["status"] == "COMPLETED"]
    check("every recording completes", len(ok) == len(R["recordings"]), f"{len(ok)}/{len(R['recordings'])}")
    check("dialogue text always identical to transcript", all(x["dialogue_preserved"] for x in ok), [x["file"] for x in ok if not x["dialogue_preserved"]])

    # ------------------------------------------------------------------ 6. concurrency
    log("== 6. concurrency (3 uploads at once)")
    short = [a for _, a in pairs if 20 < sf.info(str(a)).duration < 150][:3]
    with ThreadPoolExecutor(3) as ex:
        tids = list(ex.map(lambda a: upload(a, "concurrent_" + a.name).json()["task_id"], short))
    res = [wait_task(x) for x in tids]; R["task_ids"] += tids
    check("3 concurrent uploads all complete", all(x["status"] == "COMPLETED" for x in res), [(x["status"], x.get("elapsed")) for x in res])

    # ------------------------------------------------------------------ 7. speaker roles (LLM) on clean text, rules off vs on
    log("== 7. speaker roles with the LLM (8 ground-truth cases)")
    import unified_app.modules.emr_groq as eg
    for g, _ in pairs[:8]:
        gt = read_gt(g)
        gold = [(r_, c) for r_, x in gt for c in norm(x)]
        res_ = {"file": g.name}
        for rules in (False, True):
            eg.USE_ROLE_RULES = rules
            try:
                out = eg.extract_emr(" ".join(x for _, x in gt))
            except Exception as e:
                res_[f"rules_{rules}"] = f"error {e}"[:120]; continue
            pr = []
            for ln in out[eg.DIALOGUE_FIELD].splitlines():
                m = re.match(r"^(เภสัชกร|ผู้ป่วย):\s*(.*)", ln)
                if m: pr += [("P" if m.group(1) == "เภสัชกร" else "C", c) for c in norm(m.group(2))]
            n = min(len(pr), len(gold))
            res_[f"acc_rules_{rules}"] = round(sum(pr[i][0] == gold[i][0] for i in range(n)) / max(1, n), 3)
            res_[f"same_text_rules_{rules}"] = "".join(c for _, c in pr) == "".join(c for _, c in gold)
        eg.USE_ROLE_RULES = False
        base = sum(1 for r_, _ in gold if r_ == "P") / max(1, len(gold))
        res_["baseline_all_pharmacist"] = round(base, 3)
        R["roles"].append(res_); log(json.dumps(res_, ensure_ascii=False))

    # ------------------------------------------------------------------ 8. dictionary on clean human text
    log("== 8. pharmacy dictionary on clean (human-typed) text")
    from unified_app.modules import pharmacy_dict as pdict
    check("pythainlp soundex available (layer 4 active)", pdict.thai_soundex is not None)
    for g, _ in pairs:
        for _, txt in read_gt(g):
            _, ch = pdict.correct_transcript(txt)
            for c_ in ch:
                if c_.get("tier") in ("4-phonetic", "1-safe", "2-ontology", "3-regex"):
                    R["dict_changes"].append({"file": g.name, "tier": c_["tier"], "orig": c_["original"], "new": c_["corrected"], "context": txt[:90]})
    log(f"dictionary changes on clean text: {len(R['dict_changes'])}")

    # ------------------------------------------------------------------ 9. PDF
    log("== 9. lab PDF")
    try:
        sys.path.insert(0, str(ROOT / "lab"))
        from lab.modules.emr_pdf import generate_emr_pdf, PharmaLogEMRPDF
        demo = {"ประวัติการแพ้ยา": "ไอบูโพรเฟน (ตาบวม)", "โรคประจำตัว": "ความดันโลหิตสูง", "ประวัติการจ่ายยา": "แอมโลดิพีน 5 มก.",
                "บันทึกทางการแพทย์": "ปวดฟันกรามล่างซ้าย 2 วัน เหงือกบวม ไม่มีไข้", "คำแนะนำจากเภสัช": "พาราเซตามอล 500 มก. ครั้งละ 1 เม็ด ทุก 6 ชั่วโมง เวลาปวด",
                "บทสนทนาที่จัดเรียงแล้ว": "เภสัชกร: เป็นมากี่วันแล้วครับ\nผู้ป่วย: สองวันค่ะ ปวดจี๊ดๆ"}
        data = generate_emr_pdf(demo, model_name="e2e test")
        (LOGS / "e2e_emr.pdf").write_bytes(data)
        shaping = getattr(PharmaLogEMRPDF(), "text_shaping", None)
        check("PDF generated", len(data) > 1000, f"{len(data)} bytes, text_shaping={bool(shaping)}")
        check("PDF Thai text shaping enabled", bool(shaping), shaping)
    except Exception:
        check("PDF generated", False, traceback.format_exc()[-400:])

    # ------------------------------------------------------------------ 10. pages render headless
    log("== 10. streamlit pages (headless)")
    try:
        from streamlit.testing.v1 import AppTest
        for page, backoffice in [("unified_app/pages/recorder.py", True), ("unified_app/pages/recorder.py", False),
                                 ("unified_app/pages/emr.py", True), ("unified_app/pages/settings.py", True),
                                 ("unified_app/pages/history.py", True)]:
            at = AppTest.from_file(str(ROOT / page), default_timeout=120)
            at.session_state["is_backoffice"] = backoffice
            at.run()
            errs = [str(e.value)[:250] for e in at.exception]
            check(f"page renders: {page} (backoffice={backoffice})", not errs, errs or "ok")
    except Exception:
        check("streamlit AppTest", False, traceback.format_exc()[-400:])

except SystemExit:
    pass
except Exception:
    check("unexpected crash in test script", False, traceback.format_exc()[-800:])
finally:
    for p in procs:
        try: p.terminate()
        except Exception: pass
    if orig_state is not None:
        state_file.write_text(orig_state, encoding="utf-8")
    if os.environ.get("E2E_KEEP_TASKS") != "1":  # do not leave test cases in the EMR page / consent tables
        try:
            import sqlite3
            time.sleep(1)
            ids = [t for t in R["task_ids"] if t]
            with sqlite3.connect(ROOT / "core_api" / "api_queue.db") as c:
                c.executemany("DELETE FROM tasks WHERE id=?", [(t,) for t in ids])
                c.execute("DELETE FROM tasks WHERE source='test'")
            for f in (ROOT / "core_api" / "temp_audio").glob("*"):
                if any(f.name.startswith(t) for t in ids):
                    f.unlink(missing_ok=True)
            with sqlite3.connect(ROOT / "record" / "pharmalog.db") as c:
                c.execute("DELETE FROM consent_events WHERE consent_id LIKE 'e2e-%'")
                c.execute("DELETE FROM consent_records WHERE consent_id LIKE 'e2e-%'")
            log(f"cleaned up {len(ids)} test tasks and e2e consent records (set E2E_KEEP_TASKS=1 to keep them)")
        except Exception as e:
            log("cleanup failed:", e)
    R["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (LOGS / "e2e_results.json").write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding="utf-8")
    L = ["# E2E report", f"{R['started']} → {R['finished']}  engine={R.get('engine')} device={R.get('device')}", "", "## Checks"]
    L += [f"- {'PASS' if c['ok'] else 'FAIL'} {c['name']} — {c['detail']}" for c in R["checks"]]
    L += ["", "## Recordings", "| file | dur s | status | total s | STT s | CER raw | CER final | fields | dialogue ok | safety |", "|---|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {x['file']} | {x['dur_s']} | {x['status']} | {x['elapsed_s']} | {x['stt_s']} | {x['cer_raw']} | {x['cer_final']} | {x['fields_filled']} | {x['dialogue_preserved']} | {str(x['safety'])[:60]} |" for x in R["recordings"]]
    L += ["", "## Speaker roles", *[json.dumps(x, ensure_ascii=False) for x in R["roles"]]]
    L += ["", f"## Dictionary changes on clean text ({len(R['dict_changes'])})", *[f"- {x['tier']}: {x['orig']} → {x['new']} ({x['context']})" for x in R["dict_changes"][:80]]]
    (LOGS / "e2e_report.md").write_text("\n".join(L), encoding="utf-8")
    log("E2E_DONE")
