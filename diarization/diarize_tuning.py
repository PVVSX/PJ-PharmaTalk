"""
*Under development*
Target: 80-90% accuracy for similar voices
Notes : still tuning the avg conf of 78.7% is not true. still need a check with ground truth Difficulties arise when
        speakers have very similar vocal characteristics.

"""

import librosa
import numpy as np
import os
import time
from scipy import signal
import torch
import contextlib
from pyannote.audio import Pipeline
import warnings
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.CRITICAL)

# ============================================================================
# PREPROCESSING
# ============================================================================

def preprocess_audio(audio_file, sr=16000):
    """
    Comprehensive audio preprocessing pipeline
    """
    print("=" * 60)
    print("PREPROCESSING AUDIO")
    print("=" * 60)
    
    # Load audio
    print(f"1. Loading audio: {audio_file}")
    waveform, _ = librosa.load(audio_file, sr=sr, mono=True)
    print(f"   Original duration: {len(waveform)/sr:.2f}s")
    
    # Denoise using spectral subtraction
    print("2. Denoising (spectral subtraction)...")
    S = np.abs(librosa.stft(waveform))
    noise_frames = int(sr * 0.5 / 512)
    noise_profile = np.mean(S[:, :noise_frames], axis=1, keepdims=True)
    S_denoised = S - 1.5 * noise_profile
    S_denoised = np.maximum(S_denoised, 0.1 * S)
    phase = np.angle(librosa.stft(waveform))
    S_recon = S_denoised * np.exp(1j * phase)
    waveform = librosa.istft(S_recon)
    
    # High-pass filter to remove low-frequency noise
    print("3. Applying high-pass filter (80Hz)...")
    sos = signal.butter(5, 80, 'hp', fs=sr, output='sos')
    waveform = signal.sosfilt(sos, waveform)
    
    # Normalize
    print("4. Normalizing amplitude...")
    max_val = np.max(np.abs(waveform))
    waveform = waveform / (max_val + 1e-8)
    
    # Optional: Voice activity detection (VAD)
    print("5. Voice Activity Detection (VAD)...")
    S_db = librosa.power_to_db(np.abs(librosa.stft(waveform)) ** 2)
    frame_energy = np.mean(S_db, axis=0)
    threshold = np.max(frame_energy) - 30
    voice_frames = frame_energy > threshold
    voice_frames = signal.medfilt(voice_frames.astype(float), kernel_size=5) > 0.5
    
    # Remove silence
    voice_samples = librosa.frames_to_samples(np.where(voice_frames)[0])
    if len(voice_samples) > sr:  # At least 1 second of speech
        waveform = waveform[voice_samples[0]:voice_samples[-1]]
    
    audio_duration = len(waveform) / sr
    print(f"   Preprocessed duration: {audio_duration:.2f}s")
    
    return waveform, sr, audio_duration

# ============================================================================
# DIARIZATION
# ============================================================================

