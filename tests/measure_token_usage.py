"""
วัดการใช้ token จริงของ Groq (openai/gpt-oss-120b) สำหรับการสกัด EMR ของ PharmaTalk

ใช้ prompt เดียวกับระบบจริง (unified_app.modules.emr_groq._build_prompt)
และใช้ผลดิบ Typhoon จาก batch_typhoon_full_results.json เป็น input

วิธีใช้ (รันในโฟลเดอร์ Pharmatalk_project):
    python measure_token_usage.py --limit 10
    python measure_token_usage.py --limit 10 --reasoning-effort low   # ทดสอบแบบลด reasoning

ผลลัพธ์: token_usage_measured.csv + สรุปบนหน้าจอ
หมายเหตุ: 10 เคสใช้โควตาฟรีประมาณ 10-15% ของ 200,000 tokens/วัน
"""
import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from groq import Groq  # noqa: E402
from unified_app.modules.emr_groq import _build_prompt, get_groq_key  # noqa: E402

MODEL = "openai/gpt-oss-120b"
PRICE_IN = 0.15 / 1_000_000   # USD ต่อ token (ตรวจราคาล่าสุดที่ console.groq.com)
PRICE_OUT = 0.60 / 1_000_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10, help="จำนวนเคสที่จะวัด")
    ap.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default=None)
    ap.add_argument("--pause", type=float, default=8.0, help="วินาทีที่รอระหว่างเคส (กัน TPM 8,000)")
    ap.add_argument("--out", default="token_usage_measured.csv")
    args = ap.parse_args()

    key = get_groq_key()
    if not key:
        sys.exit("ไม่พบ Groq API Key (GROQ_API_KEY หรือ .groq_api_key)")
    client = Groq(api_key=key)

    data = json.loads((ROOT / "batch_typhoon_full_results.json").read_text(encoding="utf-8"))
    cases = [(k, v.get("raw_transcript", "")) for k, v in data.items()
             if len(v.get("raw_transcript", "")) > 50]
    cases = cases[: args.limit]
    print(f"วัด {len(cases)} เคส, model={MODEL}, reasoning_effort={args.reasoning_effort or 'default'}")

    rows = []
    for i, (name, raw) in enumerate(cases, 1):
        conversation = "--- ส่วนที่ 1: ข้อความเนื้อหาภาษาไทย ---\n" + raw
        prompt = _build_prompt(conversation)
        kwargs = dict(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        if args.reasoning_effort:
            kwargs["reasoning_effort"] = args.reasoning_effort

        t0 = time.time()
        try:
            resp_raw = client.chat.completions.with_raw_response.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}] {name}: ERROR {e}")
            rows.append({"file": name, "error": str(e)[:300]})
            time.sleep(args.pause)
            continue
        latency = time.time() - t0
        resp = resp_raw.parse()
        h = resp_raw.headers
        u = resp.usage
        details = getattr(u, "completion_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", None) if details else None
        cost = u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT
        row = {
            "file": name,
            "transcript_chars": len(raw),
            "prompt_chars": len(prompt),
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "reasoning_tokens": reasoning if reasoning is not None else "",
            "total_tokens": u.total_tokens,
            "latency_sec": round(latency, 2),
            "cost_usd": round(cost, 7),
            "remaining_requests_day": h.get("x-ratelimit-remaining-requests", ""),
            "remaining_tokens_min": h.get("x-ratelimit-remaining-tokens", ""),
            "error": "",
        }
        rows.append(row)
        print(f"[{i}] {name}: in={u.prompt_tokens} out={u.completion_tokens} "
              f"(reasoning={reasoning}) total={u.total_tokens} {latency:.2f}s ${cost:.6f}")
        time.sleep(args.pause)

    fields = ["file", "transcript_chars", "prompt_chars", "prompt_tokens", "completion_tokens",
              "reasoning_tokens", "total_tokens", "latency_sec", "cost_usd",
              "remaining_requests_day", "remaining_tokens_min", "error"]
    with open(ROOT / args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    ok = [r for r in rows if not r.get("error")]
    if ok:
        def s(key):
            xs = [r[key] for r in ok]
            return f"min={min(xs)} median={statistics.median(xs)} max={max(xs)}"
        print("\n=== สรุป ===")
        print("prompt_tokens     ", s("prompt_tokens"))
        print("completion_tokens ", s("completion_tokens"))
        print("total_tokens      ", s("total_tokens"))
        print("latency_sec       ", s("latency_sec"))
        med = statistics.median(r["total_tokens"] for r in ok)
        print(f"Free tier (200,000 tokens/วัน) รองรับได้ประมาณ {int(200_000 // med)} เคส/วัน")
        print(f"ค่าใช้จ่ายเฉลี่ย ${statistics.mean(r['cost_usd'] for r in ok):.6f} ต่อเคส")
    print(f"\nบันทึกผลที่ {args.out}")


if __name__ == "__main__":
    main()
