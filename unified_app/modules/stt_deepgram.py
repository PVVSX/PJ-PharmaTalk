import os
import requests
from pathlib import Path
from groq import Groq
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KEY_FILE = ROOT / ".deepgram_api_key"

def get_deepgram_key():
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key and KEY_FILE.exists():
        api_key = KEY_FILE.read_text(encoding="utf-8").strip()
    return api_key

def _format_transcript_with_llm(raw_transcript: str) -> str:
    # Use Groq to map Speaker 0/1 to Pharmacist/Patient instantly
    try:
        from unified_app.modules.stt_groq import get_groq_client
        client = get_groq_client()
        prompt = f"""
นำบทสนทนานี้มาจัดเรียงใหม่ โดยพิจารณาจากบริบทว่า Speaker ไหนคือ "เภสัชกร" และ Speaker ไหนคือ "คนไข้"
ห้ามเพิ่มหรือลดเนื้อหา และไม่ต้องมีคำอธิบายเพิ่มเติมใดๆ ให้พิมพ์ผลลัพธ์ที่เป็นบทสนทนามาอย่างเดียว

บทสนทนา:
{raw_transcript}
"""
        # Using a fast standard Groq model for this simple task
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="openai/gpt-oss-120b", 
            temperature=0.1
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error formatting transcript: {e}")
        return raw_transcript


def transcribe_audio_deepgram(audio_path_or_bytes) -> str:
    """
    Transcribe audio using Deepgram API with Speaker Diarization.
    Returns a formatted string indicating [Speaker X]: message
    """
    api_key = get_deepgram_key()
    if not api_key:
        raise RuntimeError("ไม่พบ Deepgram API Key (ตั้งค่า DEEPGRAM_API_KEY หรือ .deepgram_api_key)")
        
    # We use Nova-2 model which supports Thai and Diarization
    url = "https://api.deepgram.com/v1/listen?diarize=true&language=th&model=nova-2&punctuate=true"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "audio/wav"
    }
    
    if isinstance(audio_path_or_bytes, (str, Path)):
        with open(audio_path_or_bytes, "rb") as f:
            audio_data = f.read()
    else:
        audio_data = audio_path_or_bytes
        
    response = requests.post(url, headers=headers, data=audio_data)
    response.raise_for_status()
    
    result = response.json()
    
    try:
        words = result['results']['channels'][0]['alternatives'][0]['words']
    except (KeyError, IndexError):
        return ""
        
    if not words:
        return ""
    
    # Group words by speaker
    formatted_transcript = ""
    current_speaker = None
    current_sentence = []
    
    for word_info in words:
        speaker = word_info.get('speaker', 0)
        word = word_info.get('punctuated_word', word_info.get('word', ''))
        
        if current_speaker is None:
            current_speaker = speaker
            
        if speaker != current_speaker:
            # Join words without spaces since it's Thai (Deepgram handles word boundaries, but joining with space is safer for readability, or we join without space if Deepgram outputs thai words)
            # Actually, Deepgram outputs segmented words, joining without space is better for Thai, but let's join with a small space for now or let LLM handle it.
            formatted_transcript += f"[Speaker {current_speaker}]: {''.join(current_sentence)}\n"
            current_speaker = speaker
            current_sentence = [word]
        else:
            current_sentence.append(word)
            
    if current_sentence:
        formatted_transcript += f"[Speaker {current_speaker}]: {''.join(current_sentence)}\n"
        
    # Send to LLM for instant formatting before returning
    if formatted_transcript.strip():
        final_transcript = _format_transcript_with_llm(formatted_transcript)
        return final_transcript
        
    return formatted_transcript