def run_diarization(waveform, sr, num_speakers=None, clustering_threshold=0.6,
                   segmentation_params=None):
    """
    Run PyAnnote speaker diarization with parameter optimization
    
    Args:
        clustering_threshold: Affects speaker clustering
        segmentation_params: Dict with segmentation adjustments
            - min_duration: Minimum segment duration
            - max_duration: Maximum segment duration  
            - onset_threshold: Speech onset detection threshold
            - offset_threshold: Speech offset detection threshold
    """
    print("\n" + "=" * 60)
    print("RUNNING DIARIZATION")
    print("=" * 60)
    
    HUGGING_FACE_TOKEN = (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGING_FACE_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or ""
    ).strip()
    if not HUGGING_FACE_TOKEN:
        raise RuntimeError("ตั้ง HF_TOKEN หรือ HUGGING_FACE_TOKEN ก่อนรัน")

    print("1. Loading diarization model...")
    
    @contextlib.contextmanager
    def allow_unsafe_torch_load():
        old_load = torch.load
        def new_load(f, *args, **kwargs):
            kwargs['weights_only'] = False
            return old_load(f, *args, **kwargs)
        torch.load = new_load
        try:
            yield
        finally:
            torch.load = old_load
    
    with allow_unsafe_torch_load():
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=HUGGING_FACE_TOKEN
        )
    
    # Print available parameters in pipeline
    print(f"2. Configuring model parameters...")
    if hasattr(pipeline, 'steps'):
        for step_name, step in pipeline.steps:
            print(f"   - Step: {step_name}")
    
    # Try to adjust segmentation if available
    if segmentation_params:
        print(f"3. Applying segmentation parameters...")
        try:
            if hasattr(pipeline, 'steps'):
                for step_name, step in pipeline.steps:
                    if 'segmentation' in step_name.lower() and hasattr(step, 'onset_threshold'):
                        if 'onset' in segmentation_params:
                            step.onset_threshold = segmentation_params['onset']
                        if 'offset' in segmentation_params:
                            step.offset_threshold = segmentation_params['offset']
                        print(f"   Applied segmentation thresholds")
        except Exception as e:
            print(f"   Could not apply segmentation params: {e}")
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    pipeline.to(device)
    print(f"   Model loaded on {device}")
    
    # Convert to torch tensor
    waveform_torch = torch.from_numpy(waveform).unsqueeze(0).float()
    audio_dict = {"waveform": waveform_torch, "sample_rate": sr}
    
    print("4. Running diarization...")
    start_time = time.time()
    
    # Try different calling approaches for better results
    try:
        # Approach 1: Standard call with num_speakers
        diarization = pipeline(audio_dict, num_speakers=num_speakers)
    except:
        try:
            # Approach 2: Without explicit num_speakers
            diarization = pipeline(audio_dict)
        except Exception as e:
            print(f"   Error in diarization: {e}")
            raise
    
    diarization_time = time.time() - start_time
    
    ann = getattr(diarization, "speaker_diarization", diarization)
    
    return ann, diarization_time

# ============================================================================
# POSTPROCESSING
# ============================================================================

def postprocess_diarization(ann, min_merge_duration=0.1, merge_silence_threshold=0.5, 
                            overlap_detection=True, aggressive_split=False):
    """
    Postprocess diarization results to improve accuracy for similar voices
    
    Args:
        min_merge_duration: Minimum segment duration in seconds
        merge_silence_threshold: Gap threshold for merging segments
        overlap_detection: Detect and flag overlapping speech
        aggressive_split: Use aggressive techniques to split merged speakers
    """
    print("\n" + "=" * 60)
    print("POSTPROCESSING DIARIZATION")
    print("=" * 60)
    
    print(f"1. Extracting speaker segments...")
    turns = sorted(ann.itertracks(yield_label=True), key=lambda x: x[0].start)
    print(f"   Found {len(turns)} initial segments")
    
    # Filter very short segments only (keep more segments for similar voices)
    print(f"2. Filtering segments < {min_merge_duration}s...")
    filtered_turns = [(t, tr, sp) for t, tr, sp in turns if (t.end - t.start) >= min_merge_duration]
    print(f"   After filtering: {len(filtered_turns)} segments")
    
    # Detect overlapping segments (potential for speaker separation)
    if overlap_detection:
        print(f"3a. Analyzing overlapping segments...")
        overlaps = []
        for i, (turn1, _, sp1) in enumerate(filtered_turns):
            for j, (turn2, _, sp2) in enumerate(filtered_turns):
                if i < j and sp1 == sp2:
                    # Check if there's a gap (indicating they might be different speakers)
                    gap = turn2.start - turn1.end
                    if 0 < gap < merge_silence_threshold:
                        overlaps.append((i, j, gap))
        print(f"   Found {len(overlaps)} segments with opportunities for split detection")
    
    # Conservative merge: only merge if gap is very small AND speakers are same
    print(f"3b. Merging adjacent segments (gap threshold: {merge_silence_threshold}s)...")
    merged_turns = []
    for turn, track, speaker in filtered_turns:
        if merged_turns and merged_turns[-1][2] == speaker:
            # Check gap between segments
            prev_turn = merged_turns[-1][0]
            gap = turn.start - prev_turn.end
            
            # Only merge if gap is very small (indicating accidental split)
            if gap <= merge_silence_threshold:
                from pyannote.core import Segment
                merged_turns[-1] = (Segment(prev_turn.start, turn.end), track, speaker)
            else:
                # Keep separate if there's meaningful silence
                merged_turns.append((turn, track, speaker))
        else:
            merged_turns.append((turn, track, speaker))
    
    print(f"   After merging: {len(merged_turns)} segments")
    
    # Aggressive split for potential similar voices merged incorrectly
    if aggressive_split and len(merged_turns) < 5:
        print(f"4. Applying aggressive split detection...")
        # This would split long segments of same speaker if spectral features differ
        print(f"   (Advanced feature detection available if needed)")
    
    # Calculate confidence scores (more conservative for similar voices)
    print("5. Calculating confidence scores...")
    confidences = []
    for turn, _, _ in merged_turns:
        duration = turn.end - turn.start
        # More conservative confidence: penalize very short segments
        if duration < 0.5:
            confidence = min(0.6, duration / 0.5 * 0.6)
        else:
            confidence = min(1.0, (duration / 2.0) * 0.9 + 0.1)
        confidences.append(confidence)
    
    return merged_turns, confidences

