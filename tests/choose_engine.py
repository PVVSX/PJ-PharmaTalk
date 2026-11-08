# -*- coding: utf-8 -*-
"""Summarise logs/stt_compare.jsonl and RECOMMEND an STT engine (logs/stt_decision.txt).

The project default is Typhoon Whisper Large v3 (PHARMALOG_STT_ENGINE=whisper in pharmalog.env).
This script never changes pharmalog.env by itself; run it with --apply to write the recommendation.
Recommendation rule: prefer Whisper unless Realtime is clearly more accurate (>=10% lower mean CER after the
dictionary on the same files) or Whisper is too slow for a pharmacy counter (RTF > 0.6, i.e. 3-min talk > 1.8 min).
"""
import json, statistics, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = ROOT / "logs" / "stt_compare.jsonl"
rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()] if src.exists() else []
rt = {r["file"]: r for r in rows if r["engine"] == "realtime" and "cer_dict" in r}
wh = {r["file"]: r for r in rows if r["engine"] == "whisper" and "cer_dict" in r}
skipped = [r for r in rows if r["engine"] in ("whisper_skipped", "whisper_stopped")]
common = sorted(set(rt) & set(wh))
lines = []
if len(common) < 5:
    choice = None
    lines.append(f"มีไฟล์ที่เทียบได้ครบสองโมเดลแค่ {len(common)} ไฟล์ — ยังสรุปไม่ได้")
    for r in skipped[-1:]:
        lines.append(f"Whisper ไม่ได้ทดสอบ: {r.get('why') or r}")
else:
    c_rt = statistics.mean(rt[f]["cer_dict"] for f in common); c_wh = statistics.mean(wh[f]["cer_dict"] for f in common)
    m_rt = statistics.median(rt[f]["cer_dict"] for f in common); m_wh = statistics.median(wh[f]["cer_dict"] for f in common)
    rtf_wh = sum(wh[f]["elapsed"] for f in common) / max(1e-9, sum(wh[f]["dur"] for f in common))
    rtf_rt = sum(rt[f]["elapsed"] for f in common) / max(1e-9, sum(rt[f]["dur"] for f in common))
    rt_clearly_better = c_rt <= c_wh * 0.9
    wh_fast = rtf_wh <= 0.6
    choice = "realtime" if (rt_clearly_better or not wh_fast) else "whisper"
    lines += [f"files compared: {len(common)}",
              f"realtime: mean CER {c_rt:.3f} (median {m_rt:.3f}), RTF {rtf_rt:.3f}",
              f"whisper : mean CER {c_wh:.3f} (median {m_wh:.3f}), RTF {rtf_wh:.3f} "
              f"(model {next(iter(wh.values())).get('model', '?')}, device {next(iter(wh.values())).get('device')})",
              f"realtime clearly more accurate: {rt_clearly_better}; whisper fast enough: {wh_fast}"]
    if any(rt[f]["cer_dict"] > 1 for f in common):
        lines.append("หมายเหตุ: มีไฟล์ที่ CER > 1 (เฉลยใน ground_truth ไม่ครบทั้งบทสนทนา) ให้ดูค่ามัธยฐานประกอบ")
lines.append(f"RECOMMENDATION: {choice or 'คงค่าเดิม (whisper)'}")
env = ROOT / "pharmalog.env"
current = next((l.split("=", 1)[1] for l in (env.read_text(encoding="utf-8").splitlines() if env.exists() else [])
                if l.startswith("PHARMALOG_STT_ENGINE=")), "whisper")
lines.append(f"pharmalog.env ตอนนี้: PHARMALOG_STT_ENGINE={current}")
if choice and "--apply" in sys.argv:
    kept = [l for l in (env.read_text(encoding="utf-8").splitlines() if env.exists() else [])
            if not l.startswith(("PHARMALOG_STT_ENGINE=", "PHARMALOG_WHISPER_DEVICE="))]
    kept.append(f"PHARMALOG_STT_ENGINE={choice}")
    if choice == "whisper":
        kept.append(f"PHARMALOG_WHISPER_DEVICE={next(iter(wh.values())).get('device', 'cpu')}")
    env.write_text("\n".join(kept) + "\n", encoding="utf-8")
    lines.append(f"APPLIED: เขียน PHARMALOG_STT_ENGINE={choice} ลง pharmalog.env แล้ว")
elif choice and choice != current:
    lines.append("ยังไม่ได้เปลี่ยน pharmalog.env (รัน python tests/choose_engine.py --apply ถ้าต้องการใช้ตามคำแนะนำ)")
(ROOT / "logs").mkdir(exist_ok=True)
(ROOT / "logs" / "stt_decision.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
