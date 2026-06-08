"""
การประเมินผลการแบ่งคำ (Word Segmentation Evaluation)
เปรียบเทียบผลการแบ่งคำกับ Ground Truth
"""
import os
import sys
from typing import List, Tuple, Dict
from collections import Counter
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import numpy as np

# ตั้งค่า encoding สำหรับ Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


def read_segmented_text(file_path: str) -> str:
    """
    อ่านผลการแบ่งคำจากไฟล์ nlp_result
    
    Args:
        file_path: Path ของไฟล์ nlp_result
        
    Returns:
        str: ข้อความที่แบ่งคำแล้ว (แยกด้วยช่องว่าง)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # หาบรรทัดที่มี "ผลการแบ่งคำ:" (บรรทัดที่ 7, index 6)
        # ผลการแบ่งคำจะอยู่บรรทัดถัดไป (บรรทัดที่ 9, index 8)
        if len(lines) >= 9:
            segmented_text = lines[8].strip()  # บรรทัดที่ 9 (index 8)
            return segmented_text
        else:
            print(f"⚠️ ไฟล์ {file_path} ไม่มีรูปแบบที่ถูกต้อง")
            return ""
    except Exception as e:
        print(f"✗ เกิดข้อผิดพลาดในการอ่านไฟล์ {file_path}: {str(e)}")
        return ""


def read_groundtruth(file_path: str) -> str:
    """
    อ่าน Ground Truth จากไฟล์
    
    Args:
        file_path: Path ของไฟล์ groundtruth
        
    Returns:
        str: ข้อความ Ground Truth ที่แบ่งคำแล้ว (แยกด้วยช่องว่าง)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            return content
    except Exception as e:
        print(f"✗ เกิดข้อผิดพลาดในการอ่านไฟล์ {file_path}: {str(e)}")
        return ""


def tokenize_text(text: str) -> List[str]:
    """
    แบ่งข้อความเป็นรายการคำ
    
    Args:
        text: ข้อความที่แบ่งคำแล้ว (แยกด้วยช่องว่าง)
        
    Returns:
        List[str]: รายการคำ
    """
    if not text:
        return []
    # แบ่งด้วยช่องว่างและกรองคำว่าง
    words = [word.strip() for word in text.split() if word.strip()]
    return words


