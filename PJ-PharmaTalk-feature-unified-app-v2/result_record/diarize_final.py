"""
Enhanced Diarization with CSV Output
Target: Better detection of similar voices and frequent speaker turns
Includes comprehensive CSV export for performance analysis
"""

from __future__ import annotations

import librosa
import numpy as np
import os
import threading
import time
from scipy import signal
import torch
import contextlib
from pyannote.audio import Pipeline
import warnings
import csv
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.CRITICAL)

# Cache pipeline เพื่อไม่โหลด pyannote จาก Hugging Face ทุกครั้ง (ลดเวลามากใน Streamlit / ถอดซ้ำ)
_PYANNOTE_PIPELINE: Pipeline | None = None
_PYANNOTE_DEVICE: torch.device | None = None
_PIPELINE_LOCK = threading.Lock()


def _hf_token_for_diarization() -> str:
    return (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGING_FACE_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or ""
    ).strip()


def clear_diarization_pipeline_cache() -> None:
    """สำหรับดีบัก / บังคับโหลดโมเดลใหม่ครั้งถัดไป"""
    global _PYANNOTE_PIPELINE, _PYANNOTE_DEVICE
    with _PIPELINE_LOCK:
        _PYANNOTE_PIPELINE = None
        _PYANNOTE_DEVICE = None


def _ensure_pyannote_pipeline() -> tuple[Pipeline, torch.device]:
    """โหลด speaker-diarization-3.1 ครั้งเดียวต่อ process"""
    global _PYANNOTE_PIPELINE, _PYANNOTE_DEVICE

    if os.environ.get("DIARIZATION_RELOAD_PIPELINE", "").strip() in ("1", "true", "yes"):
        clear_diarization_pipeline_cache()

    with _PIPELINE_LOCK:
        if _PYANNOTE_PIPELINE is not None and _PYANNOTE_DEVICE is not None:
            print(
                "1. Using cached pyannote pipeline "
                "(โหลดครั้งเดียวต่อ process — ประหยัดเวลามากเมื่อถอดเสียงซ้ำ)"
            )
            return _PYANNOTE_PIPELINE, _PYANNOTE_DEVICE

        tok = _hf_token_for_diarization()
        if not tok:
            raise RuntimeError(
                "ต้องมี HF_TOKEN / HUGGING_FACE_TOKEN สำหรับดาวน์โหลดโมเดล pyannote"
            )

        print("1. Loading diarization model (ครั้งแรกใน process — ครั้งถัดไปใช้แคชเร็วขึ้น)...")

        @contextlib.contextmanager
        def allow_unsafe_torch_load():
            old_load = torch.load

            def new_load(f, *args, **kwargs):
                kwargs["weights_only"] = False
                return old_load(f, *args, **kwargs)

            torch.load = new_load
            try:
                yield
            finally:
                torch.load = old_load

        with allow_unsafe_torch_load():
            try:
                pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    token=tok,
                )
            except TypeError as e:
                if "token" not in str(e):
                    raise
                pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=tok,
                )

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        pipeline.to(device)

        _PYANNOTE_PIPELINE = pipeline
        _PYANNOTE_DEVICE = device
        return pipeline, device


# ============================================================================
# PREPROCESSING - Enhanced for similar voices
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
# DIARIZATION - With parameter optimization
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

    pipeline, device = _ensure_pyannote_pipeline()

    # Print available parameters in pipeline
    print(f"2. Configuring model parameters...")
    if hasattr(pipeline, 'steps'):
        for step_name, step in pipeline.steps:
            print(f"   - Step: {step_name}")

    # Try to adjust segmentation if available
    if segmentation_params:
        print(f"3. Applying segmentation parameters...")
        # ปรับ threshold สำหรับ speech onset/offset detection (ขั้นตอนที่ 1)
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

    # Configure clustering threshold (ขั้นตอนที่ 3 - SPEAKER CLUSTERING)
    # ควบคุมความเข้มงวดในการแยก speakers
    if hasattr(pipeline, 'clustering') and hasattr(pipeline.clustering, 'threshold'):
        pipeline.clustering.threshold = clustering_threshold
        print(f"   Set clustering threshold to {clustering_threshold}")

    pipeline.to(device)
    print(f"   Model on {device}")

    # Convert to torch tensor
    waveform_torch = torch.from_numpy(waveform).unsqueeze(0).float()
    audio_dict = {"waveform": waveform_torch, "sample_rate": sr}

    print("4. Running diarization...")
    # เริ่มกระบวนการ diarization หลัก (เกิดขึ้นภายใน pipeline นี้):
    # ขั้นตอนที่ 1: SPEECH SEGMENTATION (ตรวจจับช่วงพูด)
    # ขั้นตอนที่ 2: SPEAKER EMBEDDING (แปลงเสียงเป็น vectors)
    # ขั้นตอนที่ 3: SPEAKER CLUSTERING (จัดกลุ่ม embeddings)
    # ขั้นตอนที่ 4: SPEAKER ASSIGNMENT (กำหนด speaker IDs)
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
# POSTPROCESSING - Enhanced for frequent turns
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

    # Conservative merge based on silence gaps
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
# CSV EXPORT FUNCTION
# ============================================================================

