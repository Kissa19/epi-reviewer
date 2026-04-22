import streamlit as st
import PyPDF2
import google.generativeai as genai
import io
import time
from docx import Document

# ==========================================
# 1. ตั้งค่าหน้าจอและ Theme (Kanit Font & DDC Pink)
# ==========================================
st.set_page_config(page_title="EpiScholar | AI Reviewer", page_icon="📋", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;600&display=swap');

    html, body, [class*="css"], .stMarkdown, .stText, .stButton, .stTextInput, .stSelectbox, .stRadio, .stHeader {
        font-family: 'Kanit', sans-serif !important;
    }

    .stApp { background-color: #FFFFFF; }
    
    section[data-testid="stSidebar"] {
        background-color: #880E4F !important;
        color: white !important;
    }
    section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] label {
        color: white !important;
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

    div.stButton > button:first-child {
        background-color: #D81B60;
        color: white;
        border-radius: 8px;
        font-weight: 600;
        border: none;
    }
    div.stButton > button:first-child:hover {
        background-color: #AD1457;
        color: white;
    }

    .result-container {
        background-color: #FDF2F6;
        padding: 25px;
        border-radius: 15px;
        border-left: 6px solid #D81B60;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ==========================================
# 2. กฎเกณฑ์ของ AI (System Instruction)
# ==========================================
SYSTEM_INSTRUCTION = """
บทบาท (Role):
คุณคือผู้เชี่ยวชาญด้านระบาดวิทยา และผู้ประเมินรายงานสอบสวนโรคระดับชาติ หน้าที่ของคุณคือการอ่าน "รายงานสอบสวนโรคฉบับสมบูรณ์ (Full Report)" และให้ข้อเสนอแนะเชิงวิจารณ์ (Constructive Feedback)

กฎเหล็กด้านความปลอดภัยของข้อมูล (CRITICAL RULE):
ห้ามมีข้อมูลส่วนบุคคล (PII): หากรายงานมีการระบุ ชื่อ, นามสกุล, เลขประจำตัวผู้ป่วย (HN), หรือ เลขบัตรประชาชน 13 หลัก ให้แจ้งเตือนเป็นข้อผิดพลาดร้ายแรง (Fatal Error) ทันที

คำสั่ง (Task):
วิเคราะห์ตามเกณฑ์ 14 หัวข้อหลัก ตรวจสอบ Epidemic Curve (Interval 1/3-1/8), สถิติวิเคราะห์, มาตรการ 5W1H และสรุปผลภายใต้เงื่อนไข 2 เท่าของระยะฟักตัว
"""

# ==========================================
# 3. ฟังก์ชันการประมวลผล (พร้อมระบบ Retry เมื่อเจอ 429)
# ==========================================
def extract_text_from_pdf(pdf_file):
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        if page.extract_text():
            text += page.extract_text() + "\n"
    return text

def analyze_report_with_retry(api_key, text, report_type):
    genai.configure(api_key=api_key)
    model_name = "gemini-2.5-flash"
    
    # ระบบ Retry 3 รอบ
    max_retries = 3
    for attempt in range(max_retries):
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=SYSTEM_INSTRUCTION + f"\n\n**บริบท:** รายงานนี้เป็นการ {report_type}"
            )
            response = model.generate_content(f"โปรดประเมินรายงานดังนี้:\n\n{text}")
            return response.text
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "quota" in err_msg.lower():
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 10 # รอเพิ่มขึ้นเรื่อยๆ 10, 20 วินาที
                    st.warning(f"⚠️ โควตาการใช้งานชั่วคราวเต็ม (429) กำลังรอคิว {wait_time} วินาทีเพื่อลองใหม่...")
                    time.sleep(wait_time)
                    continue
                else:
                    return "❌ ขออภัยครับ โควตา API ฟรีของคุณหมดลงชั่วคราว (จำกัด 5 ครั้งต่อนาที) กรุณารอสัก 1-2 นาทีแล้วลองใหม่อีกครั้งครับ"
            return f"❌ พบข้อผิดพลาด: {e}"

def create_word_doc(feedback_text):
    doc = Document()
    doc.add_heading('ผลการประเมินรายงานสอบสวนโรค (EpiScholar)', 0)
    for line in feedback_text.split('\n'):
        doc.add_paragraph(line)
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ==========================================
# 4. ส่วนแสดงผล (UI)
# ==========================================
st.title("📋 EpiScholar: ระบบประเมินรายงานอัจฉริยะ")
st.markdown("**กลุ่มระบาดวิทยาและตอบโต้ภาวะฉุกเฉินทางสาธารณสุข สคร.8 อุดรธานี**")

with st.sidebar:
    st.header("⚙️ ตั้งค่าระบบ")
    api_key_input = st.text_input("🔑 Gemini API Key", type="password")
    st.markdown("---")
    st.markdown('<div class="sidebar-footer">พัฒนาโดยกลุ่มระบาดวิทยาและตอบโต้ภาวะฉุกเฉินทางสาธารณสุข สคร.8 อุดรธานี กรมควบคุมโรค</div>', unsafe_allow_html=True)

with st.expander("📖 วิธีการใช้งานระบบ (User Manual)", expanded=False):
    st.markdown("""
    1. **API Key:** ระบุ Gemini API Key ที่แถบด้านซ้าย
    2. **ประเภท:** เลือกประเภทรายงาน (Outbreak / Single Case)
    3. **อัปโหลด:** เลือกไฟล์ PDF (ต้องปกปิดข้อมูลส่วนบุคคลแล้ว)
    4. **วิเคราะห์:** หากพบข้อผิดพลาด 429 (Quota Exceeded) ระบบจะรอคิวและพยายามใหม่ให้โดยอัตโนมัติ
    """)

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📥 ข้อมูลนำเข้า")
    report_type = st.radio("ประเภทการสอบสวน:", ["สอบสวนการระบาด (Outbreak)", "สอบสวนเฉพาะราย (Single Case)"])
    uploaded_file = st.file_uploader("อัปโหลดไฟล์รายงาน (PDF)", type=["pdf"])

with col2:
    st.subheader("📊 ผลการประเมิน")
    if st.button("🚀 เริ่มตรวจสอบรายงาน", type="primary", use_container_width=True):
        if not api_key_input:
            st.warning("⚠️ กรุณาระบุ API Key ก่อนครับ")
        elif not uploaded_file:
            st.warning("⚠️ กรุณาอัปโหลดไฟล์ PDF")
        else:
            with st.spinner("⏳ EpiScholar กำลังวิเคราะห์รายงาน..."):
                try:
                    raw_text = extract_text_from_pdf(uploaded_file)
                    feedback = analyze_report_with_retry(api_key_input, raw_text, report_type)
                    
                    if "❌" in feedback:
                        st.error(feedback)
                    else:
                        st.success("✅ วิเคราะห์เสร็จสมบูรณ์!")
                        st.markdown(f'<div class="result-container">{feedback}</div>', unsafe_allow_html=True)
                        
                        word_file = create_word_doc(feedback)
                        st.download_button(
                            label="💾 ดาวน์โหลดผลการประเมิน (Word)",
                            data=word_file,
                            file_name="EpiScholar_Feedback.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            use_container_width=True
                        )
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาดรุนแรง: {e}")
