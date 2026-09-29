# 🤖 Models & APIs Reference (PharmaTalk)

เอกสารฉบับนี้ใช้สำหรับรวบรวมข้อมูลโมเดล AI และ API ทั้งหมดที่ถูกเรียกใช้งานภายในโปรเจกต์ PharmaTalk เพื่อให้ง่ายต่อการติดตามและแก้ไข 
*(หากมีการเพิ่มโมเดลใหม่หรือเปลี่ยน API ให้มาอัปเดตไฟล์นี้ด้วยเสมอ)*

---

## 1. Speech-to-Text (STT) Models
โมเดลสำหรับใช้ถอดเสียงพูดภาษาไทยให้กลายเป็นข้อความ (Transcript)

| ชื่อโมเดล | ผู้ให้บริการ / ผู้พัฒนา | รูปแบบการรัน | การแยกผู้พูด (Diarization) | ตำแหน่งเก็บ Key | สถานะการใช้งานปัจจุบัน |
|:---|:---|:---|:---|:---|:---|
| **Typhoon ASR**<br>`typhoon-asr-realtime` | SCB10X | **Local** (NeMo) | ❌ ไม่รองรับ | *ไม่มี (รันในเครื่อง)* | 🟢 **ใช้งานเป็นหลัก** |
| **Deepgram** | Deepgram API | Cloud API | ✅ รองรับ | `.deepgram_api_key` | ⚪️ ปิดใช้งานชั่วคราว |
| **Groq STT**<br>`whisper-large-v3` | Groq API | Cloud API | ❌ ไม่รองรับ | `.groq_api_key` | ⚪️ ปิดใช้งานชั่วคราว |

*(การตั้งค่าว่าจะใช้โมเดล STT ตัวไหน สามารถเข้าไปเปิด-ปิด `True`/`False` ได้ที่ไฟล์ `core_api/main.py`)*

---

## 2. LLMs / Generative AI (EMR Extraction)
โมเดลภาษาขนาดใหญ่ที่ใช้สำหรับอ่านข้อความ Transcript แล้วสกัด/จัดเรียงข้อมูลเข้าฟอร์มเวชระเบียน (EMR) โดยอัตโนมัติ

| ชื่อโมเดล | ไฟล์ Module ที่ใช้งาน | ผู้ให้บริการ | ตำแหน่งเก็บ Key | หน้าที่หลัก | สถานะการใช้งานปัจจุบัน |
|:---|:---|:---|:---|:---|:---|
| **Llama 3.1 70B**<br>`llama-3.1-70b-versatile` | `emr_groq.py` | Groq API | `.groq_api_key` | อ่านข้อความและสร้าง JSON เวชระเบียน (EMR) | 🟢 **ใช้งานเป็นหลัก** |
| **Gemini 1.5 Pro** | `emr_gemini.py` | Google AI | `.gemini_api_key` | โมเดลสำรอง / ใช้ในงานจัดหมวดหมู่เก่า (text_classified) | ⚪️ สแตนด์บาย |
| **Azure OpenAI** | `emr_azure.py` | Microsoft Azure | Environment Var. | โมเดลสำรอง | ⚪️ ไม่ได้เรียกใช้ |
| **DashScope (Qwen)** | *(เก่า)* | Alibaba Cloud | `.dashscope_api_key` | ทดสอบงาน NLP | ⚪️ เลิกใช้งาน |

---

## 3. Database & Storage APIs
ระบบฐานข้อมูลและที่เก็บไฟล์บน Cloud

| บริการที่ใช้ | หน้าที่หลัก | การยืนยันตัวตน (Auth) | สถานะ |
|:---|:---|:---|:---|
| **Google Cloud Firestore** (Firebase) | เก็บสถานะงาน, ข้อความถอดเสียง, และผลลัพธ์ EMR (JSON) ของคนไข้ | ใช้ Service Account JSON (`core_api/firebase_config.py`) | 🟢 ทำงานปกติ |
| **Google Cloud Storage** (Firebase) | แบ็คอัปไฟล์เสียง `.wav` ขี้น Cloud ไว้ที่โฟลเดอร์ `recordings/` | ใช้ Service Account JSON เดียวกัน | 🔴 ขัดข้อง (หา Bucket ไม่เจอ) |

---

## 🔒 กฎการจัดการ API Keys
1. **ห้ามนำ API Key ระบุลงไปในไฟล์โค้ด (Hardcode) เด็ดขาด** 
2. ให้บันทึก API Key ไว้ในไฟล์ `.txt` หรือไฟล์ซ่อนที่ไม่มีนามสกุล (เช่น `.groq_api_key`) ซึ่งได้ตั้งค่า `.gitignore` ไว้แล้ว ป้องกันการเผลอ Push ขึ้น GitHub
3. เวลาโค้ดดึงไปใช้ ให้เปิดอ่านจากไฟล์นั้นๆ หรือใช้ท่าดึงจาก `os.environ` 

---
*อัปเดตล่าสุด: 29 กันยายน 2026*