def calculate_metrics(predicted_words: List[str], groundtruth_words: List[str]) -> Dict:
    """
    คำนวณ metrics สำหรับการประเมินผล
    
    Args:
        predicted_words: คำที่แบ่งจาก NLP
        groundtruth_words: คำจาก Ground Truth
        
    Returns:
        Dict: Dictionary ที่มี metrics ต่างๆ
    """
    # แปลงเป็น Counter เพื่อนับจำนวนคำ
    pred_counter = Counter(predicted_words)
    gt_counter = Counter(groundtruth_words)
    
    # คำนวณ True Positives, False Positives, False Negatives
    # True Positive: คำที่อยู่ในทั้ง predicted และ groundtruth
    tp = sum((pred_counter & gt_counter).values())
    
    # False Positive: คำที่อยู่ใน predicted แต่ไม่อยู่ใน groundtruth
    fp = sum((pred_counter - gt_counter).values())
    
    # False Negative: คำที่อยู่ใน groundtruth แต่ไม่อยู่ใน predicted
    fn = sum((gt_counter - pred_counter).values())
    
    # คำนวณ Precision, Recall, F1-Score
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # คำนวณ Word Error Rate (WER)
    # WER = (Substitutions + Insertions + Deletions) / Total words in groundtruth
    total_gt_words = len(groundtruth_words)
    wer = (fp + fn) / total_gt_words if total_gt_words > 0 else 0.0
    
    # คำนวณ Character Error Rate (CER)
    pred_text = ''.join(predicted_words)
    gt_text = ''.join(groundtruth_words)
    
    # ใช้ Levenshtein distance สำหรับคำนวณ CER
    cer = levenshtein_distance(pred_text, gt_text) / len(gt_text) if len(gt_text) > 0 else 0.0
    
    return {
        'true_positives': tp,
        'false_positives': fp,
        'false_negatives': fn,
        'precision': precision,
        'recall': recall,
        'f1_score': f1_score,
        'word_error_rate': wer,
        'character_error_rate': cer,
        'total_predicted_words': len(predicted_words),
        'total_groundtruth_words': len(groundtruth_words)
    }


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    คำนวณ Levenshtein distance ระหว่าง 2 strings
    
    Args:
        s1: String แรก
        s2: String ที่สอง
        
    Returns:
        int: Levenshtein distance
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def create_visualizations(all_metrics: List[Dict], filenames: List[str], output_folder: str):
    """
    สร้างกราฟและรูปภาพสำหรับการประเมินผล
    
    Args:
        all_metrics: List ของ metrics จากทุกไฟล์
        filenames: List ของชื่อไฟล์
        output_folder: โฟลเดอร์สำหรับบันทึกรูปภาพ
    """
    if not all_metrics:
        return
    
    # สร้างโฟลเดอร์ถ้ายังไม่มี
    os.makedirs(output_folder, exist_ok=True)
    
    # ตั้งค่า font สำหรับภาษาไทย
    plt.rcParams['font.family'] = 'DejaVu Sans'
    plt.rcParams['axes.unicode_minus'] = False
    
    # 1. กราฟสรุปค่าเฉลี่ย (Bar Chart)
    if len(all_metrics) > 0:
        avg_precision = sum(m['precision'] for m in all_metrics) / len(all_metrics)
        avg_recall = sum(m['recall'] for m in all_metrics) / len(all_metrics)
        avg_f1 = sum(m['f1_score'] for m in all_metrics) / len(all_metrics)
        avg_wer = sum(m['word_error_rate'] for m in all_metrics) / len(all_metrics)
        avg_cer = sum(m['character_error_rate'] for m in all_metrics) / len(all_metrics)
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # กราฟที่ 1: Precision, Recall, F1-Score
        metrics_names = ['Precision', 'Recall', 'F1-Score']
        metrics_values = [avg_precision, avg_recall, avg_f1]
        colors = ['#2ecc71', '#3498db', '#9b59b6']
        
        bars1 = ax1.bar(metrics_names, metrics_values, color=colors, alpha=0.8, edgecolor='black', linewidth=1.5)
        ax1.set_ylim([0, 1])
        ax1.set_ylabel('Score', fontsize=12, fontweight='bold')
        ax1.set_title('Average Metrics (Precision, Recall, F1-Score)', fontsize=14, fontweight='bold', pad=20)
        ax1.grid(axis='y', alpha=0.3, linestyle='--')
        
        # เพิ่มค่าในแต่ละ bar
        for bar, val in zip(bars1, metrics_values):
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                    f'{val:.4f}', ha='center', va='bottom', fontsize=11, fontweight='bold')
        
        # กราฟที่ 2: WER, CER
        error_metrics = ['WER', 'CER']
        error_values = [avg_wer, avg_cer]
        colors2 = ['#e74c3c', '#f39c12']
        
        bars2 = ax2.bar(error_metrics, error_values, color=colors2, alpha=0.8, edgecolor='black', linewidth=1.5)
        ax2.set_ylim([0, max(error_values) * 1.2 if max(error_values) > 0 else 0.1])
        ax2.set_ylabel('Error Rate', fontsize=12, fontweight='bold')
        ax2.set_title('Average Error Rates (WER, CER)', fontsize=14, fontweight='bold', pad=20)
        ax2.grid(axis='y', alpha=0.3, linestyle='--')
        
        # เพิ่มค่าในแต่ละ bar
        for bar, val in zip(bars2, error_values):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height + max(error_values) * 0.02,
                    f'{val:.4f}', ha='center', va='bottom', fontsize=11, fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(os.path.join(output_folder, 'summary_metrics.png'), dpi=300, bbox_inches='tight')
        plt.close()
        print(f"✅ บันทึกรูปภาพ: summary_metrics.png")
    
    # 2. กราฟแสดงผลของแต่ละไฟล์ (Line Chart)
    if len(all_metrics) > 1:
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        
        # สร้างชื่อไฟล์แบบสั้น (ใช้แค่ส่วนท้าย)
        short_names = [name.split('_')[-1].replace('.txt', '')[:15] for name in filenames[:len(all_metrics)]]
        
        # Precision per file
        precisions = [m['precision'] for m in all_metrics]
        axes[0, 0].plot(range(len(precisions)), precisions, marker='o', linewidth=2, markersize=6, color='#2ecc71')
        axes[0, 0].set_title('Precision per File', fontsize=13, fontweight='bold')
        axes[0, 0].set_xlabel('File Index', fontsize=11)
        axes[0, 0].set_ylabel('Precision', fontsize=11)
        axes[0, 0].grid(True, alpha=0.3, linestyle='--')
        axes[0, 0].set_ylim([0, 1])
        
        # Recall per file
        recalls = [m['recall'] for m in all_metrics]
        axes[0, 1].plot(range(len(recalls)), recalls, marker='s', linewidth=2, markersize=6, color='#3498db')
        axes[0, 1].set_title('Recall per File', fontsize=13, fontweight='bold')
        axes[0, 1].set_xlabel('File Index', fontsize=11)
        axes[0, 1].set_ylabel('Recall', fontsize=11)
        axes[0, 1].grid(True, alpha=0.3, linestyle='--')
        axes[0, 1].set_ylim([0, 1])
        
        # F1-Score per file
        f1_scores = [m['f1_score'] for m in all_metrics]
        axes[1, 0].plot(range(len(f1_scores)), f1_scores, marker='^', linewidth=2, markersize=6, color='#9b59b6')
        axes[1, 0].set_title('F1-Score per File', fontsize=13, fontweight='bold')
        axes[1, 0].set_xlabel('File Index', fontsize=11)
        axes[1, 0].set_ylabel('F1-Score', fontsize=11)
        axes[1, 0].grid(True, alpha=0.3, linestyle='--')
        axes[1, 0].set_ylim([0, 1])
        
        # WER per file
        wers = [m['word_error_rate'] for m in all_metrics]
        axes[1, 1].plot(range(len(wers)), wers, marker='d', linewidth=2, markersize=6, color='#e74c3c')
        axes[1, 1].set_title('Word Error Rate (WER) per File', fontsize=13, fontweight='bold')
        axes[1, 1].set_xlabel('File Index', fontsize=11)
        axes[1, 1].set_ylabel('WER', fontsize=11)
        axes[1, 1].grid(True, alpha=0.3, linestyle='--')
        axes[1, 1].set_ylim([0, max(wers) * 1.2 if max(wers) > 0 else 0.1])
        
        plt.tight_layout()
        plt.savefig(os.path.join(output_folder, 'metrics_per_file.png'), dpi=300, bbox_inches='tight')
        plt.close()
        print(f"✅ บันทึกรูปภาพ: metrics_per_file.png")
    
    # 3. กราฟเปรียบเทียบ TP, FP, FN
    if len(all_metrics) > 0:
        fig, ax = plt.subplots(figsize=(12, 6))
        
        tps = [m['true_positives'] for m in all_metrics]
        fps = [m['false_positives'] for m in all_metrics]
        fns = [m['false_negatives'] for m in all_metrics]
        
        x = np.arange(len(all_metrics))
        width = 0.25
        
        bars1 = ax.bar(x - width, tps, width, label='True Positives (TP)', color='#2ecc71', alpha=0.8)
        bars2 = ax.bar(x, fps, width, label='False Positives (FP)', color='#e74c3c', alpha=0.8)
        bars3 = ax.bar(x + width, fns, width, label='False Negatives (FN)', color='#f39c12', alpha=0.8)
        
        ax.set_xlabel('File Index', fontsize=12, fontweight='bold')
        ax.set_ylabel('Count', fontsize=12, fontweight='bold')
        ax.set_title('True Positives, False Positives, and False Negatives per File', 
                    fontsize=14, fontweight='bold', pad=20)
        ax.set_xticks(x)
        ax.set_xticklabels([f'File {i+1}' for i in range(len(all_metrics))], rotation=45, ha='right')
        ax.legend(fontsize=10)
        ax.grid(axis='y', alpha=0.3, linestyle='--')
        
        plt.tight_layout()
        plt.savefig(os.path.join(output_folder, 'tp_fp_fn_comparison.png'), dpi=300, bbox_inches='tight')
        plt.close()
        print(f"✅ บันทึกรูปภาพ: tp_fp_fn_comparison.png")
    
    # 4. กราฟสรุปแบบรวม (Comprehensive Summary)
    if len(all_metrics) > 0:
        fig = plt.figure(figsize=(16, 10))
        gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)
        
        # คำนวณค่าเฉลี่ย
        avg_precision = sum(m['precision'] for m in all_metrics) / len(all_metrics)
        avg_recall = sum(m['recall'] for m in all_metrics) / len(all_metrics)
        avg_f1 = sum(m['f1_score'] for m in all_metrics) / len(all_metrics)
        avg_wer = sum(m['word_error_rate'] for m in all_metrics) / len(all_metrics)
        avg_cer = sum(m['character_error_rate'] for m in all_metrics) / len(all_metrics)
        
        # Pie chart: Precision vs (1-Precision)
        ax1 = fig.add_subplot(gs[0, 0])
        ax1.pie([avg_precision, 1-avg_precision], labels=[f'Correct\n{avg_precision:.2%}', f'Incorrect\n{1-avg_precision:.2%}'],
                colors=['#2ecc71', '#ecf0f1'], autopct='%1.2f%%', startangle=90, textprops={'fontsize': 11, 'fontweight': 'bold'})
        ax1.set_title('Precision Distribution', fontsize=13, fontweight='bold', pad=15)
        
        # Pie chart: Recall vs (1-Recall)
        ax2 = fig.add_subplot(gs[0, 1])
        ax2.pie([avg_recall, 1-avg_recall], labels=[f'Found\n{avg_recall:.2%}', f'Missed\n{1-avg_recall:.2%}'],
                colors=['#3498db', '#ecf0f1'], autopct='%1.2f%%', startangle=90, textprops={'fontsize': 11, 'fontweight': 'bold'})
        ax2.set_title('Recall Distribution', fontsize=13, fontweight='bold', pad=15)
        
        # Bar chart: All main metrics
        ax3 = fig.add_subplot(gs[1, :])
        metrics = ['Precision', 'Recall', 'F1-Score']
        values = [avg_precision, avg_recall, avg_f1]
        colors_bar = ['#2ecc71', '#3498db', '#9b59b6']
        bars = ax3.bar(metrics, values, color=colors_bar, alpha=0.8, edgecolor='black', linewidth=2, width=0.6)
        ax3.set_ylim([0, 1])
        ax3.set_ylabel('Score', fontsize=12, fontweight='bold')
        ax3.set_title('Overall Performance Metrics', fontsize=14, fontweight='bold', pad=20)
        ax3.grid(axis='y', alpha=0.3, linestyle='--')
        for bar, val in zip(bars, values):
            height = bar.get_height()
            ax3.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                    f'{val:.4f}', ha='center', va='bottom', fontsize=12, fontweight='bold')
        
        # Bar chart: Error rates
        ax4 = fig.add_subplot(gs[2, :])
        error_metrics = ['WER', 'CER']
        error_values = [avg_wer, avg_cer]
        colors_error = ['#e74c3c', '#f39c12']
        bars = ax4.bar(error_metrics, error_values, color=colors_error, alpha=0.8, edgecolor='black', linewidth=2, width=0.6)
        ax4.set_ylabel('Error Rate', fontsize=12, fontweight='bold')
        ax4.set_title('Error Rates', fontsize=14, fontweight='bold', pad=20)
        ax4.grid(axis='y', alpha=0.3, linestyle='--')
        max_error = max(error_values) if max(error_values) > 0 else 0.1
        ax4.set_ylim([0, max_error * 1.3])
        for bar, val in zip(bars, error_values):
            height = bar.get_height()
            ax4.text(bar.get_x() + bar.get_width()/2., height + max_error * 0.05,
                    f'{val:.4f}', ha='center', va='bottom', fontsize=12, fontweight='bold')
        
        plt.suptitle('Word Segmentation Evaluation - Comprehensive Summary', 
                    fontsize=16, fontweight='bold', y=0.995)
        plt.savefig(os.path.join(output_folder, 'comprehensive_summary.png'), dpi=300, bbox_inches='tight')
        plt.close()
        print(f"✅ บันทึกรูปภาพ: comprehensive_summary.png")


