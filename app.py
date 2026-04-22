import streamlit as st
import PyPDF2
import google.generativeai as genai
import io
from docx import Document

# ==========================================
# 1. ตั้งค่าหน้าจอและ Theme (DDC Pink & Kanit Font)
# ==========================================
st.set_page_config(page_title="EpiScholar | AI Reviewer", page_icon="📋", layout="wide")

# Custom CSS สำหรับฟอนต์ Kanit, ธีมสีชมพู และปรับสี Footer เป็นสีขาว
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;600&display=swap');

    /* กำหนดฟอนต์ Kanit ทั้งระบบ */
    html, body, [class*="css"], .stMarkdown, .stText, .stButton, .stTextInput, .stSelectbox, .stRadio, .stHeader {
        font-family: 'Kanit', sans-serif !important;
    }

    /* สีพื้นหลังหลัก */
    .stApp {
        background-color: #FFFFFF;
    }
    
    /* ปรับแต่ง Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #880E4F !important; /* ชมพูเข้มกรมควบคุมโรค */
        color: white !important;
    }
    section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] label {
        color: white !important;
    }

    /* ปรับแต่งข้อความ "พัฒนาโดย" ให้เป็นสีขาวชัดเจน */
    .sidebar-footer {
        color: #FFFFFF !important; /* เปลี่ยนเป็นสีขาวตามคำขอ */
        font-size: 14px;
        font-weight: 400;
        margin-top: 20px;
        padding: 10px;
        background-color: rgba(255, 255, 255, 0.1); /* เพิ่มพื้นหลังจางๆ ให้ดูมีมิติ */
        border-radius: 8px;
        line-height: 1.5;
    }

    /* ปุ่ม Primary (สีชมพูกรมควบคุมโรค) */
    div.stButton > button:first-child {
        background-color: #D81B60;
        color: white;
        border-radius: 8px;
        border: none;
        font-weight: 600;
        font-family: 'Kanit', sans-serif !important;
    }
    div.stButton > button:first-child:hover {
        background-color: #AD1457;
        border: none;
        color: white;
    }

    /* กล่องผลลัพธ์ */
    .result-container {
        background-color: #FDF2F6;
        padding: 20px;
        border-radius: 12px;
        border-left: 5px solid #D81B60;
        font-family: 'Kanit', sans-serif !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ==========================================
# 2. กฎเกณฑ์ของ AI (System Instruction เวอร์ชันผู้เชี่ยวชาญ)
# ==========================================
SYSTEM_INSTRUCTION = """
บทบาท (Role):
คุณคือผู้เชี่ยวชาญด้านระบาดวิทยา และผู้ประเมินรายงานสอบสวนโรคระดับชาติ หน้าที่ของคุณคือการอ่าน "รายงานสอบสวนโรคฉบับสมบูรณ์ (Full Report)" และให้ข้อเสนอแนะเชิงวิจารณ์ (Constructive Feedback)

กฎเหล็กด้านความปลอดภัยของข้อมูล (CRITICAL RULE):
ห้ามมีข้อมูลส่วนบุคคล (PII): หากรายงานมีการระบุ ชื่อ, นามสกุล, เลขประจำตัวผู้ป่วย (HN), หรือ เลขบัตรประชาชน 13 หลัก ให้แจ้งเตือนเป็นข้อผิดพลาดร้ายแรง (Fatal Error) ทันที และแนะนำให้ผู้เขียนทำข้อมูลให้เป็นนิรนาม (Anonymization)

คำสั่ง (Task):
จงวิเคราะห์ข้อความรายงานสอบสวนโรคอย่างละเอียด โดยแบ่งการทำงานเป็น 2 ขั้นตอนหลัก:

ขั้นตอนที่ 1: ตรวจสอบความครบถ้วนของโครงสร้างรายงาน 14 หัวข้อหลัก
เช็คว่ามี: 1. ชื่อเรื่อง 2. ผู้รายงานและทีม 3. บทคัดย่อ 4. ความเป็นมา 5. วัตถุประสงค์ 6. วิธีการสอบสวน 7. ผลการสอบสวน 8. มาตรการควบคุมป้องกันโรค 9. วิจารณ์ผล 10. ปัญหาและข้อจำกัด 11. ข้อเสนอแนะ 12. สรุปผล 13. กิตติกรรมประกาศ 14. เอกสารอ้างอิง

ขั้นตอนที่ 2: ประเมินคุณภาพและให้ข้อเสนอแนะรายหัวข้อ
* วัตถุประสงค์: ตรวจสอบความสอดคล้อง (เฉพาะรายต้องเพื่อวินิจฉัย/หาแหล่งโรค, การระบาดต้องยืนยันเหตุการณ์/ศึกษา Person Time Place)
* วิธีการสอบสวน: เช็คนิยามผู้ป่วย (Time ต้องครอบคลุมอย่างน้อย 1 เท่าของระยะฟักตัวก่อน Index Case)
* ผลการสอบสวน: เช็ค Epidemic Curve (Interval 1/3-1/8 ของระยะฟักตัว), สถิติวิเคราะห์ และผลสิ่งแวดล้อม/Lab
* มาตรการควบคุม: ต้องระบุกิจกรรม 5W1H ทั้งระยะสั้นและยาว
* วิจารณ์ผล: ไม่อธิบายตัวเลขซ้ำ อภิปรายจุดอ่อนและเปรียบเทียบเอกสารวิชาการ
* สรุปผล: ตอบวัตถุประสงค์ และระบุว่าควบคุมโรคได้หรือไม่ (ภายใน 2 เท่าระยะฟักตัวยาวสุด)

รูปแบบผลลัพธ์ (Output Format):
1. คำแนะนำเบื้องต้น (แจ้งเตือน PII ถ้ามี)
2. 📋 ส่วนที่ 1: การตรวจสอบความครบถ้วน 14 หัวข้อหลัก (✅/❌)
3. 📝 ส่วนที่ 2: ความคิดเห็นและข้อเสนอแนะรายหัวข้อ
4. 💡 ส่วนที่ 3: ตัวอย่างการปรับแก้
"""

# ==========================================
# 3. ฟังก์ชันการทำงานหลัก
# ==========================================
def extract_text_from_pdf(pdf_file):
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        if page.extract_text():
            text += page.extract_text() + "\n"
    return text

def analyze_report(api_key, text, report_type):
    genai.configure(api_key=api_key)
    dynamic_prompt = SYSTEM_INSTRUCTION + f"\n\n**ข้อมูลเพิ่มเติม:** รายงานนี้เป็นการ {report_type}"
    try:
        model = genai.GenerativeModel(model_name="gemini-1.5-flash", system_instruction=dynamic_prompt)
        response = model.generate_content(f"โปรดประเมินรายงานต่อไปนี้:\n\n{text}")
        return response.text
    except Exception as e:
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

# Sidebar
with st.sidebar:
    st.header("⚙️ ตั้งค่าระบบ")
    api_key_input = st.text_input("🔑 Gemini API Key", type="password")
    st.markdown("---")
    # ส่วน Footer ปรับเป็นสีขาวตามคำขอ
    st.markdown('<div class="sidebar-footer">พัฒนาโดยกลุ่มระบาดวิทยาและตอบโต้ภาวะฉุกเฉินทางสาธารณสุข สคร.8 อุดรธานี กรมควบคุมโรค</div>', unsafe_allow_html=True)

# Main Interface
with st.expander("📖 วิธีการใช้งานระบบ (User Manual)", expanded=False):
    st.markdown("""
    1. **ตั้งค่า API Key:** ใส่ Gemini API Key ที่แถบด้านซ้าย
    2. **เลือกประเภทรายงาน:** เลือกประเภทการสอบสวน (Outbreak / Single Case)
    3. **อัปโหลด PDF:** ไฟล์รายงานต้องทำข้อมูลเป็นนิรนาม (Anonymized) แล้ว
    4. **ประเมินผล:** กดปุ่มเริ่มตรวจสอบ และรอ AI วิเคราะห์
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
            with st.spinner("⏳ EpiScholar กำลังวิเคราะห์เชิงวิชาการ..."):
                try:
                    raw_text = extract_text_from_pdf(uploaded_file)
                    feedback = analyze_report(api_key_input, raw_text, report_type)
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
                    st.error(f"เกิดข้อผิดพลาด: {e}")
