import os
from pathlib import Path
from groq import Groq

ROOT = Path(__file__).resolve().parent.parent.parent
KEY_FILE = ROOT / ".groq_api_key"

def get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key and KEY_FILE.exists():
        api_key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not api_key:
        raise RuntimeError("ไม่พบ Groq API Key (ตั้งค่า GROQ_API_KEY หรือ .groq_api_key)")
    return Groq(api_key=api_key)

def _format_transcript_with_llm(raw_transcript: str) -> str:
    # Use Groq to map and organize Pharmacist/Patient instantly from raw Whisper text
    try:
        client = get_groq_client()
        prompt = f"""
นำบทสนทนานี้มาจัดเรียงใหม่ แยกประโยคตามบริบทว่าใครคือ "เภสัชกร" และใครคือ "คนไข้"
โดยพิมพ์ผลลัพธ์ที่เป็นบทสนทนามาอย่างเดียว ห้ามเพิ่มเนื้อหา ห้ามสรุป

บทสนทนา:
{raw_transcript}
"""
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="openai/gpt-oss-120b", 
            temperature=0.1
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error formatting transcript: {e}")
        return raw_transcript


def transcribe_audio_groq(audio_path_or_bytes, filename="audio.wav") -> str:
    """
    Transcribe audio using Groq Whisper model.
    Accepts either a file path or direct bytes.
    """
    client = get_groq_client()
    
    if isinstance(audio_path_or_bytes, (str, Path)):
        with open(audio_path_or_bytes, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(filename, file.read()),
                model="whisper-large-v3-turbo",
                prompt="นี่คือบทสนทนาภาษาไทยระหว่างเภสัชกรกับคนไข้",
                response_format="json",
                language="th"
            )
            return _format_transcript_with_llm(transcription.text)

            
    elif isinstance(audio_path_or_bytes, bytes):
        transcription = client.audio.transcriptions.create(
            file=(filename, audio_path_or_bytes),
            model="whisper-large-v3-turbo",
            prompt="นี่คือบทสนทนาภาษาไทยระหว่างเภสัชกรกับคนไข้",
            response_format="json",
            language="th"
        )
        return _format_transcript_with_llm(transcription.text)

    return ""
