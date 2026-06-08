# -*- coding: utf-8 -*-
"""ตรวจสอบว่าไฟล์เสียงใน sound/ ไฟล์ไหนยังไม่มี report ใน report/"""
import os
import sys

# ให้ Windows แสดงผลไทยได้
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

audio_dir = "sound"
report_dir = "report"

wav_files = sorted([f for f in os.listdir(audio_dir) if f.endswith(".wav")])
have_report = set()
for f in os.listdir(report_dir):
    if f.endswith(".txt") and f != "summary_report.txt":
        have_report.add(os.path.splitext(f)[0])

missing = []
for wav in wav_files:
    base = os.path.splitext(wav)[0]
    if base not in have_report:
        missing.append(wav)

print(f"Wav in sound: {len(wav_files)} | Have report: {len(wav_files) - len(missing)} | Missing report: {len(missing)}")
if missing:
    print("Missing report (will be processed):")
    for i, f in enumerate(missing, 1):
        print(f"  {i:2}. {f}")