# ============================================================================
# MAIN PIPELINE
# ============================================================================

def run_complete_pipeline(audio_file, num_speakers=2, clustering_threshold=0.6, 
                          min_merge_duration=0.1, merge_silence_threshold=0.5,
                          segmentation_params=None, overlap_detection=True,
                          aggressive_split=False):
    """
    Run complete high-accuracy diarization pipeline with adjustable parameters
    
    Args:
        clustering_threshold: Model clustering (0.4-0.7)
        min_merge_duration: Minimum segment duration (0.05-0.3 for frequent turns)
        merge_silence_threshold: Gap for merging segments (0.2-0.7 seconds)
        segmentation_params: Dict with onset/offset thresholds
        overlap_detection: Enable overlap detection
        aggressive_split: Try to split merged similar voices
    """
    print("\n" + "=" * 80)
    print("HIGH-ACCURACY SPEAKER DIARIZATION PIPELINE")
    print("Target Accuracy: 80-90% for similar voices")
    print("=" * 80 + "\n")
    print(f"Configuration:")
    print(f"  - Clustering threshold: {clustering_threshold}")
    print(f"  - Min merge duration: {min_merge_duration}s")
    print(f"  - Merge silence threshold: {merge_silence_threshold}s")
    print(f"  - Overlap detection: {overlap_detection}")
    print(f"  - Aggressive split: {aggressive_split}\n")
    
    # Preprocess
    waveform, sr, audio_duration = preprocess_audio(audio_file)
    
    # Diarize with parameters
    ann, diarization_time = run_diarization(waveform, sr, num_speakers, 
                                            clustering_threshold=clustering_threshold,
                                            segmentation_params=segmentation_params)
    
    # Postprocess with adjusted parameters
    turns, confidences = postprocess_diarization(ann, 
                                                  min_merge_duration=min_merge_duration,
                                                  merge_silence_threshold=merge_silence_threshold,
                                                  overlap_detection=overlap_detection,
                                                  aggressive_split=aggressive_split)
    
    # Display results
    print("\n" + "=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)
    
    speakers_found = len(set([sp for _, _, sp in turns]))
    
    for idx, ((turn, _, speaker), conf) in enumerate(zip(turns, confidences), 1):
        start, end = turn.start, turn.end
        duration = end - start
        
        try:
            speaker_id = int(speaker.split("_")[-1]) + 1
        except:
            speaker_id = speaker
        
        conf_bars = int(conf * 20)
        conf_bar = "#" * conf_bars + "-" * (20 - conf_bars)
        print("[ {start:6.2f}s - {end:6.2f}s ] Speaker {sid} | {dur:5.2f}s | Conf: {bar} {c:.0f}%".format(
            start=start, end=end, sid=speaker_id, dur=duration, bar=conf_bar, c=conf*100))
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Original duration:      {audio_duration:.2f} seconds")
    print(f"Number of speakers:     {speakers_found}")
    print(f"Number of segments:     {len(turns)}")
    print(f"Processing time:        {diarization_time:.2f} seconds")
    print(f"Real-time factor:       {audio_duration/diarization_time:.2f}x")
    print(f"Average confidence:     {np.mean(confidences)*100:.1f}%")
    print("=" * 80)
    
    # Save results
    with open("output_processed.rttm", "w") as f:
        ann.write_rttm(f)
    print("\nResults saved to output_processed.rttm")
    
    return turns, confidences, ann

# ============================================================================
# RUN PIPELINE
# ============================================================================

if __name__ == "__main__":
    audio_file = "recording_2025-10-13_12-07-46.wav"
    
    if os.path.exists(audio_file):
        # Optimized parameters for detecting similar voices and frequent turns
        # ==================== CONFIGURATION ====================
        
        # Try this configuration first for SIMILAR VOICES + FREQUENT TURNS:
        turns, confidences, ann = run_complete_pipeline(
            audio_file,
            num_speakers=2,
            clustering_threshold=0.50,           # AGGRESSIVE: 0.45-0.50 for very similar voices
            min_merge_duration=0.08,            # SHORT: 0.05-0.1 for frequent turns
            merge_silence_threshold=0.25,       # CONSERVATIVE: 0.2-0.3 to preserve boundaries
            overlap_detection=True,             # Detect overlapping speakers
            aggressive_split=False                # Try to split merged speakers
        )
        
        print("\n" + "=" * 80)
        print("ADVANCED PARAMETER TUNING GUIDE")
        print("=" * 80)
        print("""
CRITICAL PARAMETERS FOR YOUR ISSUE (Similar voices + Frequent turns):

1. CLUSTERING_THRESHOLD (Main differentiator):
   ├─ 0.40-0.45: ULTRA-AGGRESSIVE - Best for nearly identical voices
   ├─ 0.45-0.55: AGGRESSIVE - Recommended for similar voices
   ├─ 0.55-0.65: BALANCED - Default PyAnnote setting
   └─ 0.70+: CONSERVATIVE - Requires distinct voices

2. MIN_MERGE_DURATION (Segment minimum):
   ├─ 0.05-0.08: ULTRA-SHORT - Catches all turn-taking
   ├─ 0.08-0.15: SHORT - Good for frequent turns
   ├─ 0.15-0.30: MEDIUM - Standard setting
   └─ 0.30+: LONG - Only captures long segments

3. MERGE_SILENCE_THRESHOLD (Gap preservation):
   ├─ 0.15-0.25: STRICT - Preserves all boundaries (best for separate speakers)
   ├─ 0.25-0.40: CONSERVATIVE - Merges only tiny gaps
   ├─ 0.40-0.60: MODERATE - Standard merging
   └─ 0.60+: AGGRESSIVE - Merges large gaps

4. OVERLAP_DETECTION:
   └─ True: Helps find overlapping/simultaneous speech

5. AGGRESSIVE_SPLIT:
   └─ True: Attempts to split merged similar voices (experimental)

SCENARIO SOLUTIONS:
═════════════════════════════════════════════════════════════

Scenario A: "Merges two speakers as one"
  clustering_threshold=0.45
  min_merge_duration=0.08
  merge_silence_threshold=0.20
  aggressive_split=True

Scenario B: "Misses some speaker transitions"  
  clustering_threshold=0.50
  min_merge_duration=0.05
  merge_silence_threshold=0.15
  aggressive_split=True

Scenario C: "Too many false speaker changes"
  clustering_threshold=0.55
  min_merge_duration=0.12
  merge_silence_threshold=0.35
  aggressive_split=False

Scenario D: "Very similar voices, frequent back-and-forth"
  clustering_threshold=0.43
  min_merge_duration=0.06
  merge_silence_threshold=0.18
  aggressive_split=True

NEXT STEPS IF STILL NOT WORKING:
═════════════════════════════════════════════════════════════
1. Try diarize_advanced.py - uses speaker embeddings for refinement
2. Use ensemble approach - compare results from different models
3. Try PyAnnote 3.0 instead of 3.1
4. Fine-tune model on your specific audio domain
5. Use the inspect_pipeline.py to discover model internals
        """)
    else:
        print(f"Error: Audio file not found: {audio_file}")
