import streamlit as st
import pandas as pd
import numpy as np
import statsmodels.api as sm
import statsmodels.formula.api as smf
from datetime import timedelta
import scipy.stats as stats
from scipy.stats import hypergeom
from streamlit_gsheets import GSheetsConnection
import plotly.express as px
import folium
from streamlit_folium import folium_static
import requests
import math
import re
import google.generativeai as genai # เพิ่มการนำเข้า AI

# ==========================================
# 1. CONFIGURATION & STYLING (MODERN SARABUN)
# ==========================================
st.set_page_config(
    page_title="Epi-Analytic Pro ODPC8", 
    page_icon="🦠", 
    layout="wide"
)

st.markdown(
    """
    <link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        html, body, [class*="css"], [class*="st-"], div, span, label, p, h1, h2, h3, th, td {
            font-family: 'Sarabun', sans-serif !important;
        }
        p, span, label, div, th, td { font-size: 1.15rem !important; }
        h1 { font-size: 2.6rem !important; color: #D81B60 !important; font-weight: 700 !important; }
        h2 { font-size: 2.0rem !important; color: #D81B60 !important; font-weight: 600 !important; }
        h3 { font-size: 1.6rem !important; color: #880E4F !important; font-weight: 600 !important; }

        [data-testid="stMetricValue"] { font-size: 2.6rem !important; color: #E91E63 !important; font-weight: 700 !important; }
        
        [data-testid="stSidebar"] {
            background-color: #FFFFFF !important; 
            box-shadow: 2px 0 15px rgba(0,0,0,0.04);
            border: none !important;
        }
        
        .stButton > button {
            background: linear-gradient(135deg, #E91E63 0%, #C2185B 100%) !important;
            color: #FFFFFF !important;
            border-radius: 12px !important;
            border: none !important;
            width: 100%;
            font-weight: 600 !important;
            transition: all 0.3s ease;
        }
        .stButton > button:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(233, 30, 99, 0.4); }

        .ai-box {
            background-color: #F3E5F5;
            padding: 20px;
            border-radius: 12px;
            border-left: 5px solid #9C27B0;
            margin-top: 15px;
        }
    </style>
    """,
    unsafe_allow_html=True
)

# ==========================================
# 2. SESSION STATE & AI HELPER
# ==========================================
if 'registered' not in st.session_state:
    st.session_state['registered'] = False

