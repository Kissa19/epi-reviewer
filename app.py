import streamlit as st
import PyPDF2
import google.generativeai as genai

# ==========================================
# 1. ตั้งค่า System Prompt (กฎเกณฑ์ของ AI)
# ==========================================
SYSTEM_INSTRUCTION = """
บทบาท (Role):
คุณคือผู้เชี่ยวชาญด้านระบาดวิทยา และผู้ประเมินรายงานสอบสวนโรคระดับชาติ หน้าที่ของคุณคือการอ่าน "รายงานสอบสวนโรคฉบับสมบูรณ์ (Full Report)" และให้ข้อเสนอแนะเชิงวิจารณ์ (Constructive Feedback)

กฎเหล็กด้านความปลอดภัยของข้อมูล (CRITICAL RULE):
ห้ามมีข้อมูลส่วนบุคคล (PII): หากรายงานมีการระบุ ชื่อ, นามสกุล, เลขประจำตัวผู้ป่วย (HN), หรือ เลขบัตรประชาชน 13 หลัก ให้แจ้งเตือนเป็นข้อผิดพลาดร้ายแรง (Fatal Error) ทันที และแนะนำให้ผู้เขียนทำข้อมูลให้เป็นนิรนาม (Anonymization)

คำสั่ง (Task):
จงวิเคราะห์ข้อความรายงานสอบสวนโรคอย่างละเอียด โดยแบ่งการทำงานเป็น 2 ขั้นตอนหลัก:

ขั้นตอนที่ 1: ตรวจสอบความครบถ้วนของโครงสร้างรายงาน 14 หัวข้อหลัก
เช็คว่ามี: 1. ชื่อเรื่อง 2. ผู้รายงานและทีม 3. บทคัดย่อ 4. ความเป็นมา 5. วัตถุประสงค์ 6. วิธีการสอบสวน 7. ผลการสอบสวน 8. มาตรการควบคุม 9. วิจารณ์ผล 10. ปัญหา/ข้อจำกัด 11. ข้อเสนอแนะ 12. สรุปผล 13. กิตติกรรมประกาศ 14. เอกสารอ้างอิง

ขั้นตอนที่ 2: ประเมินคุณภาพและให้ข้อเสนอแนะรายหัวข้อ
* วัตถุประสงค์: ตรวจสอบว่าสอดคล้องกับประเภทการสอบสวนหรือไม่
* วิธีการสอบสวน: เช็คนิยามผู้ป่วย (Person, Place, Time, Clinical criteria) 
* เชิงวิเคราะห์ (Optional): หากมีให้เช็คว่าระบุรูปแบบการศึกษาชัดเจนหรือไม่ (เช่น Cohort, Case-Control)
* ผลการสอบสวน: เช็ค Epidemic Curve (Time interval 1/3-1/8 ของระยะฟักตัว), ตาราง Bivariate/Multiple Logistic Regression, การสำรวจสิ่งแวดล้อม (ค่า อ.31, SI-2) และผล Lab
* วิจารณ์ผล: ต้องไม่อธิบายตัวเลขซ้ำกับผลการสอบสวน

รูปแบบผลลัพธ์ (Output Format): ให้แสดงผลเป็น Markdown แบ่งเป็น
1. คำแนะนำเบื้องต้น (แจ้งเตือน PII ถ้ามี)
2. 📋 ส่วนที่ 1: การตรวจสอบความครบถ้วน 14 หัวข้อหลัก (ใช้ ✅ หรือ ❌)
3. 📝 ส่วนที่ 2: ความคิดเห็นและข้อเสนอแนะรายหัวข้อ (ชื่นชมส่วนที่ดี และระบุข้อบกพร่อง)
4. 💡 ส่วนที่ 3: ตัวอย่างการปรับแก้
"""

# ==========================================
# 2. ฟังก์ชันสกัดข้อความ และส่งเข้า AI
# ==========================================
def extract_text_from_pdf(pdf_file):
    """สกัดข้อความจากไฟล์ PDF"""
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        if page.extract_text():
            text += page.extract_text() + "\n"
    return text

