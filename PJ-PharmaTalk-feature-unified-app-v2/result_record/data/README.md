# data — ข้อมูลทดสอบ

| โฟลเดอร์ | เนื้อหา | ใช้กับ |
|----------|---------|--------|
| `voice/` | ไฟล์เสียง WAV 45 ไฟล์ | `speech_to_text.py`, diarization |
| `text/` | transcript ที่พิมพ์ด้วยมือ 17 ไฟล์ | `classify_gemini_extract.py --from-data text` |
| `text_from_speech/` | transcript จาก ASR 11 ไฟล์ | `classify_gemini_extract.py --from-data text_from_speech` |
| `บท500_split/` | บทสนทนา 500 เคส (`case_001`–`case_500`) | `classify_gemini_extract.py --from-data บท500_split` |
