import io
import re
import time
from datetime import datetime

import streamlit as st
import PyPDF2
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import google.generativeai as genai

# =========================================================
# EpiScholar: AI Reviewer for Investigation Report
# Single-file Streamlit App
# =========================================================

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

    html, body, [class*="css"], .stMarkdown, .stText, .stButton, .stTextInput,
    .stSelectbox, .stRadio, .stHeader, .stFileUploader, .stDownloadButton {
        font-family: 'Kanit', sans-serif !important;
    }

    .stApp { background-color: #FFFFFF; }

    section[data-testid="stSidebar"] {
        background-color: #880E4F !important;
        color: white !important;
    }

    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span {
        color: white !important;
    }

    div.stButton > button:first-child,
    div.stDownloadButton > button:first-child {
        background-color: #D81B60;
        color: white;
        border-radius: 10px;
        font-weight: 600;
        border: none;
        padding: 0.6rem 1rem;
    }

    div.stButton > button:first-child:hover,
    div.stDownloadButton > button:first-child:hover {
        background-color: #AD1457;
        color: white;
        border: none;
    }

    .hero-box {
        background: linear-gradient(135deg, #FCE4EC 0%, #FFFFFF 70%);
        border-left: 7px solid #D81B60;
        padding: 22px 26px;
        border-radius: 18px;
        margin-bottom: 16px;
    }

    .result-container {
        background-color: #FDF2F6;
        padding: 24px;
        border-radius: 16px;
        border-left: 6px solid #D81B60;
        line-height: 1.75;
        white-space: normal;
    }

    .sidebar-footer {
        color: #FFFFFF !important;
        font-size: 14px;
        font-weight: 400;
        margin-top: 20px;
        padding: 12px;
        background-color: rgba(255, 255, 255, 0.15);
        border-radius: 10px;
        line-height: 1.6;
    }

    .small-note {
        color: #6B7280;
        font-size: 0.92rem;
        line-height: 1.6;
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
1. หากพบข้อมูลส่วนบุคคล เช่น ชื่อ-สกุลผู้ป่วย, HN, เลขบัตรประชาชน 13 หลัก, เบอร์โทร, ที่อยู่ละเอียด หรือข้อมูลระบุตัวบุคคล ให้จัดเป็น "Fatal Error"
2. ห้ามคัดลอกข้อมูลส่วนบุคคลซ้ำในคำตอบ ให้ระบุเพียงประเภทข้อมูลที่พบ
3. หากข้อมูลไม่เพียงพอ ห้ามเดา ให้ระบุว่า "ไม่พบข้อมูลในรายงาน" หรือ "ยังประเมินไม่ได้จากข้อมูลที่มี"

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


def scan_pii(text: str) -> list[str]:
    """Basic local pre-scan for common PII patterns before sending to API."""
    findings = []

    if re.search(r"\b\d{13}\b", text):
        findings.append("พบเลข 13 หลักที่อาจเป็นเลขประจำตัวประชาชน")

    if re.search(r"\b0\d{8,9}\b", text):
        findings.append("พบตัวเลขที่อาจเป็นเบอร์โทรศัพท์")

    if re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text):
        findings.append("พบอีเมล")

    if re.search(r"\b(?:HN|H\.N\.|AN|A\.N\.)\s*[:：]?\s*[A-Za-z0-9/-]{4,}\b", text, flags=re.IGNORECASE):
        findings.append("พบรหัสผู้ป่วย เช่น HN/AN")

    # Thai full-name clues. This is intentionally conservative and may not catch all names.
    if re.search(r"(?:นาย|นาง|นางสาว|ด\.ช\.|ด\.ญ\.)\s*[ก-๙]{2,}\s+[ก-๙]{2,}", text):
        findings.append("พบรูปแบบชื่อ-สกุลภาษาไทยที่อาจเป็นข้อมูลส่วนบุคคล")

    return findings


def mask_pii(text: str) -> str:
    """Mask common PII patterns locally before API submission."""
    masked = text
    masked = re.sub(r"\b\d{13}\b", "[MASKED_ID_13_DIGITS]", masked)
    masked = re.sub(r"\b0\d{8,9}\b", "[MASKED_PHONE]", masked)
    masked = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[MASKED_EMAIL]", masked)
    masked = re.sub(
        r"\b(?:HN|H\.N\.|AN|A\.N\.)\s*[:：]?\s*[A-Za-z0-9/-]{4,}\b",
        "[MASKED_PATIENT_CODE]",
        masked,
        flags=re.IGNORECASE,
    )
    masked = re.sub(
        r"(?:นาย|นาง|นางสาว|ด\.ช\.|ด\.ญ\.)\s*[ก-๙]{2,}\s+[ก-๙]{2,}",
        "[MASKED_THAI_NAME]",
        masked,
    )
    return masked


def build_user_prompt(report_text: str, report_type: str, pii_findings: list[str]) -> str:
    pii_note = "ไม่พบ PII จากการตรวจเบื้องต้นของระบบ"
    if pii_findings:
        pii_note = "ระบบตรวจพบและ mask PII เบื้องต้นก่อนส่งวิเคราะห์ ได้แก่: " + "; ".join(pii_findings)

    return f"""
ประเภทที่ผู้ใช้เลือก: {report_type}
ผลการตรวจ PII เบื้องต้น: {pii_note}

โปรดประเมินรายงานสอบสวนโรคต่อไปนี้ตามเกณฑ์ใน System Instruction
หากประเภทที่ผู้ใช้เลือกไม่สอดคล้องกับเนื้อหารายงาน ให้แจ้งเตือนและอธิบายเหตุผล

ข้อกำหนดการตอบ:
- ห้ามใช้ markdown table
- ห้ามใช้ตารางแนวนอน
- ให้ตอบเป็นหัวข้อเรียงลำดับ
- แต่ละหัวข้อให้กระชับแต่ครบถ้วน
- ข้อเสนอแนะต้องนำไปแก้ไขรายงานได้จริง
- หากข้อมูลไม่พบ ให้ระบุว่า "ไม่พบข้อมูลในรายงาน"

เนื้อหารายงาน:
{report_text}
"""


def analyze_report_with_retry(api_key: str, text: str, report_type: str, model_name: str, pii_findings: list[str]) -> str:
    """Call Gemini API with retry for quota/rate-limit errors."""
    genai.configure(api_key=api_key)
    max_retries = 3

    user_prompt = build_user_prompt(text, report_type, pii_findings)

    for attempt in range(max_retries):
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=SYSTEM_INSTRUCTION,
            )
            response = model.generate_content(
                user_prompt,
                generation_config={
                    "temperature": 0.2,
                    "top_p": 0.8,
                    "top_k": 40,
                    "max_output_tokens": 8192,
                },
            )

            feedback = getattr(response, "text", "") or ""
            feedback = normalize_text_for_display(feedback)
            if not feedback.strip():
                return "❌ โมเดลไม่ส่งผลลัพธ์กลับมา กรุณาลองใหม่ หรือลดความยาวรายงาน"
            return feedback

        except Exception as exc:
            err_msg = str(exc)
            if "429" in err_msg or "quota" in err_msg.lower() or "rate" in err_msg.lower():
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 10
                    st.warning(f"⚠️ โควตาการใช้งานชั่วคราวเต็ม กำลังรอ {wait_time} วินาทีก่อนลองใหม่...")
                    time.sleep(wait_time)
                    continue
                return "❌ โควตา API เต็มชั่วคราว กรุณารอสักครู่แล้วลองใหม่อีกครั้ง"

            return f"❌ พบข้อผิดพลาดจากการเรียก API: {exc}"

    return "❌ วิเคราะห์ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"


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
        doc.add_paragraph("ระบบตรวจพบและ mask ข้อมูลที่อาจเป็น PII ก่อนส่งวิเคราะห์ ดังนี้")
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
    """
    <div class="hero-box">
        <h1 style="margin-bottom: 0.2rem; color: #880E4F;">📋 EpiScholar: ระบบประเมินรายงานสอบสวนโรค</h1>
        <div style="font-size: 1.05rem; color: #4B5563;">
            กลุ่มระบาดวิทยาและตอบโต้ภาวะฉุกเฉินทางสาธารณสุข สคร.8 อุดรธานี กรมควบคุมโรค
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("⚙️ ตั้งค่าระบบ")
    api_key_input = st.text_input("🔑 Gemini API Key", type="password")
    model_name = st.selectbox(
        "🤖 โมเดลที่ใช้วิเคราะห์",
        options=["gemini-2.5-flash", "gemini-2.5-pro"],
        index=0,
        help="แนะนำ gemini-2.5-flash สำหรับความเร็วและต้นทุนต่ำกว่า",
    )
    mask_before_send = st.checkbox(
        "Mask PII ก่อนส่งเข้า AI",
        value=True,
        help="แนะนำให้เปิดไว้เสมอ เพื่อความปลอดภัยของข้อมูล",
    )
    st.markdown("---")
    st.markdown(
        '<div class="sidebar-footer">พัฒนาเพื่อสนับสนุนการประเมินรายงานสอบสวนโรคฉบับสมบูรณ์ โดยเน้น 14 องค์ประกอบ ระบาดวิทยาภาคสนาม และความพร้อมต่อการตีพิมพ์</div>',
        unsafe_allow_html=True,
    )

with st.expander("📖 วิธีการใช้งาน", expanded=False):
    st.markdown(
        """
        1. ระบุ Gemini API Key ที่แถบด้านซ้าย
        2. เลือกประเภทการสอบสวน หรือเลือกให้ AI จำแนกจากเนื้อหารายงาน
        3. อัปโหลดไฟล์ PDF ที่เลือกข้อความได้ ไม่ใช่ภาพสแกนล้วน
        4. กดเริ่มตรวจสอบรายงาน
        5. ดาวน์โหลดผลประเมินเป็นไฟล์ Word

        หมายเหตุ: ระบบมีการตรวจและ mask PII เบื้องต้น แต่ควรปกปิดข้อมูลส่วนบุคคลในรายงานก่อนอัปโหลดทุกครั้ง
        """
    )

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📥 ข้อมูลนำเข้า")
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

    st.markdown(
        """
        <div class="small-note">
        คำแนะนำ: หากเป็น PDF ที่สแกนจากภาพ ระบบอาจอ่านข้อความได้น้อย ควรใช้ไฟล์ PDF ที่สามารถลากเลือกข้อความได้
        </div>
        """,
        unsafe_allow_html=True,
    )

with col2:
    st.subheader("📊 ผลการประเมิน")

    if "feedback" not in st.session_state:
        st.session_state.feedback = None
        st.session_state.word_file = None
        st.session_state.pii_findings = []

    if st.button("🚀 เริ่มตรวจสอบรายงาน", type="primary", use_container_width=True):
        if not api_key_input:
            st.warning("⚠️ กรุณาระบุ Gemini API Key ก่อนครับ")
        elif not uploaded_file:
            st.warning("⚠️ กรุณาอัปโหลดไฟล์ PDF ก่อนครับ")
        else:
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

            pii_findings = scan_pii(raw_text)
            text_for_analysis = mask_pii(raw_text) if mask_before_send else raw_text

            if pii_findings:
                st.warning("⚠️ ตรวจพบข้อมูลที่อาจเป็น PII ระบบได้ mask เบื้องต้นก่อนวิเคราะห์แล้ว" if mask_before_send else "⚠️ ตรวจพบข้อมูลที่อาจเป็น PII แต่ขณะนี้ไม่ได้เปิดการ mask")
                with st.expander("ดูประเภทข้อมูลที่ตรวจพบ", expanded=False):
                    for item in pii_findings:
                        st.write(f"- {item}")

            with st.spinner("⏳ EpiScholar กำลังวิเคราะห์รายงาน..."):
                feedback = analyze_report_with_retry(
                    api_key=api_key_input,
                    text=text_for_analysis,
                    report_type=report_type,
                    model_name=model_name,
                    pii_findings=pii_findings,
                )

            if feedback.startswith("❌"):
                st.error(feedback)
            else:
                st.session_state.feedback = feedback
                st.session_state.pii_findings = pii_findings
                st.session_state.word_file = create_word_doc(feedback, report_type, pii_findings)
                st.success("✅ วิเคราะห์เสร็จสมบูรณ์")

    if st.session_state.feedback:
        st.markdown("### ผลลัพธ์")
        # Avoid unsafe HTML for model output.
        st.markdown(st.session_state.feedback)

        st.download_button(
            label="💾 ดาวน์โหลดผลการประเมิน (Word)",
            data=st.session_state.word_file,
            file_name="EpiScholar_Feedback.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