def analyze_report(api_key, text, report_type):
    """ส่งข้อมูลให้ Gemini วิเคราะห์"""
    genai.configure(api_key=api_key)
    
    # เพิ่มบริบทเรื่องประเภทรายงานที่ผู้ใช้เลือกบนหน้าเว็บ
    dynamic_prompt = SYSTEM_INSTRUCTION + f"\n\n**ข้อมูลเพิ่มเติมจากระบบ:** รายงานฉบับนี้เป็นการ {report_type}"
    
    # แนะนำให้ใช้รุ่น 1.5 Pro เนื่องจากอ่านเอกสารภาษาไทยและจับบริบทได้แม่นยำที่สุด
    model = genai.GenerativeModel(
        model_name="gemini-pro",
        system_instruction=dynamic_prompt
    )
    
    prompt = f"โปรดประเมินรายงานสอบสวนโรคต่อไปนี้:\n\n{text}"
    response = model.generate_content(prompt)
    return response.text

# ==========================================
# 3. ส่วนหน้าตาแอปพลิเคชัน (UI)
# ==========================================
st.set_page_config(page_title="Epi-Reviewer | ระบบประเมินรายงาน", page_icon="📋", layout="wide")

st.title("📋 Epi-Reviewer: ผู้ช่วยตรวจประเมินรายงานสอบสวนโรค")
st.markdown("**โมดูลยกระดับงานวิชาการ (ส่วนหนึ่งของระบบ Epi-Analytic Pro)**")

# แถบด้านข้างสำหรับใส่ API Key
with st.sidebar:
    st.header("⚙️ ตั้งค่าระบบ")
    api_key_input = st.text_input("🔑 โปรดระบุ Gemini API Key ของคุณ", type="password", help="รับฟรีได้ที่ Google AI Studio")
    st.markdown("---")
    st.markdown("ระบบนี้ออกแบบตามคู่มือของ **กรมควบคุมโรค** เน้นการประเมิน 14 หัวข้อหลัก และหลักระบาดวิทยาเชิงลึก")

# พื้นที่หลัก แบ่งเป็น 2 คอลัมน์
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. นำเข้าข้อมูลรายงาน")
    
    # ปุ่มเลือกประเภทการสอบสวน
    report_type = st.radio(
        "ประเภทการสอบสวนในรายงานฉบับนี้:",
        ["สอบสวนการระบาด (Outbreak)", "สอบสวนเฉพาะราย (Single Case)"],
        index=0
    )
    
    st.markdown("---")
    uploaded_file = st.file_uploader("2. อัปโหลดไฟล์รายงาน (PDF)", type=["pdf"])

with col2:
    st.subheader("3. ผลการประเมินจาก AI")
    
    if st.button("🚀 เริ่มตรวจสอบรายงาน", type="primary", use_container_width=True):
        if not api_key_input:
            st.warning("⚠️ กรุณาระบุ API Key ในแถบด้านข้างก่อนครับ")
        elif not uploaded_file:
            st.warning("⚠️ กรุณาอัปโหลดไฟล์รายงานฉบับสมบูรณ์ (PDF)")
        else:
            with st.spinner("⏳ ระบบกำลังอ่านเอกสารและวิเคราะห์โครงสร้าง 14 หัวข้อ... อาจใช้เวลาสักครู่"):
                try:
                    # 1. สกัดข้อความ
                    raw_text = extract_text_from_pdf(uploaded_file)
                    
                    # 2. วิเคราะห์
                    feedback = analyze_report(api_key_input, raw_text, report_type)
                    
                    # 3. แสดงผล
                    st.success("✅ วิเคราะห์เสร็จสมบูรณ์!")
                    
                    # ตกแต่งกล่องแสดงผล
                    with st.container(border=True):
                        st.markdown(feedback)
                        
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาดในการวิเคราะห์: {e}")
