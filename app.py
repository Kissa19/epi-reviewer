import streamlit as st
import PyPDF2
import google.generativeai as genai
import io
from docx import Document

# ==========================================
# 1. ตั้งค่าหน้าจอและ Theme (DDC Pink & Prompt Font)
# ==========================================
st.set_page_config(page_title="EpiScholar | AI Reviewer", page_icon="📋", layout="wide")

# Custom CSS สำหรับฟอนต์ Prompt และธีมสีชมพู-ขาว
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;600&display=swap');

    /* ฟอนต์ทั้งระบบ */
    html, body, [class*="css"], .stMarkdown, .stText, .stButton, .stTextInput, .stSelectbox, .stRadio, .stHeader {
        font-family: 'Prompt', sans-serif !important;
    }

    /* สีพื้นหลังและ Header */
    .stApp {
        background-color: #FFFFFF;
    }
    
    /* ปรับแต่ง Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #880E4F !important;
        color: white !important;
    }
    section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] label {
        color: white !important;
    }

    /* ปุ่ม Primary (สีชมพูกรมควบคุมโรค) */
    div.stButton > button:first-child {
        background-color: #D81B60;
        color: white;
        border-radius: 8px;
        border: none;
        font-weight: 600;
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
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ==========================================
# 2. กฎเกณฑ์ของ AI (System Instruction ล่าสุด)
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
* วัตถุประสงค์: ตรวจสอบว่าสอดคล้องกับประเภทการสอบสวนหรือไม่ 
    - สอบสวนเฉพาะราย: ต้องมี (เพื่อยืนยันการวินิจฉัย, ค้นหาแหล่งโรค/ลักษณะการเกิดโรค, หาแนวทางควบคุมป้องกัน)
    - สอบสวนการระบาด: ต้องมี (1.ยืนยันการวินิจฉัยและการระบาด 2.ศึกษาลักษณะทางระบาดวิทยาตาม Person, Time, Place 3.ค้นหาแหล่งโรค/วิธีการถ่ายทอด/ผู้สัมผัส 4.หามาตรการควบคุมป้องกัน)
* วิธีการสอบสวน: เช็คนิยามผู้ป่วย (Person, Place, Time, Clinical criteria)
    - Time: การค้นหาผู้ป่วยต้องครอบคลุมอย่างน้อย 1 เท่าของระยะฟักตัวยาวสุดก่อนหน้า Index Case
    - อาการ: เลือกอาการที่เฉพาะเจาะจง (Specific) อ้างอิงนิยามปี 2563 (สงสัย/เข้าข่าย/ยืนยัน)
* การศึกษาระบาดวิทยาเชิงวิเคราะห์ (Optional): เช็คการระบุรูปแบบการศึกษา (Cohort, Case-Control) 
* ผลการสอบสวน: เช็ค Epidemic Curve (Time interval 1/3-1/8 ของระยะฟักตัว), ตาราง Bivariate/Multiple Logistic Regression, การสำรวจสิ่งแวดล้อม (ค่า อ.31, SI-2) และผล Lab
* มาตรการควบคุมป้องกันโรค: ต้องระบุกิจกรรม 5W1H (ใคร ทำอะไร ที่ไหน เมื่อไหร่ อย่างไร) ทั้งระยะสั้นและยาว
* วิจารณ์ผล: ห้ามอธิบายตัวเลขซ้ำกับผลการสอบสวน ให้อภิปรายจุดอ่อน ข้อจำกัด และเปรียบเทียบเอกสารวิชาการ
* สรุปผล: สั้น กระชับ ตอบวัตถุประสงค์ ระบุว่าควบคุมโรคได้หรือไม่ (ภายใน 2 เท่าระยะฟักตัวยาวสุด)

รูปแบบผลลัพธ์ (Output Format):
1. คำแนะนำเบื้องต้น (แจ้งเตือน PII ถ้ามี)
2. 📋 ส่วนที่ 1: การตรวจสอบความครบถ้วน 14 หัวข้อหลัก (ใช้ ✅ หรือ ❌)
3. 📝 ส่วนที่ 2: ความคิดเห็นและข้อเสนอแนะรายหัวข้อ
4. 💡 ส่วนที่ 3: ตัวอย่างการปรับแก้
"""

# ==========================================
# 3. ฟังก์ชันการทำงาน
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
    dynamic_prompt = SYSTEM_INSTRUCTION + f"\n\n**ข้อมูลเพิ่มเติมจากระบบ:** รายงานฉบับนี้เป็นการ {report_type}"
    
    try:
        model = genai.GenerativeModel(model_name="gemini-1.5-flash", system_instruction=dynamic_prompt)
        response = model.generate_content(f"โปรดประเมินรายงานสอบสวนโรคต่อไปนี้:\n\n{text}")
        return response.text
    except Exception as e:
        return f"❌ พบข้อผิดพลาดของระบบ: {e}"

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

# --- ส่วนวิธีการใช้งาน ---
with st.expander("📖 วิธีการใช้งานระบบ (User Manual)", expanded=False):
    st.markdown("""
    1. **ระบุ API Key:** ใส่ Gemini API Key ที่แถบด้านซ้าย
    2. **เลือกประเภทรายงาน:** เลือก 'Outbreak' หรือ 'Single Case'
    3. **อัปโหลด PDF:** เลือกไฟล์รายงานฉบับสมบูรณ์ที่ทำเป็นนิรนาม (Anonymized) แล้ว
    4. **ประเมินผล:** กดปุ่มเริ่มตรวจสอบ และรอ AI วิเคราะห์ตามมาตรฐาน 14 หัวข้อ
    5. **ดาวน์โหลด:** นำผลการประเมินไปปรับแก้รายงานในรูปแบบไฟล์ Word
    """)

st.divider()

# Sidebar
with st.sidebar:
    st.image("https://via.placeholder.com/100?text=ODPC8", width=100) # เปลี่ยนเป็น URL โลโก้จริงได้ครับ
    st.header("⚙️ ตั้งค่าระบบ")
    api_key_input = st.text_input("🔑 Gemini API Key", type="password")
    st.markdown("---")
    st.info("พัฒนาโดย: กลุ่มระบาดวิทยา สคร.8 อุดรธานี")

# Main Interface
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📥 ข้อมูลนำเข้า")
    report_type = st.radio(
        "ประเภทการสอบสวน:",
        ["สอบสวนการระบาด (Outbreak)", "สอบสวนเฉพาะราย (Single Case)"]
    )
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