def generate_ai_summary(api_key, context_text, menu_name):
    if not api_key:
        return "⚠️ กรุณาระบุ Google Gemini API Key ในแถบเมนูด้านซ้ายก่อนครับ"
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        คุณคือนักระบาดวิทยาผู้เชี่ยวชาญ กรุณาสรุปผลการวิเคราะห์ข้อมูลจากเมนู '{menu_name}' 
        โดยเขียนเป็นภาษาทางการที่ใช้ในรายงานการสอบสวนโรค (สั้น กระชับ ตรงประเด็น) และให้ข้อเสนอแนะ 1-2 ข้อ
        
        ข้อมูลที่วิเคราะห์ได้:
        {context_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"❌ เกิดข้อผิดพลาดในการเชื่อมต่อ AI: {e}"

# Config สำหรับปุ่ม Export กราฟความละเอียดสูง
chart_config = {
    'displaylogo': False,
    'toImageButtonOptions': {'format': 'png', 'filename': 'Epi_Chart_Export', 'height': 720, 'width': 1280, 'scale': 2}
}

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
@st.cache_data
def load_data(file):
    try:
        if file.name.endswith('.csv'): return pd.read_csv(file)
        else: return pd.read_excel(file)
    except Exception as e:
        st.error(f"ไม่สามารถโหลดไฟล์ได้: {e}")
        return None

def smart_map_variable(series):
    unique_vals = set(series.dropna().unique())
    if unique_vals.issubset({1, 2, 1.0, 2.0, '1', '2'}):
        return pd.to_numeric(series, errors='coerce').map({1: 1, 2: 0, 1.0: 1, 2.0: 0})
    return series

def calculate_mid_p(a, b, c, d):
    n = a + b + c + d
    if n == 0: return 1.0
    k, m = a + c, a + b
    p_obs = hypergeom.pmf(a, n, k, m)
    p_lower = hypergeom.cdf(a, n, k, m)
    p_upper = hypergeom.sf(a-1, n, k, m)
    mid_p = 2 * (min(p_lower, p_upper) - 0.5 * p_obs)
    return max(min(mid_p, 1.0), 0.0)

# ==========================================
# 4. SIDEBAR NAVIGATION
# ==========================================
try: st.sidebar.image("odpc8_logo.png", use_container_width=True)
except: st.sidebar.title("🏥 ODPC8 Udon Thani")

st.sidebar.markdown("---")

if not st.session_state['registered']:
    menu = "📝 ลงทะเบียนใช้งาน"
    st.sidebar.warning("⚠️ โปรดลงทะเบียนเพื่อปลดล็อกเมนูวิเคราะห์")
else:
    # เพิ่มช่องใส่ API Key สำหรับ AI
    st.sidebar.subheader("🧠 ผู้ช่วย AI (EpiScholar)")
    api_key_input = st.sidebar.text_input("ใส่ Gemini API Key ที่นี่", type="password", help="รับฟรีที่ Google AI Studio")
    st.sidebar.markdown("---")

    menu = st.sidebar.radio(
        "เลือกหัวข้อการวิเคราะห์", 
        ["👥 ประชากรและอัตราป่วย (Attack Rate)",
         "👤 พรรณนา (Descriptive)", 
         "📊 สร้าง Epi Curve (Time)", 
         "🗺️ Spot Map (Place)",
         "🔬 Bivariate Analysis (OR/RR)", 
         "🧬 Multiple Logistic Regression (AOR)",
         "📝 ข้อมูลการลงทะเบียน (แก้ไข)"],
        key="main_menu_radio" 
    )

# ==========================================
# 5. DATA SOURCE
# ==========================================
df = None
if st.session_state['registered']:
    st.sidebar.divider()
    source_choice = st.sidebar.radio("เลือกแหล่งข้อมูล:", ["อัปโหลดไฟล์ (Excel/CSV)", "Google Sheets"], key="data_source_radio")
    
    if source_choice == "อัปโหลดไฟล์ (Excel/CSV)":
        uploaded_file = st.sidebar.file_uploader("📂 เลือกไฟล์ข้อมูล", type=['xlsx', 'csv'])
        if uploaded_file: df = load_data(uploaded_file)
    else:
        sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets:")
        if sheet_url:
            try:
                if "docs.google.com/spreadsheets" in sheet_url:
                    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
                    if match:
                        sheet_id = match.group(1)
                        df = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv")
                    else:
                        conn = st.connection("gsheets", type=GSheetsConnection)
                        df = conn.read(spreadsheet=sheet_url)
                else:
                    conn = st.connection("gsheets", type=GSheetsConnection)
                    df = conn.read(spreadsheet=sheet_url)
                if st.sidebar.button("🔄 อัปเดตข้อมูล"):
                    st.cache_data.clear(); st.rerun()
            except Exception as e:
                st.error(f"เชื่อมต่อล้มเหลว: {e}")

# ==========================================
# 6. MAIN CONTENT
# ==========================================

if menu == "📝 ลงทะเบียนใช้งาน" or menu == "📝 ข้อมูลการลงทะเบียน (แก้ไข)":
    st.title("📝 ลงทะเบียนเข้าใช้งานระบบ")
    with st.form("registration"):
        u_agency = st.text_input("หน่วยงานต้นสังกัด (เช่น สสจ.อุดรธานี)")
        u_purpose = st.selectbox("วัตถุประสงค์", ["สอบสวนโรคภาคสนาม", "วิเคราะห์สถิติวิชาการ", "ซ้อมแผนฯ"])
        if st.form_submit_button("เริ่มใช้งาน"):
            if u_agency:
                st.session_state['registered'] = True
                st.success("ลงทะเบียนสำเร็จ!")
                st.rerun()
            else: st.error("กรุณาระบุหน่วยงาน")

elif df is not None:
    total_n = len(df)

    # ------------------------------------------
    # 6.1 Attack Rate
    # ------------------------------------------
    if menu == "👥 ประชากรและอัตราป่วย (Attack Rate)":
        st.title("👥 ประชากรและอัตราป่วย (Attack Rate)")
        sex_c = find_col(df, ['sex', 'gender', 'เพศ'])
        age_c = find_col(df, ['age', 'อายุ'])
        
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            pop_male = st.number_input("ประชากรชายทั้งหมด", min_value=1, value=100)
            pop_female = st.number_input("ประชากรหญิงทั้งหมด", min_value=1, value=100)
        with col_p2:
            age_labels = ['0-4','5-14','15-24','25-34','35-44','45-54','55-64','65+']
            pop_age = {lbl: st.number_input(f"กลุ่ม {lbl}", min_value=0, value=0) for lbl in age_labels}

        if st.button("📈 คำนวณ"):
            total_pop = pop_male + pop_female
            ar = (total_n / total_pop * 100) if total_pop > 0 else 0
            st.metric("Overall Attack Rate", f"{ar:.2f} %")
            
            c_res1, c_res2 = st.columns(2)
            ar_sex = pd.DataFrame()
            ar_age_df = pd.DataFrame()

            with c_res1:
                if sex_c:
                    df['sex_temp'] = df[sex_c].astype(str).str.strip().replace({'1':'ชาย','2':'หญิง','1.0':'ชาย','2.0':'หญิง'})
                    m_case = len(df[df['sex_temp'] == 'ชาย'])
                    f_case = len(df[df['sex_temp'] == 'หญิง'])
                    ar_sex = pd.DataFrame({"เพศ": ["ชาย", "หญิง"], "ป่วย": [m_case, f_case], "ประชากร": [pop_male, pop_female], "AR (%)": [m_case/pop_male*100, f_case/pop_female*100]})
                    st.table(ar_sex.style.format({"AR (%)": "{:.2f}"}))
            with c_res2:
                if age_c:
                    df['age_tmp'] = pd.cut(pd.to_numeric(df[age_c], errors='coerce'), bins=[0,5,15,25,35,45,55,65,120], labels=age_labels, right=False)
                    a_cases = df['age_tmp'].value_counts().reindex(age_labels, fill_value=0)
                    ar_age_df = pd.DataFrame([{"อายุ": l, "ป่วย": a_cases[l], "ประชากร": pop_age[l], "AR (%)": (a_cases[l]/pop_age[l]*100) if pop_age[l]>0 else 0} for l in age_labels])
                    st.table(ar_age_df.style.format({"AR (%)": "{:.2f}"}))

            # AI Summary
            if st.button("✨ ให้ AI ช่วยสรุปผล", key="ai_ar"):
                with st.spinner("กำลังวิเคราะห์..."):
                    context = f"ภาพรวมผู้ป่วย: {total_n} คน, อัตราป่วยรวม: {ar:.2f}%\nอัตราป่วยแยกเพศ:\n{ar_sex.to_string()}\nอัตราป่วยแยกอายุ:\n{ar_age_df.to_string()}"
                    summary = generate_ai_summary(api_key_input, context, "อัตราป่วย (Attack Rate)")
                    st.markdown(f"<div class='ai-box'><b>🤖 สรุปผลจาก AI:</b><br>{summary}</div>", unsafe_allow_html=True)

    # ------------------------------------------
    # 6.2 Descriptive Analysis
    # ------------------------------------------
    elif menu == "👤 พรรณนา (Descriptive)":
        st.title("👤 ระบาดวิทยาเชิงพรรณนา")
        st.info(f"📋 จำนวนผู้ป่วยทั้งหมด (n) = {total_n} ราย")
        
        c1, c2 = st.columns(2)
        with c1:
            sex_col = st.selectbox("ตัวแปรเพศ", df.columns)
            res_sex = df[sex_col].value_counts().reset_index()
            res_sex.columns = ['เพศ', 'n']; res_sex['%'] = (res_sex['n']/total_n*100)
            st.table(res_sex.style.format({'%': '{:.2f}'}))
        with c2:
            age_col = st.selectbox("ตัวแปรอายุ", df.columns)
            df['age_grp'] = pd.cut(pd.to_numeric(df[age_col], errors='coerce'), bins=[0,5,15,25,35,45,55,65,120], labels=['0-4','5-14','15-24','25-34','35-44','45-54','55-64','65+'])
            res_age = df['age_grp'].value_counts().sort_index().reset_index()
            res_age.columns = ['อายุ', 'n']; res_age['%'] = (res_age['n']/total_n*100)
            st.table(res_age.style.format({'%': '{:.2f}'}))

        symp_cols = st.multiselect("เลือกตัวแปรอาการ (1=มีอาการ)", df.columns)
        if symp_cols:
            s_df = pd.DataFrame([{"อาการ": c, "%": (df[c]==1).sum()/total_n*100} for c in symp_cols]).sort_values("%", ascending=True)
            fig_s = px.bar(s_df, x="%", y="อาการ", orientation='h', text_auto='.1f', color_discrete_sequence=['#E91E63'])
            fig_s.update_layout(font=dict(family="Sarabun", size=16, color="#4A4A4A"))
            
            # ปุ่มกล้อง (Export) ทำงานด้วย Config
            st.plotly_chart(fig_s, use_container_width=True, config=chart_config)

            # AI Summary
            if st.button("✨ ให้ AI ช่วยสรุปผล", key="ai_desc"):
                with st.spinner("กำลังวิเคราะห์..."):
                    context = f"การกระจายอาการ (เรียงจากน้อยไปมาก):\n{s_df.to_string()}\nข้อมูลเพศ:\n{res_sex.to_string()}"
                    summary = generate_ai_summary(api_key_input, context, "ระบาดวิทยาเชิงพรรณนา")
                    st.markdown(f"<div class='ai-box'><b>🤖 สรุปผลจาก AI:</b><br>{summary}</div>", unsafe_allow_html=True)

    # ------------------------------------------
    # 6.3 Epidemic Curve
    # ------------------------------------------
    elif menu == "📊 สร้าง Epi Curve (Time)":
        st.title("📊 Interactive Epidemic Curve")
        date_col = st.sidebar.selectbox("คอลัมน์วันเริ่มป่วย", df.columns)
        col_grp = st.sidebar.selectbox("ตัวแปรแยกกลุ่มสี:", ["<none>"] + list(df.columns))
        
        # ฟีเจอร์ใหม่: เลือกสีกราฟเอง
        custom_color = st.sidebar.color_picker("🎨 เลือกสีกราฟหลัก", "#E91E63")

        unit_map = {"Hour": "h", "Day": "d", "Week": "W", "Month": "ME", "30 Min": "30min"}
        bin_unit = st.sidebar.selectbox("หน่วยเวลา", list(unit_map.keys()), index=0)
        bin_size = st.sidebar.number_input("ขนาด Bin", min_value=1, value=1)
        freq = f"{bin_size}{unit_map[bin_unit]}"

        pad_before = st.sidebar.number_input(f"เพิ่มช่วงว่างก่อนหน้า ({bin_unit})", value=1)
        pad_after = st.sidebar.number_input(f"เพิ่มช่วงว่างข้างหลัง ({bin_unit})", value=1)

        df[date_col] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')
        df_clean = df.dropna(subset=[date_col]).copy()

        if not df_clean.empty:
            min_dt, max_dt = df_clean[date_col].min(), df_clean[date_col].max()
            
            if "h" in freq or "min" in freq:
                start_range = (min_dt - pd.Timedelta(hours=pad_before)).floor('h')
                end_range = (max_dt + pd.Timedelta(hours=pad_after)).ceil('h')
            else:
                start_range = (min_dt - pd.to_timedelta(pad_before, unit='d')).floor('d')
                end_range = (max_dt + pd.to_timedelta(pad_after, unit='d')).ceil('d')
            
            full_range = pd.date_range(start=start_range, end=end_range, freq=freq)

            if col_grp == "<none>":
                counts = df_clean.groupby(pd.Grouper(key=date_col, freq=freq)).size()
                chart_df = counts.reindex(full_range, fill_value=0).reset_index()
                chart_df.columns = [date_col, 'Cases']
                fig = px.bar(chart_df, x=date_col, y='Cases', text_auto=True, color_discrete_sequence=[custom_color])
            else:
                counts = df_clean.groupby([pd.Grouper(key=date_col, freq=freq), col_grp]).size().unstack(fill_value=0)
                chart_df = counts.reindex(full_range, fill_value=0).stack().reset_index(name='Cases')
                chart_df.columns = [date_col, col_grp, 'Cases']
                fig = px.bar(chart_df, x=date_col, y='Cases', color=col_grp, color_discrete_sequence=px.colors.sequential.RdPu[::-1])

            fig.update_layout(
                font=dict(family="Sarabun", size=16, color="#4A4A4A"),
                bargap=0.01, 
                xaxis=dict(type='date', tickformat='%d/%m %H:%M'),
                xaxis_title="Onset Date/Time",
                yaxis_title="Number of Cases",
                hovermode="x unified"
            )
            fig.update_traces(marker_line_width=0.5, marker_line_color='white')
            
            # Export รูปภาพผ่าน Config ของ Plotly
            st.plotly_chart(fig, use_container_width=True, config=chart_config)
            st.caption("💡 ท่านสามารถคลิกรูปไอคอน 'กล้องถ่ายรูป' มุมขวาบนของกราฟ เพื่อดาวน์โหลดเป็นรูปภาพความละเอียดสูงได้")

            # AI Summary
            if st.button("✨ ให้ AI ช่วยสรุปผล", key="ai_curve"):
                with st.spinner("กำลังวิเคราะห์..."):
                    context = f"ข้อมูลจำนวนเคสตามเวลา:\n{chart_df.to_string()}"
                    summary = generate_ai_summary(api_key_input, context, "Epidemic Curve")
                    st.markdown(f"<div class='ai-box'><b>🤖 สรุปผลจาก AI:</b><br>{summary}</div>", unsafe_allow_html=True)
        else:
            st.error("❌ ไม่สามารถวิเคราะห์ได้ เนื่องจากรูปแบบวันที่ในไฟล์ไม่ถูกต้อง")

    # ------------------------------------------
    # 6.4 Spot Map
    # ------------------------------------------
    elif menu == "🗺️ Spot Map (Place)":
        st.title("🗺️ Spot Map - GIS Analytics")
        lat_c = next((c for c in df.columns if any(p in c.lower() for p in ['lat', 'latitude', 'ละติจูด'])), None)
        lon_c = next((c for c in df.columns if any(p in c.lower() for p in ['lon', 'longitude', 'ลองจิจูด'])), None)
        
        if lat_c and lon_c:
            df_m = df.dropna(subset=[lat_c, lon_c]).copy()

            st.sidebar.markdown("---")
            st.sidebar.subheader("⚙️ ตั้งค่าแผนที่")
            buffer_radius = st.sidebar.number_input("รัศมีควบคุมโรค (เมตร)", min_value=0, value=100, step=50)
            map_type = st.sidebar.radio("รูปแบบแผนที่", ["ดาวเทียม (Google Hybrid)", "แผนที่ถนน (OpenStreetMap)"])

            if map_type == "ดาวเทียม (Google Hybrid)":
                tiles_url = 'https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}'
                attr = 'Google'
            else:
                tiles_url = 'OpenStreetMap'
                attr = 'OpenStreetMap'

            m = folium.Map(location=[df_m[lat_c].mean(), df_m[lon_c].mean()], zoom_start=16, tiles=tiles_url, attr=attr)

            for idx, r in df_m.iterrows():
                if buffer_radius > 0:
                    folium.Circle(location=[r[lat_c], r[lon_c]], radius=buffer_radius, color='#FFEB3B', weight=2, fill=True, fill_opacity=0.25, fill_color='#FF9800').add_to(m)
                folium.CircleMarker(location=[r[lat_c], r[lon_c]], radius=6, color='#E91E63', fill=True, fill_opacity=1.0, popup=f"เคสที่ {idx+1}").add_to(m)

            folium_static(m, width=1000, height=650)
            st.caption("💡 แนะนำให้ใช้ฟังก์ชัน Screen Capture ของคอมพิวเตอร์ เพื่อบันทึกภาพแผนที่")
        else: 
            st.warning("⚠️ ไม่พบคอลัมน์พิกัด (Lat/Lon) ในไฟล์")

    # ------------------------------------------
    # 6.5 Bivariate Analysis
    # ------------------------------------------
    elif menu == "🔬 Bivariate Analysis (OR/RR)":
        st.title("🔬 Bivariate Analysis")
        out_v = st.selectbox("Outcome", df.columns)
        exp_list = st.multiselect("Exposures", [c for c in df.columns if c != out_v])
        
        if st.button("🚀 ประมวลผล"):
            results = []
            for e in exp_list:
                temp = df[[out_v, e]].copy().dropna()
                temp[out_v], temp[e] = smart_map_variable(temp[out_v]), smart_map_variable(temp[e])
                a = len(temp[(temp[e]==1) & (temp[out_v]==1)])
                b = len(temp[(temp[e]==1) & (temp[out_v]==0)])
                c = len(temp[(temp[e]==0) & (temp[out_v]==1)])
                d = len(temp[(temp[e]==0) & (temp[out_v]==0)])
                or_val = (a*d)/(b*c) if (b*c)>0 else 0
                results.append({"ปัจจัยเสี่ยง": e, "Odds Ratio": or_val, "Mid-P": calculate_mid_p(a,b,c,d)})
            
            res_df = pd.DataFrame(results)
            st.table(res_df.style.format({"Odds Ratio": "{:.2f}", "Mid-P": "{:.4f}"}))
            
            # ส่งข้อมูลที่เพิ่งประมวลผลเข้า Session State ชั่วคราวเพื่อให้ปุ่ม AI อ่านได้
            st.session_state['bi_res'] = res_df

        # AI Summary (อ่านจาก Session State ป้องกันปุ่มหาย)
        if 'bi_res' in st.session_state:
            if st.button("✨ ให้ AI ช่วยสรุปผล", key="ai_bi"):
                with st.spinner("กำลังวิเคราะห์..."):
                    context = st.session_state['bi_res'].to_string()
                    summary = generate_ai_summary(api_key_input, context, "Bivariate Analysis (OR)")
                    st.markdown(f"<div class='ai-box'><b>🤖 สรุปผลจาก AI:</b><br>{summary}</div>", unsafe_allow_html=True)

    # ------------------------------------------
    # 6.6 Logistic Regression
    # ------------------------------------------
    elif menu == "🧬 Multiple Logistic Regression (AOR)":
        st.title("🧬 Multiple Logistic Regression")
        out_v = st.selectbox("Outcome", df.columns, key="mlr_out")
        exp_v = st.selectbox("ปัจจัยหลัก", [c for c in df.columns if c != out_v])
        adj_v = st.multiselect("ตัวแปรกวน", [c for c in df.columns if c not in [out_v, exp_v]])
        
        if st.button("🚀 คำนวณ AOR"):
            try:
                df_m = df[[out_v, exp_v] + adj_v].copy().dropna()
                for c in df_m.columns: df_m[c] = smart_map_variable(df_m[c])
                
                formula = f"Q('{out_v}') ~ Q('{exp_v}')" + (" + " + " + ".join([f"Q('{a}')" for a in adj_v]) if adj_v else "")
                model = smf.logit(formula, data=df_m).fit(disp=0)
                
                conf_int = model.conf_int()
                res_df = pd.DataFrame({
                    "Factors": model.params.index,
                    "Adjusted OR (AOR)": np.exp(model.params.values),
                    "95% CI Lower": np.exp(conf_int[0].values),
                    "95% CI Upper": np.exp(conf_int[1].values),
                    "P-value": model.pvalues.values
                })

                res_df = res_df[res_df['Factors'] != 'Intercept']
                res_df['Factors'] = res_df['Factors'].str.extract(r"Q\('(.*)'\)")[0].fillna(res_df['Factors'])

                st.subheader("📋 สรุปผลการวิเคราะห์ปัจจัยเสี่ยง")
                st.dataframe(res_df.style.format({
                    "Adjusted OR (AOR)": "{:.2f}",
                    "95% CI Lower": "{:.2f}",
                    "95% CI Upper": "{:.2f}",
                    "P-value": "{:.4f}"
                }).apply(lambda x: ['background-color: #F8BBD0' if x['P-value'] < 0.05 else '' for _ in x], axis=1), 
                use_container_width=True)
                
                st.session_state['mlr_res'] = res_df
                st.success("✅ คำนวณค่า Adjusted OR และ 95% CI สำเร็จ")

            except Exception as e: st.error(f"⚠️ ไม่สามารถประมวลผลได้: {e}")

        if 'mlr_res' in st.session_state:
            if st.button("✨ ให้ AI ช่วยสรุปผล", key="ai_mlr"):
                with st.spinner("กำลังวิเคราะห์..."):
                    context = st.session_state['mlr_res'].to_string()
                    summary = generate_ai_summary(api_key_input, context, "Multiple Logistic Regression (AOR)")
                    st.markdown(f"<div class='ai-box'><b>🤖 สรุปผลจาก AI:</b><br>{summary}</div>", unsafe_allow_html=True)

# --- Footer ---
st.markdown("---")
st.markdown("<div style='text-align: center; color: #880E4F;'>Epi-Analytic Pro ODPC8 | พัฒนาโดย กลุ่มระบาดวิทยา</div>", unsafe_allow_html=True)