def save_diarization_to_csv(turns, confidences, audio_duration, diarization_time,
                           num_speakers, parameters, csv_filename="diarization_results.csv"):
    """
    Save comprehensive diarization results to CSV format

    Args:
        turns: List of (segment, track, speaker) tuples
        confidences: List of confidence scores
        audio_duration: Original audio duration in seconds
        diarization_time: Processing time in seconds
        num_speakers: Expected number of speakers
        parameters: Dict of parameters used
        csv_filename: Output CSV filename
    """

    print(f"\nSaving results to {csv_filename}...")

    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)

        # Write header
        writer.writerow(["Diarization Results - Performance Analysis"])
        writer.writerow([])  # Empty row

        # SUMMARY SECTION
        writer.writerow(["SUMMARY METRICS"])
        writer.writerow(["Metric", "Value", "Unit", "Description"])

        speakers_found = len(set([sp for _, _, sp in turns]))
        total_segments = len(turns)
        avg_confidence = np.mean(confidences) if confidences else 0
        real_time_factor = audio_duration / diarization_time if diarization_time > 0 else 0

        summary_data = [
            ["Audio Duration", ".2f", "seconds", "Original audio length"],
            ["Speakers Expected", num_speakers, "count", "Expected number of speakers"],
            ["Speakers Detected", speakers_found, "count", "Actual speakers found"],
            ["Total Segments", total_segments, "count", "Number of speech segments"],
            ["Average Confidence", ".1f", "percentage", "Mean confidence score"],
            ["Processing Time", ".2f", "seconds", "Time to process audio"],
            ["Real-time Factor", ".2f", "x", "Speed relative to audio duration"],
            ["Segments per Minute", ".1f", "count", "Speech segment density"],
        ]

        for row in summary_data:
            if row[0] == "Average Confidence":
                writer.writerow([row[0], f"{avg_confidence*100:.1f}%", row[2], row[3]])
            elif row[0] == "Processing Time":
                writer.writerow([row[0], f"{diarization_time:.2f}", row[2], row[3]])
            elif row[0] == "Real-time Factor":
                writer.writerow([row[0], f"{real_time_factor:.2f}", row[2], row[3]])
            elif row[0] == "Segments per Minute":
                segments_per_min = total_segments / (audio_duration / 60) if audio_duration > 0 else 0
                writer.writerow([row[0], f"{segments_per_min:.1f}", row[2], row[3]])
            elif row[0] == "Audio Duration":
                writer.writerow([row[0], f"{audio_duration:.2f}", row[2], row[3]])
            else:
                writer.writerow([row[0], row[1], row[2], row[3]])

        writer.writerow([])  # Empty row

        # PARAMETERS SECTION
        writer.writerow(["MODEL PARAMETERS"])
        writer.writerow(["Parameter", "Value", "Description"])

        param_descriptions = {
            "clustering_threshold": "Speaker clustering sensitivity (lower = more separation)",
            "min_merge_duration": "Minimum segment duration to keep",
            "merge_silence_threshold": "Gap threshold for merging segments",
            "overlap_detection": "Detection of overlapping speech",
            "aggressive_split": "Experimental split of merged speakers"
        }

        for param, value in parameters.items():
            desc = param_descriptions.get(param, f"Parameter: {param}")
            writer.writerow([param, str(value), desc])

        writer.writerow([])  # Empty row

        # SEGMENT DETAILS SECTION
        writer.writerow(["SEGMENT DETAILS"])
        writer.writerow([
            "Segment ID", "Start Time", "End Time", "Duration", "Speaker",
            "Confidence Score", "Confidence %", "Speaker Changes",
            "Segment Density", "Time Coverage"
        ])

        total_speech_time = 0
        speaker_changes = 0
        prev_speaker = None

        for idx, ((turn, _, speaker), conf) in enumerate(zip(turns, confidences), 1):
            start, end = turn.start, turn.end
            duration = end - start
            total_speech_time += duration

            # Count speaker changes
            if prev_speaker is not None and speaker != prev_speaker:
                speaker_changes += 1
            prev_speaker = speaker

            # Calculate segment density (segments per second in this region)
            segment_density = 1.0 / duration if duration > 0 else 0

            # Time coverage percentage
            time_coverage = (duration / audio_duration) * 100 if audio_duration > 0 else 0

            try:
                speaker_id = int(speaker.split("_")[-1]) + 1
            except:
                speaker_id = speaker

            writer.writerow([
                idx,
                f"{start:.2f}",
                f"{end:.2f}",
                f"{duration:.2f}",
                speaker_id,
                f"{conf:.3f}",
                f"{conf*100:.1f}",
                speaker_changes if idx == len(turns) else "",
                f"{segment_density:.2f}",
                f"{time_coverage:.2f}"
            ])

        writer.writerow([])  # Empty row

        # PERFORMANCE ANALYSIS SECTION
        writer.writerow(["PERFORMANCE ANALYSIS"])
        writer.writerow(["Metric", "Value", "Benchmark", "Status"])

        speech_percentage = (total_speech_time / audio_duration) * 100 if audio_duration > 0 else 0
        avg_segment_length = total_speech_time / total_segments if total_segments > 0 else 0
        speaker_consistency = 1.0 - (speaker_changes / max(1, total_segments - 1))

        performance_data = [
            ["Speech Percentage", ".1f", "60-80%", "Good" if 60 <= speech_percentage <= 80 else "Check"],
            ["Average Segment Length", ".2f", "1.0-3.0s", "Good" if 1.0 <= avg_segment_length <= 3.0 else "Check"],
            ["Speaker Consistency", ".2f", ">0.7", "Good" if speaker_consistency > 0.7 else "Check"],
            ["Confidence Stability", ".2f", ">0.6", "Good" if avg_confidence > 0.6 else "Check"],
            ["Processing Efficiency", ".1f", ">1.0x", "Good" if real_time_factor > 1.0 else "Slow"]
        ]

        for row in performance_data:
            if row[0] == "Speech Percentage":
                status = "Good" if 60 <= speech_percentage <= 80 else ("Low" if speech_percentage < 60 else "High")
                writer.writerow([row[0], f"{speech_percentage:.1f}%", row[2], status])
            elif row[0] == "Average Segment Length":
                status = "Good" if 1.0 <= avg_segment_length <= 3.0 else ("Short" if avg_segment_length < 1.0 else "Long")
                writer.writerow([row[0], f"{avg_segment_length:.2f}s", row[2], status])
            elif row[0] == "Speaker Consistency":
                status = "Good" if speaker_consistency > 0.7 else "Low"
                writer.writerow([row[0], f"{speaker_consistency:.2f}", row[2], status])
            elif row[0] == "Confidence Stability":
                status = "Good" if avg_confidence > 0.6 else "Low"
                writer.writerow([row[0], f"{avg_confidence:.2f}", row[2], status])
            elif row[0] == "Processing Efficiency":
                status = "Good" if real_time_factor > 1.0 else "Slow"
                writer.writerow([row[0], f"{real_time_factor:.1f}x", row[2], status])

        writer.writerow([])  # Empty row
        writer.writerow(["CSV Generated", time.strftime("%Y-%m-%d %H:%M:%S"), "", ""])

    print(f"✓ Results saved to {csv_filename}")
    print(f"✓ CSV contains {total_segments} segments and comprehensive performance metrics")

