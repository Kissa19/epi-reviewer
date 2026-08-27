import io
import os
import re
import time
import random
import threading
import hashlib
import uuid
from collections import deque
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


# Workshop Mode: จำกัดจำนวนงาน AI ที่รันพร้อมกันและจัดคิวแบบ FIFO
# ค่าเริ่มต้น 3 เหมาะกับ Central API Mode สำหรับห้องอบรม 30–50 คน โดยให้ผู้ใช้ที่เหลือรอคิว FIFO
MAX_CONCURRENT_AI_JOBS = int(os.getenv("MAX_CONCURRENT_AI_JOBS", "3"))
QUEUE_WAIT_TIMEOUT = int(os.getenv("QUEUE_WAIT_TIMEOUT", "1800"))


def get_central_api_key() -> str:
    """Load the shared Gemini API key from Streamlit Secrets first, then environment variables."""
    key = ""
    try:
        key = str(st.secrets.get("GEMINI_API_KEY", "") or "").strip()
    except Exception:
        key = ""
    if not key:
        key = str(os.getenv("GEMINI_API_KEY", "") or "").strip()
    return key


CENTRAL_GEMINI_API_KEY = get_central_api_key()


class WorkshopQueue:
    """Process-level FIFO queue shared by all Streamlit sessions in one app instance."""

    def __init__(self, max_active: int):
        self.max_active = max(1, int(max_active))
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._waiting = deque()
        self._active = set()
        self._submitted = 0
        self._completed = 0
        self._failed = 0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "max_active": self.max_active,
                "active": len(self._active),
                "waiting": len(self._waiting),
                "submitted": self._submitted,
                "completed": self._completed,
                "failed": self._failed,
            }

    def join_and_wait(self, job_id: str, timeout: int, status_callback=None) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            if job_id in self._active or job_id in self._waiting:
                return False
            self._waiting.append(job_id)
            self._submitted += 1
            self._condition.notify_all()

            while True:
                try:
                    position = list(self._waiting).index(job_id) + 1
                except ValueError:
                    position = 0

                can_start = (
                    self._waiting
                    and self._waiting[0] == job_id
                    and len(self._active) < self.max_active
                )
                if can_start:
                    self._waiting.popleft()
                    self._active.add(job_id)
                    self._condition.notify_all()
                    return True

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    try:
                        self._waiting.remove(job_id)
                    except ValueError:
                        pass
                    self._condition.notify_all()
                    return False

                snap = {
                    "active": len(self._active),
                    "waiting": len(self._waiting),
                    "position": position,
                    "max_active": self.max_active,
                }
                # callback is intentionally called outside a long wait but still under lock; keep it lightweight
                if status_callback:
                    try:
                        status_callback(snap)
                    except Exception:
                        pass
                self._condition.wait(timeout=min(1.0, remaining))

    def finish(self, job_id: str, success: bool) -> None:
        with self._condition:
            self._active.discard(job_id)
            if success:
                self._completed += 1
            else:
                self._failed += 1
            self._condition.notify_all()


