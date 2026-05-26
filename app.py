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

ส่วนที่ 3: ประเมิน 14 องค์ประกอบของรายงาน
ห้ามใช้ markdown table
ให้เขียนแยกหัวข้อเรียงลำดับ 1-14 เท่านั้น
แต่ละหัวข้อให้ใช้รูปแบบนี้:

1. ชื่อเรื่อง
คะแนน: 0-3
สิ่งที่พบ: เขียนสั้น กระชับ
ข้อเสนอแนะ: เขียนเป็นข้อเสนอแนะที่แก้ไขได้จริง ไม่เกิน 3 ข้อ

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
- ถ้าข้อมูลในรายงานไม่พบ ให้ระบุว่า "ไม่พบข้อมูลในรายงาน"
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

user_prompt = f"""
ประเภทที่ผู้ใช้เลือก: {report_type}

โปรดประเมินรายงานสอบสวนโรคต่อไปนี้ตามเกณฑ์ใน System Instruction

ข้อกำหนดการตอบ:
- ห้ามใช้ markdown table
- ให้ตอบเป็นหัวข้อเรียงลำดับ
- แต่ละหัวข้อให้กระชับ
- ข้อเสนอแนะต้องนำไปแก้ไขรายงานได้จริง
- หากข้อมูลไม่พบ ให้ระบุว่า "ไม่พบข้อมูลในรายงาน"

เนื้อหารายงาน:
{text}
"""
response = model.generate_content(user_prompt)

def create_word_doc(feedback_text):
    doc = Document()
    doc.add_heading('ผลการประเมินรายงานสอบสวนโรค (EpiScholar)', 0)

    for line in feedback_text.split('\n'):
        line = line.strip()

        if not line:
            continue

        # แปลงหัวข้อ markdown เป็น heading
        if line.startswith("### "):
            doc.add_heading(line.replace("### ", ""), level=2)
        elif line.startswith("## "):
            doc.add_heading(line.replace("## ", ""), level=1)
        elif line.startswith("# "):
            doc.add_heading(line.replace("# ", ""), level=1)

        # bullet
        elif line.startswith("- "):
            doc.add_paragraph(line.replace("- ", ""), style="List Bullet")
        elif line.startswith("* "):
            doc.add_paragraph(line.replace("* ", ""), style="List Bullet")

        # numbered list แบบง่าย
        elif len(line) > 2 and line[0].isdigit() and line[1:3] in [". ", ") "]:
            doc.add_paragraph(line, style="List Number")

        else:
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