def evaluate_segmentation(nlp_result_folder: str, groundtruth_folder: str, output_file: str = None, output_folder: str = None):
    """
    ประเมินผลการแบ่งคำโดยเปรียบเทียบกับ Ground Truth
    
    Args:
        nlp_result_folder: โฟลเดอร์ที่มีผลการแบ่งคำ (nlp_result)
        groundtruth_folder: โฟลเดอร์ที่มี Ground Truth
        output_file: ไฟล์สำหรับบันทึกผลการประเมิน (ถ้า None จะพิมพ์ออกหน้าจอ)
    """
    # ตรวจสอบว่าโฟลเดอร์มีอยู่หรือไม่
    if not os.path.exists(nlp_result_folder):
        print(f"✗ ไม่พบโฟลเดอร์: {nlp_result_folder}")
        return
    
    if not os.path.exists(groundtruth_folder):
        print(f"✗ ไม่พบโฟลเดอร์: {groundtruth_folder}")
        print(f"💡 สร้างโฟลเดอร์ {groundtruth_folder} และเพิ่มไฟล์ Ground Truth ลงไป")
        return
    
    # หาไฟล์ทั้งหมดใน nlp_result
    nlp_files = [f for f in os.listdir(nlp_result_folder) if f.endswith('.txt')]
    
    if not nlp_files:
        print(f"✗ ไม่พบไฟล์ในโฟลเดอร์: {nlp_result_folder}")
        return
    
    print(f"📊 พบไฟล์ทั้งหมด: {len(nlp_files)} ไฟล์\n")
    
    # เก็บผลการประเมินทั้งหมด
    all_metrics = []
    all_filenames = []
    results_text = []
    
    results_text.append("=" * 80)
    results_text.append("📊 รายงานการประเมินผลการแบ่งคำ")
    results_text.append("=" * 80)
    results_text.append("")
    
    # ประมวลผลแต่ละไฟล์
    for filename in sorted(nlp_files):
        nlp_path = os.path.join(nlp_result_folder, filename)
        gt_path = os.path.join(groundtruth_folder, filename)
        
        # ตรวจสอบว่าไฟล์ Ground Truth มีอยู่หรือไม่
        if not os.path.exists(gt_path):
            print(f"⚠️ ไม่พบไฟล์ Ground Truth: {filename}")
            results_text.append(f"⚠️ {filename}: ไม่พบไฟล์ Ground Truth")
            results_text.append("")
            continue
        
        # อ่านผลการแบ่งคำ
        segmented_text = read_segmented_text(nlp_path)
        if not segmented_text:
            print(f"⚠️ ไม่สามารถอ่านผลการแบ่งคำจาก: {filename}")
            continue
        
        # อ่าน Ground Truth
        groundtruth_text = read_groundtruth(gt_path)
        if not groundtruth_text:
            print(f"⚠️ ไม่สามารถอ่าน Ground Truth จาก: {filename}")
            continue
        
        # แบ่งเป็นรายการคำ
        predicted_words = tokenize_text(segmented_text)
        groundtruth_words = tokenize_text(groundtruth_text)
        
        # คำนวณ metrics
        metrics = calculate_metrics(predicted_words, groundtruth_words)
        all_metrics.append(metrics)
        all_filenames.append(filename)
        
        # แสดงผลลัพธ์
        print(f"📄 {filename}")
        print(f"   Precision: {metrics['precision']:.4f}")
        print(f"   Recall: {metrics['recall']:.4f}")
        print(f"   F1-Score: {metrics['f1_score']:.4f}")
        print(f"   WER: {metrics['word_error_rate']:.4f}")
        print(f"   CER: {metrics['character_error_rate']:.4f}")
        print()
        
        # บันทึกผลลัพธ์
        results_text.append(f"📄 {filename}")
        results_text.append(f"   Precision: {metrics['precision']:.4f}")
        results_text.append(f"   Recall: {metrics['recall']:.4f}")
        results_text.append(f"   F1-Score: {metrics['f1_score']:.4f}")
        results_text.append(f"   WER: {metrics['word_error_rate']:.4f}")
        results_text.append(f"   CER: {metrics['character_error_rate']:.4f}")
        results_text.append(f"   TP: {metrics['true_positives']}, FP: {metrics['false_positives']}, FN: {metrics['false_negatives']}")
        results_text.append(f"   Predicted words: {metrics['total_predicted_words']}, Ground truth words: {metrics['total_groundtruth_words']}")
        results_text.append("")
    
    # คำนวณค่าเฉลี่ย
    if all_metrics:
        avg_precision = sum(m['precision'] for m in all_metrics) / len(all_metrics)
        avg_recall = sum(m['recall'] for m in all_metrics) / len(all_metrics)
        avg_f1 = sum(m['f1_score'] for m in all_metrics) / len(all_metrics)
        avg_wer = sum(m['word_error_rate'] for m in all_metrics) / len(all_metrics)
        avg_cer = sum(m['character_error_rate'] for m in all_metrics) / len(all_metrics)
        
        print("=" * 80)
        print("📊 สรุปผลการประเมิน (ค่าเฉลี่ย)")
        print("=" * 80)
        print(f"   Precision: {avg_precision:.4f}")
        print(f"   Recall: {avg_recall:.4f}")
        print(f"   F1-Score: {avg_f1:.4f}")
        print(f"   WER: {avg_wer:.4f}")
        print(f"   CER: {avg_cer:.4f}")
        print()
        
        results_text.append("=" * 80)
        results_text.append("📊 สรุปผลการประเมิน (ค่าเฉลี่ย)")
        results_text.append("=" * 80)
        results_text.append(f"   Precision: {avg_precision:.4f}")
        results_text.append(f"   Recall: {avg_recall:.4f}")
        results_text.append(f"   F1-Score: {avg_f1:.4f}")
        results_text.append(f"   WER: {avg_wer:.4f}")
        results_text.append(f"   CER: {avg_cer:.4f}")
        results_text.append("")
    
    # สร้างกราฟและรูปภาพ
    if output_folder and all_metrics:
        print("\n" + "=" * 80)
        print("📊 กำลังสร้างกราฟและรูปภาพ...")
        print("=" * 80)
        create_visualizations(all_metrics, all_filenames, output_folder)
    
    # บันทึกผลลัพธ์ลงไฟล์
    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(results_text))
            print(f"\n✅ บันทึกผลการประเมินลงไฟล์: {output_file}")
        except Exception as e:
            print(f"✗ เกิดข้อผิดพลาดในการบันทึกไฟล์: {str(e)}")


if __name__ == "__main__":
    # หา directory ของไฟล์นี้ (nlp/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # กำหนด path ของโฟลเดอร์ (relative to script directory)
    nlp_result_folder = os.path.join(script_dir, "nlp_result")
    groundtruth_folder = os.path.join(script_dir, "groundtruth")
    output_file = os.path.join(script_dir, "evaluation_results.txt")
    output_folder = os.path.join(script_dir, "evaluation")  # โฟลเดอร์สำหรับเก็บรูปภาพ
    
    # เรียกใช้ฟังก์ชันประเมินผล
    evaluate_segmentation(nlp_result_folder, groundtruth_folder, output_file, output_folder)