WORKSHOP_QUEUE = WorkshopQueue(MAX_CONCURRENT_AI_JOBS)

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
    @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;500;600;700;800&display=swap');
    @import url('https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css');

    :root {
        --ddc-pink: #D81B60;
        --ddc-deep: #880E4F;
        --ddc-soft: #FCE4EC;
        --ddc-bg: #FFF7FB;
        --text-main: #172033;
        --text-muted: #667085;
        --card-border: rgba(216, 27, 96, 0.12);
        --card-shadow: 0 18px 45px rgba(136, 14, 79, 0.08);
        --soft-shadow: 0 10px 30px rgba(17, 24, 39, 0.05);
        --success: #10B981;
        --warn: #F59E0B;
        --info: #7C3AED;
    }

    html, body, [class*="css"], .stMarkdown, .stText, .stButton, .stTextInput,
    .stSelectbox, .stRadio, .stHeader, .stFileUploader, .stDownloadButton, label, p, span {
        font-family: 'Kanit', sans-serif !important;
    }

    .stApp {
        background:
            radial-gradient(circle at top left, rgba(216, 27, 96, 0.10), transparent 30rem),
            radial-gradient(circle at right top, rgba(124, 58, 237, 0.06), transparent 26rem),
            linear-gradient(180deg, #FFFFFF 0%, var(--ddc-bg) 100%);
        color: var(--text-main);
    }

    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 3rem;
        max-width: 1320px;
    }

    header[data-testid="stHeader"] {
        background: rgba(255, 255, 255, 0);
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #6C0A3E 0%, #AD1457 56%, #D81B60 100%) !important;
        color: white !important;
        border-right: 1px solid rgba(255,255,255,0.18);
    }

    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] small {
        color: white !important;
    }

    .brand-card {
        background: rgba(255, 255, 255, 0.13);
        border: 1px solid rgba(255, 255, 255, 0.24);
        border-radius: 24px;
        padding: 18px 16px;
        text-align: center;
        box-shadow: 0 16px 36px rgba(0, 0, 0, 0.12);
        margin-bottom: 16px;
        backdrop-filter: blur(10px);
    }

    .brand-card img {
        max-width: 112px;
        border-radius: 18px;
        background: white;
        padding: 8px;
        margin-bottom: 10px;
    }

    .brand-title {
        font-size: 1.08rem;
        font-weight: 700;
        letter-spacing: 0.2px;
        line-height: 1.35;
    }

    .brand-subtitle {
        font-size: 0.84rem;
        opacity: 0.95;
        line-height: 1.45;
        margin-top: 4px;
    }

    .sidebar-group {
        background: rgba(255,255,255,0.12);
        border: 1px solid rgba(255,255,255,0.18);
        border-radius: 18px;
        padding: 14px 14px 8px 14px;
        margin-bottom: 14px;
    }

    .sidebar-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-weight: 700;
        margin-bottom: 8px;
    }

    .hero-shell {
        position: relative;
        overflow: hidden;
        background: linear-gradient(135deg, rgba(255,255,255,0.96) 0%, rgba(252,228,236,0.96) 48%, rgba(255,255,255,0.95) 100%);
        border: 1px solid var(--card-border);
        border-radius: 30px;
        padding: 28px 28px 22px 28px;
        box-shadow: var(--card-shadow);
        margin-bottom: 18px;
    }

    .hero-shell::before {
        content: "";
        position: absolute;
        inset: auto -80px -80px auto;
        width: 220px;
        height: 220px;
        border-radius: 999px;
        background: rgba(216, 27, 96, 0.10);
    }

    .hero-layout {
        display: grid;
        grid-template-columns: minmax(0, 1.25fr) minmax(290px, 0.75fr);
        gap: 20px;
        align-items: stretch;
        position: relative;
        z-index: 1;
    }

    .hero-main {
        display: flex;
        gap: 18px;
        align-items: flex-start;
    }

    .hero-logo {
        width: 96px;
        height: 96px;
        border-radius: 24px;
        background: white;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 12px 35px rgba(136, 14, 79, 0.16);
        border: 1px solid rgba(216, 27, 96, 0.10);
        flex: 0 0 auto;
    }

    .hero-logo img {
        max-width: 78px;
        max-height: 78px;
        object-fit: contain;
    }

    .hero-kicker {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border-radius: 999px;
        background: rgba(216, 27, 96, 0.12);
        color: var(--ddc-deep);
        font-size: 0.82rem;
        font-weight: 700;
        margin-bottom: 10px;
    }

    .hero-title {
        margin: 0;
        color: var(--ddc-deep);
        font-size: clamp(1.8rem, 3.2vw, 2.7rem);
        font-weight: 800;
        letter-spacing: -0.03em;
        line-height: 1.08;
    }

    .hero-subtitle {
        color: #4B5563;
        font-size: 1.02rem;
        margin-top: 8px;
        line-height: 1.65;
        max-width: 760px;
    }

    .pill-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 16px;
    }

    .pill {
        background: rgba(255, 255, 255, 0.72);
        color: var(--ddc-deep);
        border: 1px solid rgba(216, 27, 96, 0.14);
        padding: 8px 12px;
        border-radius: 999px;
        font-size: 0.87rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 7px;
    }

    .hero-side {
        display: grid;
        gap: 12px;
        align-content: start;
    }

    .feature-card {
        background: rgba(255,255,255,0.72);
        border: 1px solid rgba(216, 27, 96, 0.12);
        border-radius: 20px;
        padding: 15px 16px;
        box-shadow: var(--soft-shadow);
    }

    .feature-head {
        display: flex;
        align-items: center;
        gap: 10px;
        font-weight: 700;
        color: var(--ddc-deep);
        margin-bottom: 4px;
    }

    .icon-chip {
        width: 34px;
        height: 34px;
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(216,27,96,0.14), rgba(124,58,237,0.14));
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--ddc-deep);
        font-size: 1rem;
        flex: 0 0 auto;
    }

    .feature-note {
        color: var(--text-muted);
        font-size: 0.92rem;
        line-height: 1.5;
    }

    .metric-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin: 14px 0 16px 0;
    }

    .mini-metric {
        background: rgba(255,255,255,0.88);
        border: 1px solid rgba(216, 27, 96, 0.10);
        border-radius: 20px;
        padding: 14px 14px;
        box-shadow: var(--soft-shadow);
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .metric-icon {
        width: 42px;
        height: 42px;
        border-radius: 14px;
        background: linear-gradient(135deg, rgba(216,27,96,0.16), rgba(124,58,237,0.14));
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--ddc-deep);
        font-size: 1.08rem;
        flex: 0 0 auto;
    }

    .mini-metric .num {
        color: var(--ddc-pink);
        font-weight: 800;
        font-size: 1.25rem;
        line-height: 1.05;
    }

    .mini-metric .label {
        color: var(--text-muted);
        font-size: 0.84rem;
        margin-top: 2px;
        line-height: 1.35;
    }

    .workshop-band {
        background: linear-gradient(135deg, rgba(255,255,255,0.92), rgba(249,250,251,0.92));
        border: 1px solid rgba(124,58,237,0.12);
        border-radius: 24px;
        padding: 18px 18px 14px 18px;
        box-shadow: var(--soft-shadow);
        margin-bottom: 20px;
    }

    .workshop-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
        margin-bottom: 12px;
    }

    .workshop-title {
        display: flex;
        align-items: center;
        gap: 10px;
        color: var(--text-main);
        font-weight: 700;
        font-size: 1.02rem;
    }

    .workshop-subtitle {
        color: var(--text-muted);
        font-size: 0.92rem;
    }

    .workshop-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
    }

    .status-card {
        background: #FFFFFF;
        border: 1px solid rgba(17,24,39,0.06);
        border-radius: 18px;
        padding: 14px 14px;
        box-shadow: 0 8px 22px rgba(17,24,39,0.04);
    }

    .status-label {
        color: var(--text-muted);
        font-size: 0.82rem;
        display: flex;
        align-items: center;
        gap: 7px;
        margin-bottom: 5px;
    }

    .status-value {
        font-size: 1.3rem;
        font-weight: 800;
        color: var(--text-main);
        line-height: 1.1;
    }

    div[data-testid="stVerticalBlockBorderWrapper"],
    div[data-testid="stExpander"] {
        border-radius: 20px !important;
        border-color: var(--card-border) !important;
        box-shadow: 0 10px 30px rgba(17, 24, 39, 0.04);
        background: rgba(255, 255, 255, 0.82);
    }

    .input-card, .result-card, .helper-card {
        background: rgba(255, 255, 255, 0.90);
        border: 1px solid var(--card-border);
        border-radius: 24px;
        padding: 22px 22px;
        box-shadow: var(--card-shadow);
        min-height: 100%;
    }

    .result-card.result-fullwidth {
        margin-top: 18px;
    }

    .result-toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
        margin-bottom: 6px;
    }

    .helper-list {
        margin: 6px 0 0 0;
        padding-left: 1.1rem;
        color: var(--text-main);
        line-height: 1.8;
        font-size: 0.95rem;
    }

    .helper-list li {
        margin-bottom: 4px;
    }

    .section-title {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 1.16rem;
        font-weight: 800;
        color: var(--ddc-deep);
        margin-bottom: 10px;
    }

    .section-icon {
        width: 34px;
        height: 34px;
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(216,27,96,0.14), rgba(124,58,237,0.16));
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--ddc-deep);
        font-size: 0.98rem;
    }

    .sub-card {
        background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(255,247,251,0.9));
        border: 1px solid rgba(216,27,96,0.10);
        border-radius: 18px;
        padding: 14px 16px;
        margin: 12px 0 14px 0;
    }

    .sub-card-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
    }

    .sub-chip {
        background: #FFFFFF;
        border: 1px solid rgba(216,27,96,0.08);
        border-radius: 14px;
        padding: 10px 10px;
        display: flex;
        align-items: flex-start;
        gap: 8px;
    }

    .sub-chip i {
        color: var(--ddc-pink);
        margin-top: 2px;
    }

    .sub-chip strong {
        display: block;
        font-size: 0.87rem;
        color: var(--text-main);
    }

    .sub-chip span {
        display: block;
        font-size: 0.78rem;
        color: var(--text-muted);
        line-height: 1.35;
    }

    div.stButton > button:first-child,
    div.stDownloadButton > button:first-child {
        background: linear-gradient(135deg, #D81B60 0%, #AD1457 100%);
        color: white;
        border-radius: 14px;
        font-weight: 700;
        border: none;
        padding: 0.78rem 1rem;
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

    .stTextInput input, .stSelectbox div[data-baseweb="select"], .stRadio div[role="radiogroup"], textarea {
        border-radius: 14px !important;
    }

    .stTextInput input, textarea, .stSelectbox div[data-baseweb="select"] {
        border: 1px solid rgba(216,27,96,0.14) !important;
    }

    [data-testid="stFileUploader"] section {
        border-radius: 18px !important;
        border: 1.5px dashed rgba(216, 27, 96, 0.45) !important;
        background: rgba(252, 228, 236, 0.32);
    }

    .info-banner {
        display: flex;
        align-items: center;
        gap: 10px;
        background: rgba(124,58,237,0.07);
        border: 1px solid rgba(124,58,237,0.12);
        color: #4C1D95;
        border-radius: 16px;
        padding: 12px 14px;
        line-height: 1.55;
        margin-top: 12px;
    }

    .small-note {
        color: #6B7280;
        font-size: 0.92rem;
        line-height: 1.65;
        background: rgba(255,255,255,0.74);
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

    .results-placeholder {
        background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(255,247,251,0.92));
        border: 1px dashed rgba(216,27,96,0.24);
        border-radius: 20px;
        padding: 28px 20px;
        text-align: center;
        color: var(--text-muted);
        margin-top: 8px;
    }

    .results-placeholder i {
        font-size: 2rem;
        color: var(--ddc-pink);
        display: block;
        margin-bottom: 8px;
    }

    .guide-card {
        background: #FFFFFF;
        border: 1px solid rgba(216, 27, 96, 0.16);
        border-radius: 20px;
        padding: 22px 24px;
        margin: 18px 0 22px 0;
        box-shadow: var(--soft-shadow);
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

    .guide-mini-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-top: 12px;
    }

    .guide-mini {
        background: rgba(252,228,236,0.46);
        border: 1px solid rgba(216,27,96,0.12);
        border-radius: 16px;
        padding: 12px 12px;
        color: var(--text-main);
        font-size: 0.9rem;
        display: flex;
        gap: 8px;
        align-items: flex-start;
    }

    .guide-mini i {
        color: var(--ddc-pink);
        margin-top: 2px;
    }

    .sidebar-footer {
        color: #FFFFFF !important;
        font-size: 13px;
        font-weight: 400;
        margin-top: 8px;
        padding: 13px;
        background-color: rgba(255, 255, 255, 0.15);
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 16px;
        line-height: 1.65;
    }

    @media (max-width: 1080px) {
        .hero-layout { grid-template-columns: 1fr; }
        .workshop-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .sub-card-grid, .guide-mini-grid { grid-template-columns: 1fr; }
    }

    @media (max-width: 760px) {
        .hero-main { flex-direction: column; }
        .hero-logo { width: 84px; height: 84px; }
        .metric-strip, .workshop-grid { grid-template-columns: 1fr; }
        .block-container { padding-top: 1rem; }
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
- ทุกหัวข้อประเมิน 1-14 ให้เพิ่มบรรทัด "หลักฐานในรายงาน:" โดยระบุเลขหน้าจาก marker --- หน้า X --- และสรุปข้อความที่ใช้ตัดสินอย่างสั้น ๆ; หากเป็น DOCX หรือหาเลขหน้าไม่ได้ให้ระบุ "ไม่สามารถระบุเลขหน้าได้"
- ตรวจความสอดคล้องข้ามส่วนอย่างน้อย: วัตถุประสงค์↔วิธีการ, วิธีการ↔ผล, ผล↔สรุป, case definition↔จำนวนผู้ป่วย, ตาราง/ตัวเลข↔ข้อความบรรยาย, มาตรการ↔ผลการสอบสวน
- หากพบตัวเลข OR/RR/95% CI ให้ประเมินความสมเหตุสมผลของการตีความ แต่ห้ามคำนวณใหม่จากข้อมูลที่ไม่ครบ
- ถ้าข้อมูลในรายงานไม่พบ ให้ระบุว่า "ไม่พบข้อมูลในรายงาน"
- หาก User Prompt กำหนดให้ประเมินเฉพาะบางส่วนหรือบางหัวข้อ ให้ตอบเฉพาะขอบเขตนั้นเท่านั้น ห้ามตอบนอกขอบเขต เพราะระบบจะเรียกวิเคราะห์หลายรอบแล้วรวมผลภายหลัง
"""

# -----------------------------
# 3) Utility functions
# -----------------------------
def extract_text_from_pdf(pdf_file) -> str:
    """Extract text from uploaded PDF while preserving page markers for evidence citation."""
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


def extract_text_from_docx(docx_file) -> str:
    """Extract paragraphs and table cells from DOCX."""
    try:
        doc = Document(docx_file)
        parts = []
        for p in doc.paragraphs:
            if p.text.strip():
                parts.append(p.text.strip())
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts).strip()
    except Exception as exc:
        raise RuntimeError(f"ไม่สามารถอ่านข้อความจาก DOCX ได้: {exc}") from exc


def extract_report_text(uploaded_file) -> str:
    """Dispatch extraction by uploaded file extension."""
    name = (getattr(uploaded_file, "name", "") or "").lower()
    if name.endswith(".pdf"):
        return extract_text_from_pdf(uploaded_file)
    if name.endswith(".docx"):
        return extract_text_from_docx(uploaded_file)
    raise RuntimeError("รองรับเฉพาะไฟล์ PDF และ DOCX")


def assess_source_quality(text: str, filename: str) -> dict:
    """Simple local quality gate before sending a report to AI."""
    page_markers = len(re.findall(r"--- หน้า \d+ ---", text))
    chars = len(text.strip())
    words = len(re.findall(r"\S+", text))
    warnings = []
    if chars < 500:
        warnings.append("อ่านข้อความได้น้อยมาก อาจเป็น PDF สแกนหรือไฟล์ไม่มี text layer")
    elif chars < 2500:
        warnings.append("ข้อความค่อนข้างสั้น ควรตรวจว่าเป็นรายงานฉบับสมบูรณ์จริง")
    if filename.lower().endswith('.pdf') and page_markers == 0:
        warnings.append("ไม่พบตัวแบ่งหน้า จึงอ้างอิงเลขหน้าได้ไม่สมบูรณ์")
    return {"chars": chars, "words": words, "pages": page_markers, "warnings": warnings}


def parse_score_summary(feedback: str) -> dict:
    """Parse the 14 component scores from model output."""
    scores = [int(x) for x in re.findall(r"คะแนน\s*:\s*([0-3])(?:\s*/\s*3)?", feedback or "")]
    scores = scores[:14]
    total = sum(scores)
    max_score = 42
    pct = round(total * 100 / max_score, 1) if len(scores) == 14 else None
    return {"scores": scores, "count": len(scores), "total": total, "max": max_score, "pct": pct}


def make_review_cache_key(text: str, report_type: str, model_name: str) -> str:
    payload = f"{report_type}|{model_name}|{text}".encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


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
3) ประเมินองค์ประกอบรายงานหัวข้อ 1-14 พร้อมคะแนน 0-3 สิ่งที่พบ หลักฐานในรายงาน (เลขหน้าเมื่อระบุได้) และข้อเสนอแนะ
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
    job_id: str,
) -> str:
    """One Gemini request per report with Workshop Mode FIFO queue and one retry."""
    prompt = build_full_review_prompt(text, report_type, pii_findings)
    max_attempts = 2
    queue_status = st.empty()

    def render_queue_status(snap: dict) -> None:
        pos = snap.get("position", 0)
        active = snap.get("active", 0)
        waiting = snap.get("waiting", 0)
        max_active = snap.get("max_active", MAX_CONCURRENT_AI_JOBS)
        queue_status.info(
            f"🟡 Workshop Mode: อยู่ในคิวลำดับที่ {pos} | "
            f"กำลังวิเคราะห์ {active}/{max_active} งาน | รอทั้งหมด {waiting} งาน"
        )

    acquired = WORKSHOP_QUEUE.join_and_wait(
        job_id=job_id,
        timeout=QUEUE_WAIT_TIMEOUT,
        status_callback=render_queue_status,
    )
    if not acquired:
        queue_status.empty()
        return (
            "❌ คิววิเคราะห์หนาแน่นหรือรอนานเกินกำหนด กรุณากดเริ่มใหม่อีกครั้ง "
            "ระบบยังคงจำกัดจำนวนงานพร้อมกันเพื่อให้ผู้ใช้ทั้งห้องใช้งานได้เสถียร"
        )

    success = False
    try:
        snap = WORKSHOP_QUEUE.snapshot()
        queue_status.success(
            f"🔵 ถึงคิวแล้ว กำลังวิเคราะห์ | "
            f"กำลังทำงาน {snap['active']}/{snap['max_active']} งาน"
        )

        for attempt in range(max_attempts):
            try:
                with st.spinner("⏳ Gemini กำลังประเมินรายงานตามเกณฑ์ระบาดวิทยา..."):
                    feedback = call_gemini_once(api_key, prompt, model_name)

                if not feedback.strip():
                    return "❌ โมเดลไม่ส่งผลลัพธ์กลับมา กรุณาลองใหม่ หรือลดความยาวรายงาน"

                feedback = ensure_required_sections(feedback)
                success = True
                return feedback

            except Exception as exc:
                user_message, retryable = classify_api_error(exc)
                if retryable and attempt < max_attempts - 1:
                    wait_time = 12 + random.randint(0, 5)
                    queue_status.warning(
                        f"⚠️ API ไม่พร้อมชั่วคราว ระบบจะลองอีก 1 ครั้งใน {wait_time} วินาที"
                    )
                    time.sleep(wait_time)
                    continue
                return user_message
    finally:
        WORKSHOP_QUEUE.finish(job_id, success=success)
        if success:
            queue_status.success("✅ วิเคราะห์เสร็จแล้ว และคืนช่องวิเคราะห์ให้ผู้ใช้คนถัดไป")


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
    <div class="hero-shell">
        <div class="hero-layout">
            <div>
                <div class="hero-main">
                    <div class="hero-logo">
                        <img src="{DDC8_LOGO_URL}" alt="DDC8 Logo">
                    </div>
                    <div>
                        <div class="hero-kicker"><i class="bi bi-stars"></i> Smart Academic Review Platform</div>
                        <h1 class="hero-title">EpiScholar</h1>
                        <div class="hero-subtitle">
                            ระบบประเมินรายงานสอบสวนโรคด้วย AI สำหรับงานระบาดวิทยาภาคสนาม<br>
                            ออกแบบให้ใช้งานง่าย อ่านสบายตา รองรับการอบรมหลายคนด้วย Central API + FIFO Queue และช่วยตรวจคุณภาพรายงานอย่างเป็นระบบ
                        </div>
                        <div class="pill-row">
                            <span class="pill"><i class="bi bi-journal-check"></i> 14 องค์ประกอบรายงาน</span>
                            <span class="pill"><i class="bi bi-diagram-3"></i> Outbreak / Single Case</span>
                            <span class="pill"><i class="bi bi-shield-lock"></i> PII Pre-scan</span>
                            <span class="pill"><i class="bi bi-file-earmark-word"></i> Export Word</span>
                            <span class="pill"><i class="bi bi-people"></i> Central API + Workshop Queue</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="hero-side">
                <div class="feature-card">
                    <div class="feature-head"><span class="icon-chip"><i class="bi bi-cpu"></i></span> AI Review Engine</div>
                    <div class="feature-note">ตรวจหัวข้อสำคัญทางระบาดวิทยา พร้อมข้อเสนอแนะที่นำไปแก้ไขรายงานได้จริง</div>
                </div>
                <div class="feature-card">
                    <div class="feature-head"><span class="icon-chip"><i class="bi bi-hourglass-split"></i></span> Queue สำหรับห้องอบรม</div>
                    <div class="feature-note">ใช้คิวแบบ FIFO ลดการชนกันของ API และช่วยให้ผู้ใช้หลายคนใช้งานพร้อมกันได้ลื่นขึ้น</div>
                </div>
                <div class="feature-card">
                    <div class="feature-head"><span class="icon-chip"><i class="bi bi-patch-check"></i></span> Ready for publication</div>
                    <div class="feature-note">สรุประดับความพร้อม จุดแข็ง และสิ่งที่ต้องแก้ก่อนส่งตีพิมพ์ในมุมวิชาการ</div>
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
        <div class="mini-metric">
            <span class="metric-icon"><i class="bi bi-list-check"></i></span>
            <div><div class="num">14</div><div class="label">หัวข้อประเมินหลัก</div></div>
        </div>
        <div class="mini-metric">
            <span class="metric-icon"><i class="bi bi-bar-chart"></i></span>
            <div><div class="num">0–3</div><div class="label">คะแนนต่อองค์ประกอบ</div></div>
        </div>
        <div class="mini-metric">
            <span class="metric-icon"><i class="bi bi-shield-lock"></i></span>
            <div><div class="num">Central</div><div class="label">API Key กลางจาก Server</div></div>
        </div>
        <div class="mini-metric">
            <span class="metric-icon"><i class="bi bi-people"></i></span>
            <div><div class="num">30–50</div><div class="label">เหมาะกับ Workshop Mode</div></div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Workshop Mode status (shared across sessions in this app instance)
workshop_snapshot = WORKSHOP_QUEUE.snapshot()
st.markdown(
    f"""
    <div class="workshop-band">
        <div class="workshop-head">
            <div>
                <div class="workshop-title"><span class="section-icon"><i class="bi bi-people-fill"></i></span> Workshop Mode — สถานะการใช้งานรวม</div>
                <div class="workshop-subtitle">คิวแบบมาก่อนได้ก่อน (FIFO) และจำกัดจำนวนงาน AI พร้อมกัน เพื่อให้ใช้งานในห้องอบรมได้เสถียร</div>
            </div>
            <div class="pill"><i class="bi bi-lightning-charge"></i> Concurrent jobs: {workshop_snapshot['max_active']}</div>
        </div>
        <div class="workshop-grid">
            <div class="status-card">
                <div class="status-label"><i class="bi bi-cpu"></i> กำลังวิเคราะห์</div>
                <div class="status-value">{workshop_snapshot['active']} / {workshop_snapshot['max_active']}</div>
            </div>
            <div class="status-card">
                <div class="status-label"><i class="bi bi-hourglass-split"></i> กำลังรอคิว</div>
                <div class="status-value">{workshop_snapshot['waiting']}</div>
            </div>
            <div class="status-card">
                <div class="status-label"><i class="bi bi-check-circle"></i> เสร็จแล้ว</div>
                <div class="status-value">{workshop_snapshot['completed']}</div>
            </div>
            <div class="status-card">
                <div class="status-label"><i class="bi bi-collection"></i> งานทั้งหมด</div>
                <div class="status-value">{workshop_snapshot['submitted']}</div>
            </div>
        </div>
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
    st.markdown('<div class="sidebar-group">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-title"><i class="bi bi-sliders2"></i> ตั้งค่าระบบ</div>', unsafe_allow_html=True)
    if CENTRAL_GEMINI_API_KEY:
        st.success("🔐 Central API พร้อมใช้งาน")
        st.caption("ผู้ใช้งานไม่ต้องกรอก API Key ระบบจะใช้ Key กลางที่เก็บไว้บน server")
    else:
        st.error("⚠️ ยังไม่ได้ตั้งค่า Central API Key บน server")
        st.caption("ผู้ดูแลระบบต้องตั้งค่า GEMINI_API_KEY ใน Streamlit Secrets หรือ Environment Variable")
    default_model = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash")
    model_options = list(dict.fromkeys([default_model, "gemini-2.5-flash", "gemini-2.5-pro"]))
    model_name = st.selectbox(
        "🤖 โมเดลที่ใช้วิเคราะห์",
        options=model_options,
        index=0,
        help="การใช้งานพร้อมกันหลายคนควรใช้ Flash เพื่อลดเวลาและการใช้โควตา",
    )
    st.caption(
        "Central API Mode: ผู้ใช้ทุกคนใช้ API Key กลางของระบบ และระบบจัดคิว FIFO เพื่อควบคุมการใช้งานพร้อมกัน"
    )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-group">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-title"><i class="bi bi-shield-check"></i> ความปลอดภัยข้อมูล</div>', unsafe_allow_html=True)
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
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="sidebar-footer"><i class="bi bi-info-circle"></i> พัฒนาเพื่อสนับสนุนการประเมินรายงานสอบสวนโรคฉบับสมบูรณ์ โดยเน้นความถูกต้องทางระบาดวิทยา ความปลอดภัยข้อมูล และความพร้อมต่อการตีพิมพ์</div>',
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <div class="guide-card">
        <div class="section-title clean-title"><span class="section-icon"><i class="bi bi-map"></i></span> วิธีการใช้งาน</div>
        <ol class="guide-list">
            <li>ระบบเชื่อมต่อ Gemini ด้วย Central API Key ที่ผู้ดูแลตั้งค่าไว้ ผู้ใช้งานไม่ต้องกรอก Key</li>
            <li>เลือกประเภทการสอบสวน หรือเลือกให้ AI จำแนกจากเนื้อหารายงาน</li>
            <li>อัปโหลดไฟล์ PDF ที่เลือกข้อความได้ หรือไฟล์ DOCX</li>
            <li>กดเริ่มตรวจสอบรายงาน และรอคิวหากใช้งานพร้อมกันหลายคน</li>
            <li>ดาวน์โหลดผลประเมินเป็นไฟล์ Word เพื่อนำไปแก้ไขต้นฉบับ</li>
        </ol>
        <div class="guide-mini-grid">
            <div class="guide-mini"><i class="bi bi-file-earmark-pdf"></i><div><strong>ไฟล์ต้นฉบับ</strong><br>PDF ควรเลือกข้อความได้ หรือใช้ DOCX ต้นฉบับ</div></div>
            <div class="guide-mini"><i class="bi bi-shield-lock"></i><div><strong>PII Protection</strong><br>ระบบตรวจและ mask ข้อมูลผู้ป่วยก่อนวิเคราะห์ได้</div></div>
            <div class="guide-mini"><i class="bi bi-people"></i><div><strong>Workshop Ready</strong><br>รองรับการใช้งานพร้อมกันด้วยระบบคิวกลาง</div></div>
        </div>
        <div class="small-note">
            หมายเหตุ: ระบบมีการตรวจและ mask PII เบื้องต้น โดยเน้นข้อมูลผู้ป่วย/ผู้สัมผัส แต่ควรตรวจทานรายงานก่อนอัปโหลดทุกครั้ง
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

top_col1, top_col2 = st.columns([1.18, 0.82], gap="large")

with top_col1:
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title"><span class="section-icon"><i class="bi bi-inbox"></i></span> ข้อมูลนำเข้า</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="sub-card">
            <div class="sub-card-grid">
                <div class="sub-chip"><i class="bi bi-clipboard2-pulse"></i><div><strong>เลือกประเภท</strong><span>AI จำแนกเอง หรือกำหนดเป็น Outbreak / Single Case</span></div></div>
                <div class="sub-chip"><i class="bi bi-cloud-arrow-up"></i><div><strong>อัปโหลดไฟล์</strong><span>รองรับ PDF และ DOCX เพื่อความยืดหยุ่นในการใช้งาน</span></div></div>
                <div class="sub-chip"><i class="bi bi-search-heart"></i><div><strong>ตรวจคุณภาพไฟล์</strong><span>ระบบเช็กข้อความเบื้องต้นก่อนส่งต่อ AI</span></div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    report_type = st.radio(
        "ประเภทการสอบสวน:",
        [
            "ให้ AI จำแนกจากเนื้อหารายงาน",
            "สอบสวนการระบาด (Outbreak)",
            "สอบสวนเฉพาะราย (Single Case)",
        ],
        index=0,
    )
    uploaded_file = st.file_uploader("อัปโหลดไฟล์รายงาน (PDF / DOCX)", type=["pdf", "docx"])

    if uploaded_file:
        st.caption(f"📎 ไฟล์ที่เลือก: {uploaded_file.name}")

    st.markdown(
        """
        <div class="info-banner">
            <i class="bi bi-lightbulb"></i>
            <div>คำแนะนำ: PDF ควรเป็นไฟล์ที่ลากเลือกข้อความได้ หากเป็นภาพสแกนล้วนให้ทำ OCR ก่อน หรือใช้ต้นฉบับ DOCX เพื่อให้ AI อ่านเนื้อหาได้ครบมากขึ้น</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

with top_col2:
    st.markdown('<div class="helper-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title"><span class="section-icon"><i class="bi bi-magic"></i></span> ก่อนเริ่มวิเคราะห์</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="sub-card">
            <div class="sub-card-grid">
                <div class="sub-chip"><i class="bi bi-shield-check"></i><div><strong>Central API</strong><span>ผู้ใช้ไม่ต้องกรอก API Key ระบบใช้ Key กลางจาก Server</span></div></div>
                <div class="sub-chip"><i class="bi bi-hourglass-split"></i><div><strong>Queue กลาง</strong><span>ถ้าใช้งานพร้อมกันหลายคน ระบบจะเข้าคิวและเรียก AI ตามลำดับ</span></div></div>
                <div class="sub-chip"><i class="bi bi-file-earmark-check"></i><div><strong>ผลลัพธ์พร้อมใช้</strong><span>เมื่อวิเคราะห์เสร็จ สามารถดาวน์โหลด Word ไปแก้ต้นฉบับต่อได้</span></div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <ul class="helper-list">
            <li>ไฟล์ที่เหมาะที่สุดคือ <strong>DOCX</strong> หรือ PDF ที่เลือกข้อความได้</li>
            <li>ถ้าคนใช้งานจำนวนมาก ระบบจะแสดงสถานะคิวให้โดยอัตโนมัติ</li>
            <li>ส่วน <strong>ผลการประเมิน</strong> จะแสดงแบบเต็มความกว้างด้านล่างเพื่อให้อ่านง่ายขึ้น</li>
        </ul>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

if "feedback" not in st.session_state:
    st.session_state.feedback = None
    st.session_state.word_file = None
    st.session_state.pii_findings = []
    st.session_state.is_processing = False
    st.session_state.review_cache = {}
    st.session_state.active_job_id = None

st.markdown('<div class="result-card result-fullwidth">', unsafe_allow_html=True)
st.markdown('<div class="result-toolbar"><div class="section-title"><span class="section-icon"><i class="bi bi-clipboard-data"></i></span> ผลการประเมิน</div></div>', unsafe_allow_html=True)

start_clicked = st.button(
    "🚀 เริ่มตรวจสอบรายงาน",
    type="primary",
    use_container_width=True,
    disabled=st.session_state.is_processing,
)

if start_clicked:
    if not CENTRAL_GEMINI_API_KEY:
        st.error("❌ ระบบยังไม่ได้ตั้งค่า Central API Key กรุณาแจ้งผู้ดูแลระบบ")
    elif not uploaded_file:
        st.warning("⚠️ กรุณาอัปโหลดไฟล์ PDF หรือ DOCX ก่อนครับ")
    else:
        st.session_state.is_processing = True
        raw_text = ""
        try:
            with st.spinner("⏳ EpiScholar กำลังอ่านข้อความจากไฟล์..."):
                raw_text = extract_report_text(uploaded_file)
            source_quality = assess_source_quality(raw_text, uploaded_file.name)
            if source_quality["warnings"]:
                for warning in source_quality["warnings"]:
                    st.warning(f"⚠️ {warning}")
            if source_quality["chars"] < 500:
                st.error("❌ ระบบอ่านข้อความได้น้อยเกินไป จึงยังไม่ส่งข้อมูลเข้า AI เพื่อป้องกันการประเมินคลาดเคลื่อน")
                st.session_state.is_processing = False
                st.stop()
            st.caption(
                f"อ่านข้อความได้ประมาณ {source_quality['words']:,} คำ / {source_quality['chars']:,} ตัวอักษร"
                + (f" / {source_quality['pages']} หน้า" if source_quality['pages'] else "")
            )
        except Exception as exc:
            st.session_state.is_processing = False
            st.error(str(exc))
            st.stop()

        pii_findings = scan_pii(raw_text, strict_staff_names=strict_staff_names)
        text_for_analysis = mask_pii(raw_text, strict_staff_names=strict_staff_names) if mask_before_send else raw_text

        if pii_findings:
            st.warning("⚠️ ตรวจพบข้อมูลที่อาจเป็น PII ระบบได้ mask เบื้องต้นก่อนวิเคราะห์แล้ว" if mask_before_send else "⚠️ ตรวจพบข้อมูลที่อาจเป็น PII แต่ขณะนี้ไม่ได้เปิดการ mask")
            with st.expander("ดูประเภทข้อมูลที่ตรวจพบ", expanded=False):
                for item in pii_findings:
                    st.write(f"- {item}")

        cache_key = make_review_cache_key(text_for_analysis, report_type, model_name)
        try:
            cached = st.session_state.review_cache.get(cache_key)
            if cached:
                feedback = cached
                st.info("ℹ️ ใช้ผลวิเคราะห์เดิมใน session นี้ เพื่อลดการเรียก API ซ้ำ")
            else:
                if not st.session_state.active_job_id:
                    st.session_state.active_job_id = uuid.uuid4().hex
                feedback = analyze_report_with_retry(
                    api_key=CENTRAL_GEMINI_API_KEY,
                    text=text_for_analysis,
                    report_type=report_type,
                    model_name=model_name,
                    pii_findings=pii_findings,
                    job_id=st.session_state.active_job_id,
                )
                if feedback and not feedback.startswith("❌"):
                    st.session_state.review_cache[cache_key] = feedback
        finally:
            st.session_state.is_processing = False
            st.session_state.active_job_id = None

        if feedback.startswith("❌"):
            st.error(feedback)
        else:
            st.session_state.feedback = feedback
            st.session_state.pii_findings = pii_findings
            st.session_state.word_file = create_word_doc(feedback, report_type, pii_findings)
            st.markdown('<div class="success-card">✅ วิเคราะห์เสร็จสมบูรณ์ พร้อมดาวน์โหลดเป็น Word</div>', unsafe_allow_html=True)

if st.session_state.feedback:
    st.markdown("### ผลลัพธ์")
    score_summary = parse_score_summary(st.session_state.feedback)
    if score_summary["count"] == 14:
        m1, m2, m3 = st.columns(3)
        m1.metric("คะแนนรวม", f"{score_summary['total']} / {score_summary['max']}")
        m2.metric("ร้อยละ", f"{score_summary['pct']}%")
        m3.metric("องค์ประกอบที่ประเมิน", "14 / 14")
    else:
        st.warning(f"⚠️ ตรวจจับคะแนนได้ {score_summary['count']} จาก 14 หัวข้อ ควรตรวจผลลัพธ์ก่อนนำไปใช้")
    st.markdown(st.session_state.feedback)

    st.download_button(
        label="💾 ดาวน์โหลดผลการประเมิน (Word)",
        data=st.session_state.word_file,
        file_name="EpiScholar_Workshop_v6_Wide_Result.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True,
    )
else:
    st.markdown(
        """
        <div class="results-placeholder">
            <i class="bi bi-clipboard2-heart"></i>
            <div><strong>ยังไม่มีผลการประเมิน</strong></div>
            <div>อัปโหลดรายงาน PDF หรือ DOCX แล้วกดเริ่มตรวจสอบ เพื่อให้ระบบประเมินรายงานตามหลักระบาดวิทยา</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown('</div>', unsafe_allow_html=True)
