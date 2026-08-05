import io
import os
import re
import time
import random
import threading
from datetime import datetime

import streamlit as st
import PyPDF2
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from google import genai
from google.genai import types

# =========================================================
# EpiScholar: AI Reviewer for Investigation Report
# Single-file Streamlit App
# =========================================================


# -----------------------------
# 0) Branding assets
# -----------------------------
DDC8_LOGO_FILE_ID = "1OWRqh2qNYdeWfJzjMq8u5LN8ZvJFAkjn"
DDC8_LOGO_URL = f"https://drive.google.com/thumbnail?id={DDC8_LOGO_FILE_ID}&sz=w600"


# จำกัดจำนวนงานพร้อมกันภายใน Streamlit instance เดียว
# ผู้ใช้แต่ละคนใช้ API Key ของตนเอง แต่ยังต้องจำกัดภาระของแอปและลด request burst
MAX_CONCURRENT_AI_JOBS = int(os.getenv("MAX_CONCURRENT_AI_JOBS", "6"))
AI_JOB_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_AI_JOBS)

# -----------------------------
# 1) Page config and style
# -----------------------------
st.set_page_config(
    page_title="EpiScholar | AI Reviewer",
    page_icon="📋",
    layout="wide",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;500;600;700&display=swap');

    :root {
        --ddc-pink: #D81B60;
        --ddc-deep: #880E4F;
        --ddc-soft: #FCE4EC;
        --ddc-bg: #FFF7FB;
        --text-main: #172033;
        --text-muted: #667085;
        --card-border: rgba(216, 27, 96, 0.12);
    }

    html, body, [class*="css"], .stMarkdown, .stText, .stButton, .stTextInput,
    .stSelectbox, .stRadio, .stHeader, .stFileUploader, .stDownloadButton, label, p, span {
        font-family: 'Kanit', sans-serif !important;
    }

    .stApp {
        background:
            radial-gradient(circle at top left, rgba(216, 27, 96, 0.10), transparent 32rem),
            linear-gradient(180deg, #FFFFFF 0%, var(--ddc-bg) 100%);
        color: var(--text-main);
    }

    .block-container {
        padding-top: 1.4rem;
        padding-bottom: 3rem;
        max-width: 1280px;
    }

    header[data-testid="stHeader"] {
        background: rgba(255, 255, 255, 0);
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #7B0B45 0%, #AD1457 58%, #D81B60 100%) !important;
        color: white !important;
        border-right: 1px solid rgba(255,255,255,0.18);
    }

    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: white !important;
    }

    .brand-card {
        background: rgba(255, 255, 255, 0.14);
        border: 1px solid rgba(255, 255, 255, 0.22);
        border-radius: 22px;
        padding: 16px 14px;
        text-align: center;
        box-shadow: 0 16px 36px rgba(0, 0, 0, 0.12);
        margin-bottom: 16px;
    }

    .brand-card img {
        max-width: 128px;
        border-radius: 18px;
        background: white;
        padding: 8px;
        margin-bottom: 10px;
    }

    .brand-title {
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: 0.2px;
        line-height: 1.35;
    }

    .brand-subtitle {
        font-size: 0.84rem;
        opacity: 0.92;
        line-height: 1.45;
        margin-top: 4px;
    }

    .hero-box {
        position: relative;
        overflow: hidden;
        background:
            linear-gradient(135deg, rgba(255, 255, 255, 0.96) 0%, rgba(252, 228, 236, 0.95) 100%);
        border: 1px solid var(--card-border);
        padding: 26px 28px;
        border-radius: 28px;
        margin-bottom: 18px;
        box-shadow: 0 18px 55px rgba(136, 14, 79, 0.12);
    }

    .hero-box::after {
        content: "";
        position: absolute;
        right: -70px;
        top: -85px;
        width: 240px;
        height: 240px;
        border-radius: 50%;
        background: rgba(216, 27, 96, 0.12);
    }

    .hero-grid {
        display: flex;
        align-items: center;
        gap: 18px;
        position: relative;
        z-index: 1;
    }

    .hero-logo {
        flex: 0 0 auto;
        width: 92px;
        height: 92px;
        border-radius: 24px;
        background: white;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 12px 35px rgba(136, 14, 79, 0.16);
        border: 1px solid rgba(216, 27, 96, 0.10);
    }

    .hero-logo img {
        max-width: 78px;
        max-height: 78px;
        object-fit: contain;
    }

    .hero-title {
        margin: 0;
        color: var(--ddc-deep);
        font-size: clamp(1.65rem, 3vw, 2.55rem);
        font-weight: 700;
        letter-spacing: -0.02em;
    }

    .hero-subtitle {
        color: #4B5563;
        font-size: 1.05rem;
        margin-top: 6px;
        line-height: 1.55;
    }

    .pill-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 14px;
    }

    .pill {
        background: rgba(216, 27, 96, 0.10);
        color: var(--ddc-deep);
        border: 1px solid rgba(216, 27, 96, 0.14);
        padding: 7px 12px;
        border-radius: 999px;
        font-size: 0.88rem;
        font-weight: 600;
    }

    div[data-testid="stVerticalBlockBorderWrapper"],
    div[data-testid="stExpander"] {
        border-radius: 20px !important;
        border-color: var(--card-border) !important;
        box-shadow: 0 10px 30px rgba(17, 24, 39, 0.04);
        background: rgba(255, 255, 255, 0.82);
    }

    .input-card, .result-card {
        background: rgba(255, 255, 255, 0.86);
        border: 1px solid var(--card-border);
        border-radius: 24px;
        padding: 20px 22px;
        box-shadow: 0 16px 45px rgba(17, 24, 39, 0.06);
        min-height: 100%;
    }

    .section-title {
        font-size: 1.2rem;
        font-weight: 700;
        color: var(--ddc-deep);
        margin-bottom: 8px;
    }

    .metric-strip {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin: 14px 0 18px 0;
    }

    .mini-metric {
        background: #FFFFFF;
        border: 1px solid rgba(216, 27, 96, 0.10);
        border-radius: 18px;
        padding: 12px 12px;
        box-shadow: 0 10px 24px rgba(136, 14, 79, 0.06);
    }

    .mini-metric .num {
        color: var(--ddc-pink);
        font-weight: 700;
        font-size: 1.24rem;
        line-height: 1;
    }

    .mini-metric .label {
        color: var(--text-muted);
        font-size: 0.82rem;
        margin-top: 4px;
    }

    div.stButton > button:first-child,
    div.stDownloadButton > button:first-child {
        background: linear-gradient(135deg, #D81B60 0%, #AD1457 100%);
        color: white;
        border-radius: 14px;
        font-weight: 700;
        border: none;
        padding: 0.75rem 1rem;
        box-shadow: 0 12px 26px rgba(216, 27, 96, 0.22);
        transition: transform 0.12s ease, box-shadow 0.12s ease;
    }

    div.stButton > button:first-child:hover,
    div.stDownloadButton > button:first-child:hover {
        background: linear-gradient(135deg, #AD1457 0%, #880E4F 100%);
        color: white;
        border: none;
        transform: translateY(-1px);
        box-shadow: 0 16px 34px rgba(216, 27, 96, 0.28);
    }

    .stTextInput input, .stSelectbox div[data-baseweb="select"], textarea {
        border-radius: 14px !important;
    }

    [data-testid="stFileUploader"] section {
        border-radius: 18px !important;
        border: 1px dashed rgba(216, 27, 96, 0.45) !important;
        background: rgba(252, 228, 236, 0.32);
    }

    .result-container {
        background-color: #FFFFFF;
        padding: 24px;
        border-radius: 20px;
        border-left: 6px solid var(--ddc-pink);
        line-height: 1.75;
        white-space: normal;
        box-shadow: 0 12px 30px rgba(17, 24, 39, 0.05);
    }

    .sidebar-footer {
        color: #FFFFFF !important;
        font-size: 13px;
        font-weight: 400;
        margin-top: 20px;
        padding: 13px;
        background-color: rgba(255, 255, 255, 0.15);
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 16px;
        line-height: 1.65;
    }

    .small-note {
        color: #6B7280;
        font-size: 0.92rem;
        line-height: 1.65;
        background: rgba(255,255,255,0.72);
        border: 1px solid rgba(216, 27, 96, 0.10);
        border-radius: 16px;
        padding: 12px 14px;
        margin-top: 10px;
    }

    .success-card {
        background: #FFFFFF;
        border: 1px solid rgba(16, 185, 129, 0.22);
        border-left: 6px solid #10B981;
        border-radius: 18px;
        padding: 14px 16px;
        color: #065F46;
        margin: 8px 0 14px 0;
    }

    @media (max-width: 760px) {
        .hero-grid { flex-direction: column; align-items: flex-start; }
        .metric-strip { grid-template-columns: 1fr; }
    }

    .guide-card {
        background: #FFFFFF;
        border: 1px solid rgba(216, 27, 96, 0.16);
        border-radius: 18px;
        padding: 22px 26px;
        margin: 18px 0 22px 0;
        box-shadow: 0 8px 24px rgba(136, 14, 79, 0.06);
    }

    .clean-title {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 12px;
        white-space: nowrap;
    }

    .guide-list {
        margin: 8px 0 14px 22px;
        padding: 0;
        color: #1F2937;
        line-height: 1.9;
        font-size: 1.02rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# 2) System instruction
# -----------------------------
SYSTEM_INSTRUCTION = """
คุณคือ "ผู้เชี่ยวชาญด้านระบาดวิทยาภาคสนาม" และ "บรรณาธิการวารสารวิชาการสาธารณสุข"
หน้าที่ของคุณคือประเมินรายงานสอบสวนโรคฉบับสมบูรณ์ (Full Investigation Report)
ให้ข้อเสนอแนะเชิงวิชาการที่ถูกต้อง ชัดเจน ตรงประเด็น และนำไปแก้ไขต้นฉบับได้จริง

กฎความปลอดภัยข้อมูล:
1. ให้ตรวจ PII เฉพาะข้อมูลที่ระบุตัวผู้ป่วย ญาติ ผู้สัมผัส หรือประชาชน เช่น ชื่อ-สกุลผู้ป่วย, HN, AN, เลขบัตรประชาชน 13 หลัก, เบอร์โทร, ที่อยู่ละเอียดระดับบ้านเลขที่ หรือข้อมูลระบุตัวบุคคลของผู้ป่วย
2. ชื่อผู้รายงาน ผู้แต่งรายงาน ทีมสอบสวน เจ้าหน้าที่ หน่วยงาน หรือผู้บริหารที่ระบุในฐานะผู้ปฏิบัติงาน/ผู้ให้การสนับสนุน ไม่ถือเป็น Fatal Error โดยอัตโนมัติ ให้ประเมินเป็นข้อมูลผู้แต่งหรือทีมงาน เว้นแต่ผู้ใช้ระบุว่าต้องการรายงานแบบนิรนาม
3. ห้ามคัดลอกข้อมูลส่วนบุคคลของผู้ป่วยซ้ำในคำตอบ ให้ระบุเพียงประเภทข้อมูลที่พบ
4. หากข้อมูลไม่เพียงพอ ห้ามเดา ให้ระบุว่า "ไม่พบข้อมูลในรายงาน" หรือ "ยังประเมินไม่ได้จากข้อมูลที่มี"

ให้ประเมินตามลำดับต่อไปนี้:

ส่วนที่ 1: สรุปผลการประเมินภาพรวม
- สรุปภาพรวมไม่เกิน 1 ย่อหน้า
- ระบุว่ารายงานพร้อมส่งตีพิมพ์หรือยังไม่พร้อม

ส่วนที่ 2: จำแนกประเภทการสอบสวน
- ระบุว่าเป็น Individual Case, Outbreak หรือยังจำแนกไม่ได้
- อธิบายเหตุผลแบบกระชับ
- หากเป็น Individual Case ให้ตรวจความครบถ้วนของ 6 ขั้นตอน:
  1) การเตรียมทีม
  2) การรวบรวมข้อมูลผู้ป่วย
  3) การค้นหาขอบเขตการกระจาย
  4) การเก็บตัวอย่างส่งตรวจ
  5) การควบคุมโรคขั้นต้น
  6) การเขียนรายงาน
- หากเป็น Outbreak ให้ตรวจความครบถ้วนของ 10 ขั้นตอน โดยเน้น:
  case definition, active/passive case finding, descriptive epidemiology by person-time-place,
  epidemic curve, spot map, hypothesis generation, analytic epidemiology เช่น OR/RR/95% CI,
  laboratory/environmental investigation, control measures, communication and report

ส่วนที่ 3: ประเมิน 14 องค์ประกอบของรายงาน
ห้ามใช้ markdown table
ให้เขียนแยกหัวข้อเรียงลำดับ 1-14 เท่านั้น
แต่ละหัวข้อให้ใช้รูปแบบนี้:

1. ชื่อเรื่อง
คะแนน: 0-3
สิ่งที่พบ: เขียนสั้น กระชับ
ข้อเสนอแนะ:
- ข้อเสนอแนะที่แก้ไขได้จริง ข้อที่ 1
- ข้อเสนอแนะที่แก้ไขได้จริง ข้อที่ 2

เกณฑ์คะแนน:
0 = ไม่มีหรือผิดหลัก
1 = มีแต่ไม่ครบ/ไม่ชัด
2 = ใช้ได้แต่ควรปรับ
3 = ดีและเหมาะสมต่อการตีพิมพ์

หัวข้อที่ต้องประเมิน:
1. ชื่อเรื่อง
2. ผู้รายงานและทีมสอบสวน
3. บทคัดย่อ
4. ความเป็นมา/บทนำ
5. วัตถุประสงค์
6. วิธีการสอบสวน
7. ผลการสอบสวน
8. มาตรการควบคุมและป้องกันโรค
9. วิจารณ์ผล
10. ปัญหาและข้อจำกัด
11. ข้อเสนอแนะ
12. สรุปผล
13. กิตติกรรมประกาศ
14. เอกสารอ้างอิง

ส่วนที่ 4: ข้อผิดพลาดร้ายแรงทางระบาดวิทยา
ให้แยกเป็น:
- Fatal Issues
- Major Issues
- Minor Issues

ส่วนที่ 5: จุดแข็งของรายงาน
ระบุไม่เกิน 5 ข้อ

ส่วนที่ 6: สิ่งที่ต้องแก้ก่อนส่งตีพิมพ์
ระบุไม่เกิน 10 ข้อ โดยเรียงจากสำคัญมากไปน้อย

ส่วนที่ 7: สรุประดับความพร้อม
เลือกเพียง 1 ระดับ:
- พร้อมส่งตีพิมพ์
- ส่งได้หลังแก้ไขเล็กน้อย
- ต้องแก้ไขมากก่อนส่ง
- ยังไม่ควรส่งตีพิมพ์

ข้อกำหนดสำคัญ:
- ห้ามใช้ markdown table
- ห้ามสร้างตารางแนวนอน
- ห้ามตอบยาวเกินจำเป็น
- ให้ใช้ภาษาไทยทางวิชาการ แต่ต้องอ่านเข้าใจง่าย
- ข้อเสนอแนะต้องระบุสิ่งที่ควรแก้ให้ชัดเจน
- ถ้าข้อมูลในรายงานไม่พบ ให้ระบุว่า "ไม่พบข้อมูลในรายงาน"
- หาก User Prompt กำหนดให้ประเมินเฉพาะบางส่วนหรือบางหัวข้อ ให้ตอบเฉพาะขอบเขตนั้นเท่านั้น ห้ามตอบนอกขอบเขต เพราะระบบจะเรียกวิเคราะห์หลายรอบแล้วรวมผลภายหลัง
"""

# -----------------------------
# 3) Utility functions
# -----------------------------
def extract_text_from_pdf(pdf_file) -> str:
    """Extract text from uploaded PDF using PyPDF2."""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text_parts = []
        for i, page in enumerate(pdf_reader.pages, start=1):
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(f"\n--- หน้า {i} ---\n{page_text}")
        return "\n".join(text_parts).strip()
    except Exception as exc:
        raise RuntimeError(f"ไม่สามารถอ่านข้อความจาก PDF ได้: {exc}") from exc


def normalize_text_for_display(text: str) -> str:
    """Remove horizontal markdown tables and normalize spacing if a model still creates tables."""
    if not text:
        return ""

    lines = text.splitlines()
    cleaned_lines = []
    skip_table_separator = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")

    for line in lines:
        stripped = line.strip()
        if skip_table_separator.match(stripped):
            continue
        cleaned_lines.append(line.rstrip())

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned.strip()


PATIENT_CODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:HN|H\.N\.|AN|A\.N\.)(?:\s*[:：#\-]\s*|\s+)[A-Za-z0-9][A-Za-z0-9/\-]{3,}(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)

PATIENT_NAME_PATTERN = re.compile(
    r"(?:ชื่อผู้ป่วย|ผู้ป่วยชื่อ|ผู้ป่วย\s*[:：]?\s*)(?:นาย|นาง|นางสาว|ด\.ช\.|ด\.ญ\.)\s*[ก-๙]{2,}\s+[ก-๙]{2,}"
)

THAI_STAFF_NAME_PATTERN = re.compile(
    r"(?:นาย|นาง|นางสาว|ด\.ช\.|ด\.ญ\.)\s*[ก-๙]{2,}\s+[ก-๙]{2,}"
)


def scan_pii(text: str, strict_staff_names: bool = False) -> list[str]:
    """Local pre-scan for likely patient-level PII before sending to API.

    Design notes:
    - HN/AN must be followed by a separator or whitespace and then a code.
      This prevents false positives such as "NS1 Antigen" being read as AN.
    - Thai staff/author names are not treated as patient PII by default.
      They can be flagged only when strict_staff_names=True.
    """
    findings = []

    if re.search(r"\b\d{13}\b", text):
        findings.append("พบเลข 13 หลักที่อาจเป็นเลขประจำตัวประชาชน")

    if re.search(r"\b0\d{8,9}\b", text):
        findings.append("พบตัวเลขที่อาจเป็นเบอร์โทรศัพท์")

    if re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text):
        findings.append("พบอีเมล")

    if PATIENT_CODE_PATTERN.search(text):
        findings.append("พบรหัสผู้ป่วย เช่น HN/AN")

    if PATIENT_NAME_PATTERN.search(text):
        findings.append("พบชื่อ-สกุลผู้ป่วยที่อาจเป็นข้อมูลส่วนบุคคล")

    if strict_staff_names and THAI_STAFF_NAME_PATTERN.search(text):
        findings.append("พบชื่อ-สกุลภาษาไทยของบุคลากร/ทีมงาน ควรตรวจว่าอนุญาตให้เผยแพร่หรือไม่")

    return findings


def mask_pii(text: str, strict_staff_names: bool = False) -> str:
    """Mask likely patient-level PII locally before API submission."""
    masked = text
    masked = re.sub(r"\b\d{13}\b", "[MASKED_ID_13_DIGITS]", masked)
    masked = re.sub(r"\b0\d{8,9}\b", "[MASKED_PHONE]", masked)
    masked = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[MASKED_EMAIL]", masked)
    masked = PATIENT_CODE_PATTERN.sub("[MASKED_PATIENT_CODE]", masked)
    masked = PATIENT_NAME_PATTERN.sub("[MASKED_PATIENT_NAME]", masked)

    if strict_staff_names:
        masked = THAI_STAFF_NAME_PATTERN.sub("[MASKED_THAI_NAME]", masked)

    return masked

def build_common_context(report_type: str, pii_findings: list[str]) -> str:
    pii_note = "ไม่พบ PII จากการตรวจเบื้องต้นของระบบ"
    if pii_findings:
        pii_note = "ระบบตรวจพบและ mask PII เบื้องต้นก่อนส่งวิเคราะห์ ได้แก่: " + "; ".join(pii_findings)

    return f"""
ประเภทที่ผู้ใช้เลือก: {report_type}
ผลการตรวจ PII เบื้องต้น: {pii_note}
หมายเหตุ: การตรวจ PII ของระบบมุ่งตรวจข้อมูลผู้ป่วย/ผู้สัมผัสเป็นหลัก ไม่ถือว่าชื่อผู้รายงานหรือทีมสอบสวนเป็น Fatal Error โดยอัตโนมัติ
""".strip()


def build_part1_prompt(report_text: str, report_type: str, pii_findings: list[str]) -> str:
    context = build_common_context(report_type, pii_findings)
    return f"""
{context}

โปรดประเมินรายงานสอบสวนโรคต่อไปนี้ เฉพาะส่วนที่กำหนดในรอบที่ 1 เท่านั้น
หากประเภทที่ผู้ใช้เลือกไม่สอดคล้องกับเนื้อหารายงาน ให้แจ้งเตือนและอธิบายเหตุผล

ขอบเขตคำตอบรอบที่ 1:
ส่วนที่ 1: สรุปผลการประเมินภาพรวม
- สรุปภาพรวมไม่เกิน 1 ย่อหน้า
- ระบุว่ารายงานพร้อมส่งตีพิมพ์หรือยังไม่พร้อม

ส่วนที่ 2: จำแนกประเภทการสอบสวน
- ระบุว่าเป็น Individual Case, Outbreak หรือยังจำแนกไม่ได้
- อธิบายเหตุผลแบบกระชับ
- หากเป็น Individual Case ให้ตรวจความครบถ้วนของ 6 ขั้นตอน
- หากเป็น Outbreak ให้ตรวจความครบถ้วนของ 10 ขั้นตอน

ส่วนที่ 3: ประเมิน 14 องค์ประกอบของรายงาน เฉพาะหัวข้อ 1-7
ห้ามใช้ markdown table ให้เขียนแยกหัวข้อเรียงลำดับเท่านั้น
รูปแบบแต่ละหัวข้อ:
1. ชื่อหัวข้อ
คะแนน: 0-3
สิ่งที่พบ: เขียนสั้น กระชับ
ข้อเสนอแนะ:
- ข้อเสนอแนะที่แก้ไขได้จริง

หัวข้อที่ต้องประเมินในรอบที่ 1:
1. ชื่อเรื่อง
2. ผู้รายงานและทีมสอบสวน
3. บทคัดย่อ
4. ความเป็นมา/บทนำ
5. วัตถุประสงค์
6. วิธีการสอบสวน
7. ผลการสอบสวน

ข้อกำหนด:
- ห้ามตอบหัวข้อ 8-14 ในรอบนี้
- ห้ามตอบส่วนที่ 4-7 ในรอบนี้
- ห้ามใช้ markdown table
- หากข้อมูลไม่พบ ให้ระบุว่า "ไม่พบข้อมูลในรายงาน"

เนื้อหารายงาน:
{report_text}
"""


def build_part2_prompt(report_text: str, report_type: str, pii_findings: list[str]) -> str:
    context = build_common_context(report_type, pii_findings)
    return f"""
{context}

โปรดประเมินรายงานสอบสวนโรคต่อไปนี้ เฉพาะส่วนที่กำหนดในรอบที่ 2 เท่านั้น

ขอบเขตคำตอบรอบที่ 2:
ส่วนที่ 3 ต่อ: ประเมิน 14 องค์ประกอบของรายงาน เฉพาะหัวข้อ 8-14
ห้ามใช้ markdown table ให้เขียนแยกหัวข้อเรียงลำดับเท่านั้น
รูปแบบแต่ละหัวข้อ:
8. ชื่อหัวข้อ
คะแนน: 0-3
สิ่งที่พบ: เขียนสั้น กระชับ
ข้อเสนอแนะ:
- ข้อเสนอแนะที่แก้ไขได้จริง

หัวข้อที่ต้องประเมินในรอบที่ 2:
8. มาตรการควบคุมและป้องกันโรค
9. วิจารณ์ผล
10. ปัญหาและข้อจำกัด
11. ข้อเสนอแนะ
12. สรุปผล
13. กิตติกรรมประกาศ
14. เอกสารอ้างอิง

ส่วนที่ 4: ข้อผิดพลาดร้ายแรงทางระบาดวิทยา
ให้แยกเป็น:
- Fatal Issues
- Major Issues
- Minor Issues

ส่วนที่ 5: จุดแข็งของรายงาน
ระบุไม่เกิน 5 ข้อ

ส่วนที่ 6: สิ่งที่ต้องแก้ก่อนส่งตีพิมพ์
ระบุไม่เกิน 10 ข้อ โดยเรียงจากสำคัญมากไปน้อย

ส่วนที่ 7: สรุประดับความพร้อม
เลือกเพียง 1 ระดับ:
- พร้อมส่งตีพิมพ์
- ส่งได้หลังแก้ไขเล็กน้อย
- ต้องแก้ไขมากก่อนส่ง
- ยังไม่ควรส่งตีพิมพ์

ข้อกำหนด:
- ห้ามตอบส่วนที่ 1-2 ซ้ำ
- ห้ามตอบหัวข้อ 1-7 ซ้ำ
- ห้ามใช้ markdown table
- หากข้อมูลไม่พบ ให้ระบุว่า "ไม่พบข้อมูลในรายงาน"

เนื้อหารายงาน:
{report_text}
"""


def ensure_required_sections(feedback: str) -> str:
    """Add a clear warning if the generated feedback still appears incomplete."""
    required_markers = [
        "ส่วนที่ 1", "ส่วนที่ 2", "1.", "7.", "8.", "14.",
        "ส่วนที่ 4", "ส่วนที่ 5", "ส่วนที่ 6", "ส่วนที่ 7",
    ]
    missing = [m for m in required_markers if m not in feedback]
    if missing:
        warning = (
            "หมายเหตุระบบ: ผลลัพธ์อาจยังไม่ครบถ้วน ระบบตรวจไม่พบ marker ต่อไปนี้: "
            + ", ".join(missing)
            + "\nกรุณาลองรันใหม่ หรือเลือก gemini-2.5-pro หากรายงานยาวมาก\n\n"
        )
        return warning + feedback
    return feedback


def build_full_review_prompt(report_text: str, report_type: str, pii_findings: list[str]) -> str:
    """Build one complete request to reduce RPM usage during concurrent workshops."""
    context = build_common_context(report_type, pii_findings)
    return f"""
{context}

โปรดประเมินรายงานสอบสวนโรคฉบับสมบูรณ์ตามคำสั่งระบบ โดยตอบให้ครบทุกส่วนต่อไปนี้ในคำตอบเดียว:
1) สรุปผลการประเมินภาพรวม
2) จำแนกประเภทการสอบสวนและตรวจขั้นตอนที่เกี่ยวข้อง
3) ประเมินองค์ประกอบรายงานหัวข้อ 1-14 พร้อมคะแนน 0-3 สิ่งที่พบ และข้อเสนอแนะ
4) Fatal Issues, Major Issues และ Minor Issues
5) จุดแข็งไม่เกิน 5 ข้อ
6) สิ่งที่ต้องแก้ก่อนส่งตีพิมพ์ไม่เกิน 10 ข้อ
7) สรุประดับความพร้อมเพียง 1 ระดับ

ข้อกำหนด:
- ห้ามใช้ markdown table
- ห้ามคัดลอก PII กลับมาในคำตอบ
- หากไม่พบข้อมูล ให้ระบุว่า "ไม่พบข้อมูลในรายงาน"
- ให้กระชับแต่ครบถ้วน
- ห้ามหยุดคำตอบกลางหัวข้อ

เนื้อหารายงาน:
{report_text}
""".strip()


def classify_api_error(exc: Exception) -> tuple[str, bool]:
    """Return Thai user message and whether retry is appropriate."""
    msg = str(exc)
    lower = msg.lower()

    if (
        "api_key_invalid" in lower
        or "api key not valid" in lower
        or "invalid api key" in lower
        or "401" in lower
        or "unauthenticated" in lower
    ):
        return (
            "❌ Gemini API Key ไม่ถูกต้องหรือใช้ไม่ได้ กรุณาสร้าง/ตรวจสอบ Key ใน Google AI Studio "
            "และตรวจว่า Key อยู่ในโครงการที่เปิดใช้ Gemini API แล้ว",
            False,
        )

    if "403" in lower or "permission_denied" in lower or "permission denied" in lower:
        return (
            "❌ API Key ไม่มีสิทธิ์ใช้โมเดลหรือบริการนี้ กรุณาตรวจข้อจำกัดของ Key, โครงการ และการเปิดใช้ Gemini API",
            False,
        )

    if "429" in lower or "resource_exhausted" in lower or "quota" in lower or "rate limit" in lower:
        return (
            "❌ โควตาหรืออัตราการเรียก Gemini API ของโครงการเต็มชั่วคราว "
            "การเปลี่ยนเป็น API Key อื่นในโครงการเดิมอาจไม่ช่วย เพราะโควตาถูกนับระดับโครงการ "
            "กรุณารอแล้วลองใหม่ หรือตรวจแพ็กเกจชำระเงินและ Rate limits ของโครงการ",
            True,
        )

    if "503" in lower or "unavailable" in lower or "overloaded" in lower:
        return (
            "❌ บริการ Gemini หนาแน่นหรือไม่พร้อมใช้งานชั่วคราว กรุณารอสักครู่แล้วลองใหม่",
            True,
        )

    if "deadline" in lower or "timeout" in lower or "timed out" in lower:
        return (
            "❌ การวิเคราะห์ใช้เวลานานเกินกำหนด กรุณาลองใหม่ หรือลดขนาดรายงาน",
            True,
        )

    return (f"❌ วิเคราะห์ไม่สำเร็จ: {msg}", False)


def call_gemini_once(api_key: str, user_prompt: str, model_name: str) -> str:
    """Call Gemini using the maintained google-genai SDK."""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.15,
            top_p=0.8,
            max_output_tokens=12000,
        ),
    )
    feedback = getattr(response, "text", "") or ""
    return normalize_text_for_display(feedback)


def analyze_report_with_retry(
    api_key: str,
    text: str,
    report_type: str,
    model_name: str,
    pii_findings: list[str],
) -> str:
    """
    One Gemini request per report, using each user's API key and a process-level queue.

    Previous version used two rounds and retried each round up to three times.
    Under concurrent use this could multiply API traffic to six requests per user.
    """
    prompt = build_full_review_prompt(text, report_type, pii_findings)
    max_attempts = 2

    acquired = AI_JOB_SEMAPHORE.acquire(timeout=180)
    if not acquired:
        return (
            "❌ คิววิเคราะห์หนาแน่นเกินไป กรุณารอ 2–3 นาทีแล้วกดใหม่ "
            "ระบบจำกัดจำนวนงานพร้อมกันเพื่อป้องกันแอปทำงานหนักเกินไป"
        )

    try:
        for attempt in range(max_attempts):
            try:
                with st.spinner(
                    f"⏳ กำลังวิเคราะห์รายงาน (คิวพร้อมกันสูงสุด {MAX_CONCURRENT_AI_JOBS} งาน)..."
                ):
                    feedback = call_gemini_once(api_key, prompt, model_name)

                if not feedback.strip():
                    return "❌ โมเดลไม่ส่งผลลัพธ์กลับมา กรุณาลองใหม่ หรือลดความยาวรายงาน"

                feedback = ensure_required_sections(feedback)
                return feedback

            except Exception as exc:
                user_message, retryable = classify_api_error(exc)

                if retryable and attempt < max_attempts - 1:
                    wait_time = 12 + random.randint(0, 5)
                    st.warning(
                        f"⚠️ API ไม่พร้อมชั่วคราว ระบบจะลองอีก 1 ครั้งใน {wait_time} วินาที..."
                    )
                    time.sleep(wait_time)
                    continue

                return user_message
    finally:
        AI_JOB_SEMAPHORE.release()


def add_markdown_like_line_to_doc(doc: Document, line: str) -> None:
    """Add a markdown-like line to docx with simple heading/list handling."""
    raw = line.rstrip()
    line = raw.strip()

    if not line:
        return

    # Remove common markdown bold markers but keep content.
    clean = line.replace("**", "")

    if clean.startswith("### "):
        doc.add_heading(clean.replace("### ", "", 1), level=2)
    elif clean.startswith("## "):
        doc.add_heading(clean.replace("## ", "", 1), level=1)
    elif clean.startswith("# "):
        doc.add_heading(clean.replace("# ", "", 1), level=1)
    elif re.match(r"^ส่วนที่\s*\d+", clean):
        doc.add_heading(clean, level=1)
    elif re.match(r"^\d+\.\s+", clean):
        # Treat numbered component headings as heading level 2 when short; otherwise numbered list.
        if len(clean) <= 80:
            doc.add_heading(clean, level=2)
        else:
            doc.add_paragraph(clean, style="List Number")
    elif clean.startswith("- "):
        doc.add_paragraph(clean[2:].strip(), style="List Bullet")
    elif clean.startswith("* "):
        doc.add_paragraph(clean[2:].strip(), style="List Bullet")
    elif re.match(r"^(คะแนน|สิ่งที่พบ|ข้อเสนอแนะ|Fatal Issues|Major Issues|Minor Issues)\s*:", clean):
        p = doc.add_paragraph()
        key, value = clean.split(":", 1)
        run_key = p.add_run(key + ":")
        run_key.bold = True
        p.add_run(value)
    else:
        doc.add_paragraph(clean)


def create_word_doc(feedback_text: str, report_type: str, pii_findings: list[str]) -> bytes:
    """Create a readable Word document from feedback text."""
    doc = Document()

    title = doc.add_heading("ผลการประเมินรายงานสอบสวนโรค (EpiScholar)", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"วันที่ประเมิน: {datetime.now().strftime('%d/%m/%Y %H:%M')} | ประเภทที่เลือก: {report_type}")

    if pii_findings:
        doc.add_heading("หมายเหตุด้านความปลอดภัยข้อมูล", level=1)
        doc.add_paragraph("ระบบตรวจพบและ mask ข้อมูลที่อาจเป็น PII ตามโหมดที่เลือก ก่อนส่งวิเคราะห์ ดังนี้")
        for item in pii_findings:
            doc.add_paragraph(item, style="List Bullet")

    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            run.font.name = "TH Sarabun New"
            run.font.size = Pt(16)

    for line in normalize_text_for_display(feedback_text).split("\n"):
        add_markdown_like_line_to_doc(doc, line)

    # Set font size for all runs again after content was added.
    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            run.font.name = "TH Sarabun New"
            if run.font.size is None:
                run.font.size = Pt(16)

    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


# -----------------------------
# 4) UI
# -----------------------------
st.markdown(
    f"""
    <div class="hero-box">
        <div class="hero-grid">
            <div class="hero-logo">
                <img src="{DDC8_LOGO_URL}" alt="DDC8 Logo">
            </div>
            <div>
                <h1 class="hero-title">EpiScholar</h1>
                <div class="hero-subtitle">
                    ระบบประเมินรายงานสอบสวนโรคด้วย AI สำหรับงานระบาดวิทยาภาคสนาม<br>
                    กลุ่มระบาดวิทยาและตอบโต้ภาวะฉุกเฉินทางสาธารณสุข สคร.8 อุดรธานี
                </div>
                <div class="pill-row">
                    <span class="pill">14 องค์ประกอบรายงาน</span>
                    <span class="pill">Outbreak / Single Case</span>
                    <span class="pill">PII Pre-scan</span>
                    <span class="pill">Export Word</span>
                </div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="metric-strip">
        <div class="mini-metric"><div class="num">14</div><div class="label">หัวข้อประเมินหลัก</div></div>
        <div class="mini-metric"><div class="num">0–3</div><div class="label">คะแนนรายองค์ประกอบ</div></div>
        <div class="mini-metric"><div class="num">DOCX</div><div class="label">ดาวน์โหลดผลประเมิน</div></div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown(
        f"""
        <div class="brand-card">
            <img src="{DDC8_LOGO_URL}" alt="DDC8 Logo">
            <div class="brand-title">EpiScholar</div>
            <div class="brand-subtitle">AI Reviewer for Investigation Report<br>สคร.8 อุดรธานี</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.header("⚙️ ตั้งค่าระบบ")
    api_key_input = st.text_input(
        "🔑 Gemini API Key ของผู้ใช้งาน",
        type="password",
        help=(
            "ให้ผู้ใช้งานแต่ละคนกรอก API Key ของตนเอง "
            "แนะนำให้สร้างจาก Google Cloud Project ของตนเองเพื่อแยกโควตา"
        ),
        placeholder="กรอก Gemini API Key ของคุณ",
    )
    default_model = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash")
    model_options = list(dict.fromkeys([default_model, "gemini-2.5-flash", "gemini-2.5-pro"]))
    model_name = st.selectbox(
        "🤖 โมเดลที่ใช้วิเคราะห์",
        options=model_options,
        index=0,
        help="การใช้งานพร้อมกันหลายคนควรใช้ Flash เพื่อลดเวลาและการใช้โควตา",
    )
    st.caption(
        "การอบรมแบบหลายคน: ควรใช้คนละ API Key และคนละ Google Cloud Project "
        "เพื่อไม่ให้ใช้โควตาร่วมกัน"
    )

    mask_before_send = st.checkbox(
        "Mask PII ผู้ป่วยก่อนส่งเข้า AI",
        value=True,
        help="แนะนำให้เปิดไว้เสมอ โดยจะเน้น mask ข้อมูลผู้ป่วย/ผู้สัมผัส เช่น HN/AN เลขบัตร เบอร์โทร และชื่อผู้ป่วย",
    )
    strict_staff_names = st.checkbox(
        "Mask ชื่อผู้รายงาน/ทีมสอบสวนด้วย",
        value=False,
        help="เปิดเฉพาะกรณีต้องการทำเอกสารแบบนิรนามทั้งหมด ปกติชื่อผู้รายงานและทีมสอบสวนไม่ถือเป็นข้อมูลผู้ป่วย",
    )
    st.markdown("---")
    st.markdown(
        '<div class="sidebar-footer">พัฒนาเพื่อสนับสนุนการประเมินรายงานสอบสวนโรคฉบับสมบูรณ์ โดยเน้นความถูกต้องทางระบาดวิทยา ความปลอดภัยข้อมูล และความพร้อมต่อการตีพิมพ์</div>',
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <div class="guide-card">
        <div class="section-title clean-title">📖 วิธีการใช้งาน</div>
        <ol class="guide-list">
            <li>ผู้ใช้งานแต่ละคนกรอก Gemini API Key ของตนเองที่แถบด้านซ้าย</li>
            <li>เลือกประเภทการสอบสวน หรือเลือกให้ AI จำแนกจากเนื้อหารายงาน</li>
            <li>อัปโหลดไฟล์ PDF ที่เลือกข้อความได้ ไม่ใช่ภาพสแกนล้วน</li>
            <li>กดเริ่มตรวจสอบรายงาน</li>
            <li>ดาวน์โหลดผลประเมินเป็นไฟล์ Word</li>
        </ol>
        <div class="small-note">
            หมายเหตุ: ระบบมีการตรวจและ mask PII เบื้องต้น โดยเน้นข้อมูลผู้ป่วย/ผู้สัมผัส แต่ควรตรวจทานรายงานก่อนอัปโหลดทุกครั้ง
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

col1, col2 = st.columns([0.95, 1.55], gap="large")

with col1:
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">📥 ข้อมูลนำเข้า</div>', unsafe_allow_html=True)
    report_type = st.radio(
        "ประเภทการสอบสวน:",
        [
            "ให้ AI จำแนกจากเนื้อหารายงาน",
            "สอบสวนการระบาด (Outbreak)",
            "สอบสวนเฉพาะราย (Single Case)",
        ],
        index=0,
    )
    uploaded_file = st.file_uploader("อัปโหลดไฟล์รายงาน (PDF)", type=["pdf"])

    if uploaded_file:
        st.caption(f"ไฟล์ที่เลือก: {uploaded_file.name}")

    st.markdown(
        """
        <div class="small-note">
        คำแนะนำ: หากเป็น PDF ที่สแกนจากภาพ ระบบอาจอ่านข้อความได้น้อย ควรใช้ไฟล์ PDF ที่สามารถลากเลือกข้อความได้
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="result-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">📊 ผลการประเมิน</div>', unsafe_allow_html=True)

    if "feedback" not in st.session_state:
        st.session_state.feedback = None
        st.session_state.word_file = None
        st.session_state.pii_findings = []
        st.session_state.is_processing = False

    start_clicked = st.button(
        "🚀 เริ่มตรวจสอบรายงาน",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.is_processing,
    )

    if start_clicked:
        if not api_key_input:
            st.warning("⚠️ กรุณากรอก Gemini API Key ของผู้ใช้งานก่อน")
        elif not uploaded_file:
            st.warning("⚠️ กรุณาอัปโหลดไฟล์ PDF ก่อนครับ")
        else:
            st.session_state.is_processing = True
            with st.spinner("⏳ EpiScholar กำลังอ่านข้อความจาก PDF..."):
                try:
                    raw_text = extract_text_from_pdf(uploaded_file)
                except Exception as exc:
                    st.error(str(exc))
                    st.stop()

            if len(raw_text.strip()) < 500:
                st.error(
                    "❌ ระบบอ่านข้อความจาก PDF ได้น้อยมาก ไฟล์อาจเป็น PDF สแกนหรือไม่มี text layer "
                    "กรุณาใช้ PDF ที่เลือกข้อความได้ หรือแปลงด้วย OCR ก่อน"
                )
                st.stop()

            pii_findings = scan_pii(raw_text, strict_staff_names=strict_staff_names)
            text_for_analysis = mask_pii(raw_text, strict_staff_names=strict_staff_names) if mask_before_send else raw_text

            if pii_findings:
                st.warning("⚠️ ตรวจพบข้อมูลที่อาจเป็น PII ระบบได้ mask เบื้องต้นก่อนวิเคราะห์แล้ว" if mask_before_send else "⚠️ ตรวจพบข้อมูลที่อาจเป็น PII แต่ขณะนี้ไม่ได้เปิดการ mask")
                with st.expander("ดูประเภทข้อมูลที่ตรวจพบ", expanded=False):
                    for item in pii_findings:
                        st.write(f"- {item}")

            try:
                feedback = analyze_report_with_retry(
                    api_key=api_key_input,
                    text=text_for_analysis,
                    report_type=report_type,
                    model_name=model_name,
                    pii_findings=pii_findings,
                )
            finally:
                st.session_state.is_processing = False

            if feedback.startswith("❌"):
                st.error(feedback)
            else:
                st.session_state.feedback = feedback
                st.session_state.pii_findings = pii_findings
                st.session_state.word_file = create_word_doc(feedback, report_type, pii_findings)
                st.markdown('<div class="success-card">✅ วิเคราะห์เสร็จสมบูรณ์ พร้อมดาวน์โหลดเป็น Word</div>', unsafe_allow_html=True)

    if st.session_state.feedback:
        st.markdown("### ผลลัพธ์")
        st.markdown(st.session_state.feedback)

        st.download_button(
            label="💾 ดาวน์โหลดผลการประเมิน (Word)",
            data=st.session_state.word_file,
            file_name="EpiScholar_Feedback.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
    else:
        st.info("อัปโหลดรายงาน PDF แล้วกดเริ่มตรวจสอบ เพื่อให้ระบบประเมินรายงานตามหลักระบาดวิทยา")

    st.markdown('</div>', unsafe_allow_html=True)