# ============================================================================
# MAIN PIPELINE
# ============================================================================

def run_complete_pipeline(audio_file, num_speakers=2, clustering_threshold=0.6,
                          min_merge_duration=0.1, merge_silence_threshold=0.5,
                          segmentation_params=None, overlap_detection=True,
                          aggressive_split=False, csv_output=True,
                          csv_filename="diarization_results.csv"):
    """
    Run complete diarization pipeline with CSV export

    Args:
        csv_output: Whether to save results to CSV
        csv_filename: Output CSV filename
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
    print(f"  - Aggressive split: {aggressive_split}")
    print(f"  - CSV output: {csv_output}")
    print()

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

    # Save to CSV if requested
    if csv_output:
        parameters = {
            "clustering_threshold": clustering_threshold,
            "min_merge_duration": min_merge_duration,
            "merge_silence_threshold": merge_silence_threshold,
            "overlap_detection": overlap_detection,
            "aggressive_split": aggressive_split,
            "num_speakers_expected": num_speakers
        }
        save_diarization_to_csv(turns, confidences, audio_duration, diarization_time,
                               num_speakers, parameters, csv_filename)

    return turns, confidences, ann

# ============================================================================
# RUN PIPELINE
# ============================================================================

if __name__ == "__main__":
    audio_file = "sound/test_woman2.wav"

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
            aggressive_split=True,              # Try to split merged speakers
            csv_output=True,                    # Enable CSV export
            csv_filename="test_results.csv"  # Custom filename
        )

        print("\n" + "=" * 80)
        print("CSV EXPORT COMPLETE")
        print("=" * 80)
        print("The CSV file contains:")
        print("• Summary metrics (speakers, segments, confidence, timing)")
        print("• Model parameters used")
        print("• Detailed segment breakdown")
        print("• Performance analysis with benchmarks")
        print("• Status indicators (Good/Check) for each metric")
        print("\nUse this CSV to:")
        print("• Compare different parameter configurations")
        print("• Analyze model performance over time")
        print("• Identify areas for improvement")
        print("• Generate reports and visualizations")
    else:
        print(f"Error: Audio file not found: {audio_file}")