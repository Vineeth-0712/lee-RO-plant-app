# =================== LeeWave – RO Plant Calculator Pro (Professional Dashboard) ===================
import streamlit as st
import pandas as pd
import sqlite3
from io import BytesIO
from datetime import datetime
from pathlib import Path
import os
import math

# ---------- Brand ----------
BRAND = "LeeWave"
PRIMARY_HEX = "#1f6feb"

st.set_page_config(page_title=f"{BRAND} – RO Pro", layout="wide")
st.markdown(
    f"""
    <style>
      .lw-title {{ text-align:center; color:{PRIMARY_HEX}; font-weight:800; font-size:28px; margin:4px 0 4px; }}
      .lw-sub   {{ text-align:center; color:#4b5563; font-size:13px; margin-bottom:16px; }}
      .stButton>button {{ border-radius:10px; padding:0.5rem 1rem; }}
      .card {{
          background:#ffffff; border:1px solid #e5e7eb; border-radius:14px; padding:14px; margin-bottom:12px;
          box-shadow: 0 1px 2px rgba(0,0,0,0.04);
      }}
      .section-title {{ font-weight:700; color:#111827; margin: 2px 0 8px; font-size:16px; }}
      div[data-testid="stMetricValue"] {{ font-size:1.15rem !important; }}
      .good  {{ border-left:6px solid #10b981; }}
      .ok    {{ border-left:6px solid #60a5fa; }}
      .bad   {{ border-left:6px solid #ef4444; }}
      .muted {{ color:#6b7280; font-size:12px; }}
      .note  {{ font-size:13px; color:#374151; line-height:1.35; }}
      footer {{ visibility:hidden; }}
    </style>
    """,
    unsafe_allow_html=True
)
st.markdown(f"<div class='lw-title'>{BRAND} – RO Plant Calculator Pro</div>", unsafe_allow_html=True)
st.markdown("<div class='lw-sub'>Admin/User • Login • Per-Vessel • Pro KPIs • Max Output • One-Sheet Excel • PDF • History • Capacity Requests</div>", unsafe_allow_html=True)

# ---------- Paths ----------
APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = str(APP_DIR / "ro.db")

# ---------- Admin creds (env override in production) ----------
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@ro.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin123")
SHOW_ADMIN_HINT = os.environ.get("SHOW_ADMIN_HINT", "0") == "1"

# ---------- Basic i18n ----------
LANGS = {"en":"English","ar":"العربية","ml":"മലയാളം","hi":"हिन्दी"}
T = {
    "en": {
        "login":"Login","register":"Register","forgot":"Forgot Password",
        "email":"Email","password":"Password","confirm":"Confirm Password",
        "create_acc":"Create account","reset":"Reset",
        "app":"App","history":"History","admin":"Admin","help":"Help",
        "plant_calc":"RO Plant Performance Calculator",
        "plant_name":"Plant Name","site_name":"Site Name","capacity":"Capacity (m³/day)","temp":"Temperature (°C)",
        "feed_tds":"Feed TDS (ppm)","perm_tds":"Product (Permeate) TDS (ppm)",
        "feed_flow":"Feed Flow (LPM)","perm_flow":"Product Flow (LPM)","rej_flow":"Reject Flow (LPM) [optional]",
        "hp":"HP Pump Discharge (bar)","brine":"Brine / Reject Pressure (bar)","perm_bp":"Permeate Backpressure (bar)",
        "stage_type":"Stage Type","single":"Single-stage","two":"Two-stage (series)","three":"Three-stage (series)",
        "s1":"Stage-1","s2":"Stage-2","s3":"Stage-3",
        "s_recovery":"Stage-{} Recovery (%)","s_perm_tds":"Stage-{} Permeate TDS (ppm)",
        "vessel_hdr":"{} — Per-Vessel Outlet TDS (ppm)","vessel_count":"{} — Number of Vessels","page":"Page",
        "results":"Results – KPIs","status_hdr":"Performance Status",
        "recovery":"Recovery (%)","rejection":"Overall Rejection (%)","salt_pass":"Salt Passage (%)",
        "reject_tds":"Reject TDS (ppm est)","cf":"CF (Reject/Feed)","mb":"Mass Balance Error (%)",
        "dp":"ΔP (bar)","pi_feed":"π Feed (bar)","pi_perm":"π Perm (bar)","dpi":"Δπ (bar)","ndp":"NDP (bar)","prod":"Production (m³/day)",
        "per_vessel":"Per-Vessel Salt Performance","vessel":"Vessel","out_ppm":"Outlet TDS (ppm)","rej_pct":"Rejection (%)","pass_pct":"Salt Passage (%)",
        "save":"Save this run","saved":"Run saved to history ✅",
        "export_excel":"📥 Download Excel report (1 sheet)","export_pdf":"📄 Download PDF report",
        "flags":"Health Flags","ok":"OK","flag_hi_rec":"Recovery very high (>80%) → scaling risk",
        "flag_hi_dp":"High ΔP (>3 bar) → fouling/plugging check","flag_low_ndp":"Low NDP (<1 bar) → low driving force","flag_mb":"Mass balance outside ±5% → verify readings",
        "limit_hit":"You reached your capacity limit (max 5 unique capacities).",
        "req_more":"📩 Request more capacity","req_label":"Request new total capacity limit",
        "req_done":"Request sent. Admin will review.","req_pending":"A request is already pending. The admin will review it.",
        "inputs":"Inputs","outputs":"Outputs (KPIs)","no_vessels":"(no vessel data)",
        "signed":"Signed in","role":"Role","section":"Section","users":"Users","cap_req":"Capacity Requests (pending)",
        "filter_plant":"Filter by Plant Name","filter_site":"Filter by Site","export_hist":"📥 Export History (CSV)",
        "register_ok":"Registered. Please log in.","email_used":"Email already registered.","pwd_mismatch":"Passwords do not match.","need_ep":"Email & password required.","need_en":"Email & new password required.",
        "pwd_updated":"Password updated. Go to Login.","admin_only":"Admin only.",
        # NEW labels
        "overall":"Overall Plant Status","notes":"Notes","max_out":"Max Safe Output (LPM)","scaling_risk":"Scaling Risk"
    },
    # Other languages will fall back to English for new keys (overall/notes/max_out/scaling_risk)
    "ar": {"login":"تسجيل الدخول","register":"تسجيل","forgot":"نسيت كلمة المرور","app":"التطبيق","history":"السجل","admin":"الإدارة","help":"مساعدة",
           "plant_calc":"حاسبة أداء محطة RO","plant_name":"اسم المحطة","site_name":"الموقع","capacity":"السعة (م³/يوم)","temp":"الحرارة (°م)",
           "feed_tds":"TDS التغذية","perm_tds":"TDS المنتج","feed_flow":"تدفق التغذية","perm_flow":"تدفق المنتج","rej_flow":"تدفق الرجيع [اختياري]",
           "hp":"ضغط المضخة","brine":"ضغط الرجيع","perm_bp":"ضغط رجعي للمنتج","stage_type":"نوع المراحل","single":"مرحلة واحدة","two":"مرحلتان","three":"ثلاث مراحل",
           "s1":"المرحلة 1","s2":"المرحلة 2","s3":"المرحلة 3","results":"النتائج","status_hdr":"تقييم الأداء",
           "save":"حفظ","saved":"تم الحفظ","export_excel":"تنزيل Excel","export_pdf":"تنزيل PDF",
           "flags":"مؤشرات الصحة","ok":"سليم","limit_hit":"تم الوصول للحد","req_more":"طلب سعة أكبر","req_label":"الحد الجديد المطلوب"},
    "ml": {"login":"ലോഗിൻ","register":"രജിസ്റ്റർ","forgot":"പാസ്‌വേഡ് മറന്നോ","app":"ആപ്പ്","history":"ഹിസ്റ്ററി","admin":"അഡ്മിൻ","help":"ഹെൽപ്പ്",
           "plant_calc":"RO പ്ലാന്റ് പെർഫോർമൻസ് കാൽക്കുലേറ്റർ","plant_name":"പ്ലാന്റ് പേര്","site_name":"സൈറ്റ്","capacity":"ശേഷി (മീ³/ദിവസം)","temp":"താപനില (°C)",
           "feed_tds":"ഫീഡ് TDS","perm_tds":"പ്രോഡക്ട് TDS","feed_flow":"ഫീഡ് ഫ്ലോ","perm_flow":"പ്രോഡക്റ്റ് ഫ്ലോ","rej_flow":"റിജക്ട് ഫ്ലോ [ഓപ്ഷണൽ]",
           "hp":"HP ഡിസ്ചാർജ്","brine":"ബ്രൈൻ പ്രഷർ","perm_bp":"പെർമിയേറ്റ് ബാക്ക്‌പ്രഷർ","stage_type":"സ്റ്റേജ് തരം","single":"സിംഗിൾ","two":"ടു സ്റ്റേജ്","three":"ത്രീ സ്റ്റേജ്",
           "s1":"സ്റ്റേജ്-1","s2":"സ്റ്റേജ്-2","s3":"സ്റ്റേജ്-3","results":"ഫലം","status_hdr":"പെർഫോർമൻസ് സ്റ്റാറ്റസ്",
           "save":"റൺ സേവ് ചെയ്യുക","saved":"സേവ് ചെയ്തു","export_excel":"Excel ഡൗൺലോഡ്","export_pdf":"PDF ഡೌൺലോഡ്",
           "flags":"ഹെൽത്ത് ഫ്ലാഗ്സ്","ok":"OK","limit_hit":"പരിമിതി എത്തിയിരിക്കുന്നു","req_more":"കപ്പാസിറ്റി കൂട്ടാൻ അഭ്യർത്ഥിക്കൂ","req_label":"പുതിയ ലിമിറ്റ്"},
    "hi": {"login":"लॉगिन","register":"रजिस्टर","forgot":"पासवर्ड भूल गए","app":"ऐप","history":"इतिहास","admin":"एडमिन","help":"सहायता",
           "plant_calc":"RO प्लांट परफॉर्मेंस कैलकुलेटर","plant_name":"प्लांट नाम","site_name":"साइट","capacity":"क्षमता (m³/दिन)","temp":"तापमान (°C)",
           "feed_tds":"फीड TDS","perm_tds":"प्रोडक्ट TDS","feed_flow":"फीड फ्लो","perm_flow":"प्रोडक्ट फ्लो","rej_flow":"रिजेक्ट फ्लो [वैकल्पिक]",
           "hp":"HP डिस्चार्ज","brine":"ब्राइन प्रेशर","perm_bp":"परम बैकप्रेशर","stage_type":"स्टेज प्रकार","single":"सिंगल","two":"टू-स्टेज","three":"थ्री-स्टेज",
           "s1":"स्टेज-1","s2":"स्टेज-2","s3":"स्टेज-3","results":"परिणाम","status_hdr":"प्रदर्शन स्थिति",
           "save":"रन सेव करें","saved":"सेव किया","export_excel":"Excel डाउनलोड","export_pdf":"PDF डाउनलोड",
           "flags":"हेल्थ फ्लैग","ok":"OK","limit_hit":"सीमा पूरी हो गई","req_more":"क्षमता बढ़ाने का अनुरोध","req_label":"नया लिमिट"}
}
def t(k, lang): return T.get(lang, T["en"]).get(k, T["en"].get(k, k))

# ---------- DB helpers ----------
def _connect(): return sqlite3.connect(DB_PATH)
def _fetchone(q,p=()): con=_connect(); cur=con.cursor(); cur.execute(q,p); r=cur.fetchone(); con.close(); return r
def _fetchall(q,p=()): con=_connect(); cur=con.cursor(); cur.execute(q,p); r=cur.fetchall(); con.close(); return r
def _execute(q,p=()):  con=_connect(); cur=con.cursor(); cur.execute(q,p); con.commit(); con.close()

# ---------- DB init/migrate/seed ----------
def init_db():
    con=_connect(); cur=con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'user',
      capacity_limit INTEGER NOT NULL DEFAULT 5,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS capacity_requests(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      requested_capacity INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY(user_id) REFERENCES users(id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS runs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT,
      user_id INTEGER,
      plant_name TEXT,
      site_name TEXT,
      capacity REAL, temperature REAL,
      feed_tds REAL, product_tds REAL,
      feed_flow REAL, product_flow REAL, reject_flow REAL,
      hp REAL, brine REAL, perm_bp REAL,
      stage_type TEXT,
      recovery REAL, rejection REAL, salt_pass REAL,
      reject_tds REAL, cf REAL, mb_error REAL,
      dP REAL, pi_feed REAL, pi_perm REAL, d_pi REAL, ndp REAL,
      prod_m3d REAL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    )""")
    con.commit(); con.close()

def migrate_db():
    con=_connect(); cur=con.cursor()
    cur.execute("PRAGMA table_info(runs)"); cols={r[1] for r in cur.fetchall()}
    needed={"perm_bp":"REAL","stage_type":"TEXT","pi_feed":"REAL","pi_perm":"REAL","d_pi":"REAL","ndp":"REAL","prod_m3d":"REAL","user_id":"INTEGER"}
    for col,ddl in needed.items():
        if col not in cols: cur.execute(f"ALTER TABLE runs ADD COLUMN {col} {ddl}")
    con.commit(); con.close()

def ensure_admin():
    if not _fetchone("SELECT id FROM users WHERE email=?", (ADMIN_EMAIL,)):
        _execute("INSERT INTO users(email,password,role,capacity_limit) VALUES(?,?,?,?)",
                 (ADMIN_EMAIL, ADMIN_PASSWORD, "admin", 999))

init_db(); migrate_db(); ensure_admin()

# ---------- Session ----------
if "page" not in st.session_state: st.session_state.page="auth"
if "user" not in st.session_state: st.session_state.user=None
if "stage_choice" not in st.session_state: st.session_state.stage_choice="single"   # stable key
if "lang" not in st.session_state: st.session_state.lang="en"

# ---------- Core calcs ----------
def compute_core(feed_tds, product_tds, feed_flow, product_flow, reject_flow_in,
                 temperature_c, hp_out_bar, brine_bar, perm_bp_bar):
    reject_flow = reject_flow_in if reject_flow_in>0 else max(feed_flow - product_flow, 0.0)
    recovery   = (product_flow/feed_flow*100.0) if feed_flow>0 else 0.0
    rejection  = ((feed_tds - product_tds)/feed_tds*100.0) if feed_tds>0 else 0.0
    salt_pass  = max(0.0, 100.0 - rejection)

    feed_salt = feed_tds*feed_flow; perm_salt = product_tds*product_flow
    reject_tds = ((feed_salt - perm_salt)/reject_flow) if reject_flow>0 else 0.0
    cf = (reject_tds/feed_tds) if feed_tds>0 else 0.0
    out_mg_min = perm_salt + reject_tds*reject_flow
    mb_error = ((out_mg_min - feed_salt)/feed_salt*100.0) if feed_salt>0 else 0.0

    temp_factor = 1.0 + 0.02 * (temperature_c - 25.0)/25.0
    pi_feed = 0.0008*feed_tds*temp_factor; pi_perm=0.0008*product_tds*temp_factor
    d_pi = max(pi_feed - pi_perm, 0.0)

    dP = max(hp_out_bar - brine_bar, 0.0)
    feed_avg = (hp_out_bar + brine_bar)/2.0 if (hp_out_bar>0 and brine_bar>0) else hp_out_bar
    ndp = max(feed_avg - perm_bp_bar - d_pi, 0.0)

    return {"recovery":round(recovery,2),"rejection":round(rejection,2),"salt_pass":round(salt_pass,2),
            "reject_flow":round(reject_flow,3),"reject_tds":round(reject_tds,2),"cf":round(cf,3),
            "mb_error":round(mb_error,2),"pi_feed":round(pi_feed,3),"pi_perm":round(pi_perm,3),
            "d_pi":round(d_pi,3),"dP":round(dP,3),"ndp":round(ndp,3)}

def compute_max_safe_output(feed_tds, product_tds, feed_flow, cf_limit=2.5):
    """Return (Qp_max_LPM, Qr_LPM, reject_tds_ppm) using mass balance at a CF limit."""
    if feed_tds <= 0 or feed_flow <= 0: return 0.0, feed_flow, 0.0
    # Qp = Qf * (1 - CF) / ((Cp/Cf) - CF)
    denom = (product_tds / float(feed_tds)) - cf_limit
    if denom >= 0:  # avoid division by zero or positive (no solution)
        return 0.0, feed_flow, feed_tds
    qf = float(feed_flow)
    qp = qf * (1.0 - cf_limit) / denom
    qp = max(0.0, min(qp, qf))
    qr = max(qf - qp, 0.0)
    # reject TDS from mass balance:
    rej_tds = ((feed_tds*qf - product_tds*qp) / qr) if qr>0 else feed_tds
    return round(qp,2), round(qr,2), round(rej_tds,2)

def scaling_risk_label(cf):
    if cf <= 2.0: return "Low"
    if cf <= 2.5: return "Medium"
    if cf <= 3.0: return "High"
    return "Very High"

# ---------- Performance Status ----------
def evaluate_status(core: dict) -> tuple[str, list[str]]:
    reasons=[]
    rec=core["recovery"]; rej=core["rejection"]; cf=core["cf"]; dp=core["dP"]; ndp=core["ndp"]; mbe=abs(core["mb_error"])
    if rej < 92: reasons.append("Low rejection (<92%)")
    if cf  > 3:  reasons.append("High concentration factor (>3.0) → scaling risk")
    if dp  > 4:  reasons.append("High ΔP (>4 bar) → fouling/plugging suspected")
    if ndp < 1:  reasons.append("Low NDP (<1 bar) → weak driving force")
    if mbe > 8:  reasons.append("Mass balance error (>±8%) → verify meters/readings")
    if rec > 80: reasons.append("Very high recovery (>80%) → scaling risk")
    if rec < 25: reasons.append("Very low recovery (<25%) → capacity under-used")

    if (rej >= 95 and cf <= 2.5 and 1 <= ndp and dp <= 3 and mbe <= 5 and 35 <= rec <= 75):
        status="Good"
    elif (rej >= 92 and cf <= 3.0 and ndp >= 1.0 and dp <= 4 and mbe <= 8):
        status="OK"
    else:
        status="Needs attention"

    if status != "Needs attention":
        reasons = [r for r in reasons if "recovery" not in r.lower()]
    return status, reasons

def overall_text(status):
    return "Good" if status=="Good" else ("Average" if status=="OK" else "Poor")

def make_notes(core, max_qp, cf_limit):
    notes=[]
    # product quality
    if core["rejection"] >= 95: notes.append("Product quality is good (rejection ≥95%).")
    elif core["rejection"] >= 92: notes.append("Product quality acceptable (rejection ≥92%).")
    else: notes.append("Product quality low — check membranes / fouling.")

    # recovery vs max
    rec_now = core["recovery"]
    # approximate max recovery at cf_limit using max_qp
    # (if feed_flow > 0)
    notes.append(f"Current recovery {rec_now:.1f}%. Max safe output (CF≤{cf_limit}) ≈ {max_qp:.0f} LPM.")

    # pressures
    if core["dP"] > 4: notes.append("ΔP high — possible fouling/plugging.")
    else: notes.append("ΔP normal.")

    if core["ndp"] < 1: notes.append("NDP low — increase driving force (check pressures/backpressure).")
    else: notes.append("NDP OK.")

    # mass balance
    if abs(core["mb_error"]) > 5: notes.append("Mass balance off (>±5%) — verify meters.")
    else: notes.append("Mass balance OK.")

    # scaling
    risk = scaling_risk_label(core["cf"])
    notes.append(f"Scaling risk: {risk} (CF={core['cf']:.2f}).")
    return notes[:6]

# ---------- Auth ----------
def auth_login(email, password):
    row=_fetchone("SELECT id,email,role,capacity_limit FROM users WHERE email=? AND password=?",(email.strip(),password))
    if row:
        st.session_state.user={"id":row[0],"email":row[1],"role":row[2],"capacity_limit":row[3]}
        st.session_state.page="app"; st.rerun()
    else: st.error("Invalid credentials.")

def auth_register(email, password):
    try:
        _execute("INSERT INTO users(email,password,role,capacity_limit) VALUES(?,?,?,?)",(email.strip(),password,"user",5))
        st.success(t("register_ok", st.session_state.lang))
    except sqlite3.IntegrityError:
        st.error(t("email_used", st.session_state.lang))

def auth_reset(email, new_pwd):
    _execute("UPDATE users SET password=? WHERE email=?", (new_pwd, email.strip()))
    st.success(t("pwd_updated", st.session_state.lang))

def topbar():
    lang = st.selectbox("Language / اللغة / ഭാഷ / भाषा", list(LANGS.keys()),
                        format_func=lambda k: LANGS[k], index=list(LANGS.keys()).index(st.session_state.lang))
    if lang != st.session_state.lang:
        st.session_state.lang = lang; st.rerun()
    st.markdown(f"{t('signed',lang)}:** {st.session_state.user['email']}  •  {t('role',lang)}: {st.session_state.user['role']}")
    labels=[t('app',lang),t('history',lang),t('admin',lang),t('help',lang)]
    choice = st.radio(t('section',lang), labels, horizontal=True)
    mapping = {t('app',lang):'app', t('history',lang):'history', t('admin',lang):'admin', t('help',lang):'help'}
    target = mapping.get(choice,'app')
    if st.session_state.page != target: st.session_state.page=target; st.rerun()

# ---------- Capacity helpers ----------
def user_capacity_values(user_id:int):
    rows=_fetchall("SELECT DISTINCT capacity FROM runs WHERE user_id=? ORDER BY capacity",(user_id,))
    return [r[0] for r in rows]

def user_can_use_capacity(user:dict, cap:float)->tuple[bool,str]:
    used=user_capacity_values(user["id"])
    if cap in used: return True, f"Using existing capacity {cap} m³/d (used {len(used)}/{user['capacity_limit']})."
    if len(used) < int(user["capacity_limit"]): return True, f"Added capacity {cap} m³/d (now {len(used)+1}/{user['capacity_limit']})."
    return False, t("limit_hit", st.session_state.lang)

def submit_capacity_request(user_id: int, requested_limit: int) -> str:
    row = _fetchone("SELECT id FROM capacity_requests WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 1",(user_id,))
    if row: return t("req_pending", st.session_state.lang)
    _execute("INSERT INTO capacity_requests(user_id, requested_capacity, status) VALUES (?,?,?)",
             (user_id, int(requested_limit), "pending"))
    return t("req_done", st.session_state.lang)

# =================== Part 2/4 — Auth • Professional App Layout ===================

def auth_page():
    lang = st.session_state.lang
    st.title(f"{BRAND} {t('login',lang)}")
    choice = st.radio("", [t("login",lang), t("register",lang), t("forgot",lang)], horizontal=True)
    if choice == t("login",lang):
        email = st.text_input(t("email",lang))
        pwd   = st.text_input(t("password",lang), type="password")
        if st.button(t("login",lang), type="primary"): auth_login(email, pwd)
        if SHOW_ADMIN_HINT: st.info(f"Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    elif choice == t("register",lang):
        email = st.text_input(t("email",lang))
        p1 = st.text_input(t("password",lang), type="password")
        p2 = st.text_input(t("confirm",lang), type="password")
        if st.button(t("create_acc",lang), type="primary"):
            if not email or not p1: st.error(t("need_ep",lang))
            elif p1!=p2: st.error(t("pwd_mismatch",lang))
            else: auth_register(email,p1)
    else:
        email = st.text_input(t("email",lang))
        newp  = st.text_input(t("password",lang), type="password")
        if st.button(t("reset",lang), type="primary"):
            if not email or not newp: st.error(t("need_en",lang))
            else: auth_reset(email,newp)

def app_page():
    lang = st.session_state.lang
    topbar()
    st.markdown(f"<div class='section-title'>{t('plant_calc',lang)}</div>", unsafe_allow_html=True)

    # ===== Top controls row =====
    col_stage, col_names, col_env = st.columns([1.2, 2.0, 1.3])

    with col_stage:
        stage_keys = ["single", "two", "three"]  # stable keys
        try:
            idx = stage_keys.index(st.session_state.stage_choice)
        except ValueError:
            idx = 0
        stage_choice = st.radio(
            t("stage_type", lang),
            stage_keys,
            index=idx,
            format_func=lambda k: t(k, lang)
        )
        st.session_state.stage_choice = stage_choice

        # CF limit selector (for max safe output)
        cf_limit = st.slider("CF limit for Max Output", 2.0, 3.0, 2.5, 0.1)

    with col_names:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        plant_name = st.text_input(t("plant_name",lang), "My RO Plant")
        site_name  = st.text_input(t("site_name",lang), "Site A")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_env:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        capacity   = st.number_input(t("capacity",lang), 0.0, 100000.0, 100.0)
        temperature_c = st.number_input(t("temp",lang), 0.0, 60.0, 25.0)
        st.markdown("</div>", unsafe_allow_html=True)

    # ===== Inputs rows =====
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("Quality")
        feed_tds    = st.number_input(t("feed_tds",lang), 0.0, 100000.0, 900.0, step=1.0)
        product_tds = st.number_input(t("perm_tds",lang), 0.0, 100000.0, 120.0, step=1.0)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("Flows (LPM)")
        feed_flow      = st.number_input(t("feed_flow",lang), 0.0, 10000.0, 180.0, step=0.1)
        product_flow   = st.number_input(t("perm_flow",lang), 0.0, 10000.0, 125.0, step=0.1)
        reject_flow_in = st.number_input(t("rej_flow",lang), 0.0, 10000.0, 0.0, step=0.1)
        st.markdown("</div>", unsafe_allow_html=True)
    with c3:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("Pressures (bar)")
        hp_out_bar  = st.number_input(t("hp",lang), 0.0, 1000.0, 10.0, step=0.1)
        brine_bar   = st.number_input(t("brine",lang), 0.0, 1000.0, 7.0, step=0.1)
        perm_bp_bar = st.number_input(t("perm_bp",lang), 0.0, 1000.0, 0.0, step=0.1)
        st.markdown("</div>", unsafe_allow_html=True)

    # ===== Per-stage sliders (if 2/3 stage) =====
    if stage_choice != "single":
        s1, s2, s3 = st.columns([1,1,1])
        with s1: r1 = st.slider(t("s_recovery",lang).format(1), 10, 85, 60) / 100.0
        with s2: r2 = st.slider(t("s_recovery",lang).format(2), 10, 85, 50) / 100.0
        with s3: r3 = st.slider(t("s_recovery",lang).format(3), 10, 85, 40) / 100.0 if stage_choice=="three" else 0.0

        pcol1, pcol2, pcol3 = st.columns([1,1,1])
        with pcol1: p1_tds = st.number_input(t("s_perm_tds",lang).format(1), min_value=0.0, value=float(product_tds), key="p1_tds")
        with pcol2: p2_tds = st.number_input(t("s_perm_tds",lang).format(2), min_value=0.0, value=float(product_tds), key="p2_tds")
        with pcol3: p3_tds = st.number_input(t("s_perm_tds",lang).format(3), min_value=0.0, value=float(product_tds), key="p3_tds") if stage_choice=="three" else float(product_tds)
    else:
        r1=r2=r3=0.0; p1_tds=p2_tds=p3_tds=float(product_tds)

    # ===== Compute =====
    reject_flow = reject_flow_in if reject_flow_in > 0 else max(feed_flow - product_flow, 0.0)
    core = compute_core(feed_tds, product_tds, feed_flow, product_flow, reject_flow,
                        temperature_c, hp_out_bar, brine_bar, perm_bp_bar)
    LPM_TO_M3D = 1.44; prod_m3d = product_flow * LPM_TO_M3D; core["prod_m3d"]=round(prod_m3d,2)

    # Max safe output at chosen CF limit
    qp_max, qr_at_max, rej_tds_at_max = compute_max_safe_output(feed_tds, product_tds, feed_flow, cf_limit)

    # ===== NEW: Quick tiles =====
    k0 = st.columns(6)
    with k0[0]: st.metric("Reject Flow (LPM)", f"{reject_flow:.2f}")
    with k0[1]: st.metric(t("max_out",lang)+f" (CF≤{cf_limit:.1f})", f"{qp_max:.2f}")
    with k0[2]: st.metric(t("scaling_risk",lang), scaling_risk_label(core["cf"]))

    # ===== KPI Cards (2 rows) =====
    st.markdown(f"<div class='section-title'>{t('results',lang)}</div>", unsafe_allow_html=True)
    k1 = st.columns(6)
    with k1[0]: st.metric(t("recovery",lang),   f"{core['recovery']:.2f}")
    with k1[1]: st.metric(t("rejection",lang),  f"{core['rejection']:.2f}")
    with k1[2]: st.metric(t("salt_pass",lang),  f"{core['salt_pass']:.2f}")
    with k1[3]: st.metric(t("reject_tds",lang), f"{core['reject_tds']:.2f}")
    with k1[4]: st.metric(t("cf",lang),         f"{core['cf']:.3f}")
    with k1[5]: st.metric(t("mb",lang),         f"{core['mb_error']:.2f}")

    k2 = st.columns(6)
    with k2[0]: st.metric(t("dp",lang),      f"{core['dP']:.2f}")
    with k2[1]: st.metric(t("pi_feed",lang), f"{core['pi_feed']:.2f}")
    with k2[2]: st.metric(t("pi_perm",lang), f"{core['pi_perm']:.2f}")
    with k2[3]: st.metric(t("dpi",lang),     f"{core['d_pi']:.2f}")
    with k2[4]: st.metric(t("ndp",lang),     f"{core['ndp']:.2f}")
    with k2[5]: st.metric(t("prod",lang),    f"{core['prod_m3d']:.2f}")

    # ===== Overall status + Notes =====
    st.markdown(f"<div class='section-title'>{t('overall',lang)}</div>", unsafe_allow_html=True)
    status, reasons = evaluate_status(core)
    status_box = "good" if status=="Good" else ("ok" if status=="OK" else "bad")
    overall = overall_text(status)
    st.markdown(f"<div class='card {status_box}'><b>{overall}</b> — {t('status_hdr',lang)}: {status}</div>", unsafe_allow_html=True)

    notes = make_notes(core, qp_max, cf_limit)
    st.markdown(f"<div class='card'><b>{t('notes',lang)}</b><div class='note'>" + "<br>".join("• "+n for n in notes) + "</div></div>", unsafe_allow_html=True)

    # ===== Per-vessel inputs (paged) =====
    def vessel_inputs(label: str, default_count: int, key_prefix: str):
        st.markdown(f"<div class='section-title'>{t('vessel_hdr',lang).format(label)}</div>", unsafe_allow_html=True)
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        vcount = st.slider(t("vessel_count",lang).format(label), 1, 100, default_count, key=f"{key_prefix}_count")
        page_size=10; pages=(vcount+page_size-1)//page_size
        page = st.number_input(t("page",lang), 1, max(1,pages), 1, key=f"{key_prefix}_page")
        start=(page-1)*page_size; end=min(start+page_size, vcount)
        cols = st.columns(5)
        vals=[0.0]*vcount
        for i in range(start,end):
            with cols[i%5]:
                vals[i] = st.number_input(f"{label} V{i+1} TDS", min_value=0.0, value=0.0, step=1.0, key=f"{key_prefix}_v{i+1}")
        st.markdown("</div>", unsafe_allow_html=True)
        return vals

    if stage_choice == "single":
        v_s1 = vessel_inputs(t("s1",lang), 6, "s1"); v_s2=[]; v_s3=[]
    elif stage_choice == "two":
        v_s1 = vessel_inputs(t("s1",lang), 6, "s1"); v_s2 = vessel_inputs(t("s2",lang), 3, "s2"); v_s3=[]
    else:
        v_s1 = vessel_inputs(t("s1",lang), 6, "s1"); v_s2 = vessel_inputs(t("s2",lang), 3, "s2"); v_s3 = vessel_inputs(t("s3",lang), 2, "s3")

    # ===== Per-vessel table =====
    def stage_reject_tds(qf, feed_ppm, rec_frac, perm_ppm):
        qp=qf*rec_frac; qr=max(qf-qp,0.0); tds_r=(feed_ppm*qf - perm_ppm*qp)/qr if qr>0 else feed_ppm; return tds_r, qp, qr

    vessel_rows=[]
    if stage_choice == "single":
        stage_feed_ppm = feed_tds
        for i,tv in enumerate(v_s1,1):
            if 0 < tv <= stage_feed_ppm:
                rej=(stage_feed_ppm-tv)/stage_feed_ppm*100.0
                vessel_rows.append({"Stage":"S1",t("vessel",lang):i,t("out_ppm",lang):tv,t("rej_pct",lang):rej,t("pass_pct",lang):100-rej})
    elif stage_choice == "two":
        tds_r1, qp1, qr1 = stage_reject_tds(feed_flow, feed_tds, r1, p1_tds)
        for i,tv in enumerate(v_s1,1):
            if 0 < tv <= feed_tds:
                rej=(feed_tds-tv)/feed_tds*100.0
                vessel_rows.append({"Stage":"S1",t("vessel",lang):i,t("out_ppm",lang):tv,t("rej_pct",lang):rej,t("pass_pct",lang):100-rej})
        for i,tv in enumerate(v_s2,1):
            if 0 < tv <= tds_r1:
                rej=(tds_r1-tv)/tds_r1*100.0
                vessel_rows.append({"Stage":"S2",t("vessel",lang):i,t("out_ppm",lang):tv,t("rej_pct",lang):rej,t("pass_pct",lang):100-rej})
    else:
        tds_r1, qp1, qr1 = stage_reject_tds(feed_flow, feed_tds, r1, p1_tds)
        tds_r2, qp2, qr2 = stage_reject_tds(qr1, tds_r1, r2, p2_tds)
        for i,tv in enumerate(v_s1,1):
            if 0 < tv <= feed_tds:
                rej=(feed_tds-tv)/feed_tds*100.0
                vessel_rows.append({"Stage":"S1",t("vessel",lang):i,t("out_ppm",lang):tv,t("rej_pct",lang):rej,t("pass_pct",lang):100-rej})
        for i,tv in enumerate(v_s2,1):
            if 0 < tv <= tds_r1:
                rej=(tds_r1-tv)/tds_r1*100.0
                vessel_rows.append({"Stage":"S2",t("vessel",lang):i,t("out_ppm",lang):tv,t("rej_pct",lang):rej,t("pass_pct",lang):100-rej})
        for i,tv in enumerate(v_s3,1):
            if 0 < tv <= tds_r2:
                rej=(tds_r2-tv)/tds_r2*100.0
                vessel_rows.append({"Stage":"S3",t("vessel",lang):i,t("out_ppm",lang):tv,t("rej_pct",lang):rej,t("pass_pct",lang):100-rej})

    df_vessels = pd.DataFrame(vessel_rows) if vessel_rows else pd.DataFrame(
        columns=["Stage",t("vessel",lang),t("out_ppm",lang),t("rej_pct",lang),t("pass_pct",lang)]
    )
    if not df_vessels.empty:
        st.markdown(f"<div class='section-title'>{t('per_vessel',lang)}</div>", unsafe_allow_html=True)
        st.dataframe(df_vessels, use_container_width=True, height=280)

    # ===== Save row =====
    s1, s2 = st.columns([1,4])
    with s1:
        if st.button("💾 "+t("save",lang), type="primary"):
            ok2, msg2 = user_can_use_capacity(st.session_state.user, capacity)
            if not ok2: st.error(msg2)
            else:
                _execute(
                    """INSERT INTO runs(ts,user_id,plant_name,site_name,capacity,temperature,feed_tds,product_tds,
                       feed_flow,product_flow,reject_flow,hp,brine,perm_bp,stage_type,
                       recovery,rejection,salt_pass,reject_tds,cf,mb_error,dP,pi_feed,pi_perm,d_pi,ndp,prod_m3d)
                       VALUES(datetime('now'),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (st.session_state.user["id"],plant_name,site_name,capacity,temperature_c,
                     feed_tds,product_tds,feed_flow,product_flow,reject_flow,
                     hp_out_bar,brine_bar,perm_bp_bar,stage_choice,
                     core["recovery"],core["rejection"],core["salt_pass"],core["reject_tds"],core["cf"],core["mb_error"],
                     core["dP"],core["pi_feed"],core["pi_perm"],core["d_pi"],core["ndp"],core["prod_m3d"])
                )
                st.success(t("saved",lang))

    # ===== Exports =====
    export_section(core, plant_name, site_name, capacity, temperature_c, stage_choice,
                   feed_tds, product_tds, feed_flow, product_flow, reject_flow,
                   hp_out_bar, brine_bar, perm_bp_bar, df_vessels, qp_max, cf_limit)

# =================== Part 3/4 — Exports (one-sheet Excel + polished PDF) ===================

def export_section(core, plant_name, site_name, capacity, temperature_c, stage_choice,
                   feed_tds, product_tds, feed_flow, product_flow, reject_flow,
                   hp_out_bar, brine_bar, perm_bp_bar, df_vessels, qp_max, cf_limit):
    lang = st.session_state.lang

    # Overall status text
    status, reasons = evaluate_status(core)
    overall = overall_text(status)
    status_text = f"{overall} — {status}"
    if reasons: status_text += " — " + "; ".join(reasons[:6])

    # -------- Tables for export --------
    display_stage = t(stage_choice, lang)  # translated label
    df_inputs = pd.DataFrame({
        "Parameter":[t("plant_name",lang),t("site_name",lang),t("capacity",lang),t("temp",lang),t("stage_type",lang),
                     t("feed_tds",lang),t("perm_tds",lang),t("feed_flow",lang),t("perm_flow",lang),t("rej_flow",lang),
                     t("hp",lang),t("brine",lang),t("perm_bp",lang)],
        "Value":[plant_name,site_name,capacity,temperature_c,display_stage,feed_tds,product_tds,
                 feed_flow,product_flow,reject_flow,hp_out_bar,brine_bar,perm_bp_bar]
    })

    notes = make_notes(core, qp_max, cf_limit)

    df_outputs = pd.DataFrame({
        "KPI":[
            "Performance Status",
            "Reject Flow (LPM)",
            t("max_out",lang)+f" (CF≤{cf_limit:.1f})",
            t("recovery",lang),t("rejection",lang),t("salt_pass",lang),t("reject_tds",lang),t("cf",lang),
            t("mb",lang),t("dp",lang),t("pi_feed",lang),t("pi_perm",lang),t("dpi",lang),t("ndp",lang),t("prod",lang),
            t("notes",lang)
        ],
        "Value":[
            status_text,
            core["reject_flow"],
            qp_max,
            core["recovery"],core["rejection"],core["salt_pass"],core["reject_tds"],core["cf"],
            core["mb_error"],core["dP"],core["pi_feed"],core["pi_perm"],core["d_pi"],core["ndp"],core["prod_m3d"],
            " | ".join(notes)
        ]
    })

    # -------- Excel (single sheet + KPI chart) --------
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_buf = BytesIO()
    with pd.ExcelWriter(excel_buf, engine="xlsxwriter") as writer:
        wb = writer.book
        ws = wb.add_worksheet("Report")
        writer.sheets["Report"] = ws

        title = wb.add_format({"bold":True,"font_size":16,"font_color":"#1f6feb"})
        hdr   = wb.add_format({"bold":True,"bg_color":"#E6F0FF","border":1})
        box   = wb.add_format({"border":1})
        num2  = wb.add_format({"num_format":"0.00","border":1})

        ws.set_column(0,0,32)
        ws.set_column(1,1,22)
        ws.set_column(3,8,18)

        row = 0
        ws.merge_range(row,0,row,4,"LeeWave – RO Run Report", title)
        row += 2

        ws.write(row,0,t("inputs",lang),hdr); row += 1
        ws.write_row(row,0,["Parameter","Value"],hdr); row += 1
        for p,v in df_inputs.itertuples(index=False):
            ws.write(row,0,p,box)
            if isinstance(v,(int,float)): ws.write_number(row,1,float(v),num2)
            else: ws.write(row,1,str(v),box)
            row += 1
        row += 1

        ws.write(row,0,t("outputs",lang),hdr); row += 1
        kpi_start = row
        ws.write_row(row,0,["KPI","Value"],hdr); row += 1
        for k,v in df_outputs.itertuples(index=False):
            ws.write(row,0,k,box)
            if isinstance(v,(int,float)): ws.write_number(row,1,float(v),num2)
            else: ws.write(row,1,str(v),box)
            row += 1
        kpi_end = row - 1
        row += 1

        ws.write(row,0,t("per_vessel",lang),hdr); row += 1
        if df_vessels.empty:
            ws.write(row,0,t("no_vessels",lang)); row += 1
        else:
            ws.write_row(row,0,list(df_vessels.columns),hdr); row += 1
            for _,r in df_vessels.iterrows():
                ws.write(row,0,str(r["Stage"]),box)
                ws.write_number(row,1,float(r[t("vessel",lang)]),box)
                ws.write_number(row,2,float(r[t("out_ppm",lang)]),num2)
                ws.write_number(row,3,float(r[t("rej_pct",lang)]),num2)
                ws.write_number(row,4,float(r[t("pass_pct",lang)]),num2)
                row += 1

        chart = wb.add_chart({"type":"column"})
        chart.add_series({
            "name":"KPIs",
            "categories":["Report",kpi_start+1,0,kpi_end,0],
            "values":["Report",kpi_start+1,1,kpi_end,1],
        })
        chart.set_title({"name":"Main KPIs"})
        chart.set_legend({"position":"none"})
        chart.set_size({"width":520,"height":300})
        ws.insert_chart(kpi_start,3,chart)

    st.download_button(
        t("export_excel",lang),
        data=excel_buf.getvalue(),
        file_name=f"{plant_name}_{ts_str}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # -------- PDF --------
    with st.expander("📄 PDF"):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import cm
            from reportlab.lib.colors import Color

            buf = BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            w, h = A4

            # Header bar
            blue = Color(31/255,111/255,235/255)
            c.setFillColor(blue)
            c.rect(0, h-1.2*cm, w, 1.2*cm, fill=1, stroke=0)
            c.setFillColorRGB(1,1,1)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(1.5*cm, h-0.8*cm, "LeeWave — RO Run Report")

            y = h - 2.2*cm
            def line(txt, dy=14, bold=False):
                nonlocal y
                c.setFont("Helvetica-Bold" if bold else "Helvetica", 11 if bold else 10)
                c.setFillColorRGB(0,0,0)
                c.drawString(2*cm, y, str(txt))
                y -= dy

            line(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 12)
            line(t("inputs",lang), 16, True)
            for p,v in df_inputs.itertuples(index=False):
                line(f"{p}: {v}")

            line(t("outputs",lang), 16, True)
            line("Performance: " + (overall_text(evaluate_status(core)[0])))
            for k in ["Reject Flow (LPM)", t("max_out",lang)+f" (CF≤{cf_limit:.1f})",
                      t("recovery",lang), t("rejection",lang), t("salt_pass",lang),
                      t("reject_tds",lang), t("cf",lang), t("mb",lang),
                      t("dp",lang), t("pi_feed",lang), t("pi_perm",lang), t("dpi",lang), t("ndp",lang), t("prod",lang)]:
                v = df_outputs[df_outputs["KPI"]==k]["Value"].values
                if len(v):
                    vv=v[0]
                    if isinstance(vv,(int,float)): line(f"{k}: {vv:.3f}")
                    else: line(f"{k}: {vv}")

            line(t("notes",lang), 16, True)
            for n in make_notes(core, qp_max, cf_limit):
                line("• " + n)

            c.showPage(); c.save()
            st.download_button(
                t("export_pdf",lang),
                data=buf.getvalue(),
                file_name=f"{plant_name}_{ts_str}.pdf",
                mime="application/pdf"
            )
        except ImportError:
            st.warning("Install once:  pip install reportlab")

# =================== Part 4/4 — History • Admin • Help • Router ===================

def history_page():
    lang = st.session_state.lang
    user = st.session_state.user
    topbar()
    st.header(t("history",lang))

    con=_connect()
    if user["role"]=="admin":
        df = pd.read_sql_query("SELECT * FROM runs ORDER BY ts DESC LIMIT 1000", con)
    else:
        df = pd.read_sql_query("SELECT * FROM runs WHERE user_id=? ORDER BY ts DESC LIMIT 1000", con, params=(user["id"],))
    con.close()

    if df.empty:
        st.info("No saved runs yet."); 
        return

    fcol1, fcol2 = st.columns(2)
    with fcol1: f1 = st.text_input(t("filter_plant",lang), "")
    with fcol2: f2 = st.text_input(t("filter_site",lang),  "")
    if f1: df = df[df["plant_name"].astype(str).str.contains(f1, case=False, na=False)]
    if f2: df = df[df["site_name"].astype(str).str.contains(f2, case=False, na=False)]

    st.dataframe(df, use_container_width=True, height=420)

    if "ts" in df.columns:
        ch1, ch2, ch3 = st.columns(3)
        with ch1:
            if "recovery" in df.columns:
                st.line_chart(df.set_index("ts")[["recovery"]], height=180)
        with ch2:
            if "dP" in df.columns:
                st.line_chart(df.set_index("ts")[["dP"]], height=180)
        with ch3:
            if "product_tds" in df.columns:
                st.line_chart(df.set_index("ts")[["product_tds"]], height=180)

    st.download_button(
        t("export_hist",lang),
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="ro_history.csv",
        mime="text/csv"
    )

def admin_page():
    lang = st.session_state.lang
    user = st.session_state.user
    topbar()
    if user["role"]!="admin":
        st.error(t("admin_only",lang)); 
        return
    st.header(t("admin",lang))

    con=_connect(); cur=con.cursor()
    users_df = pd.read_sql_query("SELECT id, email, role, capacity_limit, created_at FROM users ORDER BY id", con)
    st.subheader(t("users",lang))
    st.dataframe(users_df, use_container_width=True)

    st.subheader(t("cap_req",lang))
    req_df = pd.read_sql_query("""
        SELECT r.id, u.email, r.user_id, r.requested_capacity, r.status, r.created_at
        FROM capacity_requests r JOIN users u ON u.id=r.user_id
        WHERE r.status='pending' ORDER BY r.created_at DESC
    """, con)

    if req_df.empty:
        st.info("No pending requests.")
    else:
        st.dataframe(req_df, use_container_width=True)
        rid = st.number_input("Request ID", min_value=1, step=1)
        c1,c2 = st.columns(2)
        with c1:
            if st.button("Approve"):
                cur.execute("SELECT user_id, requested_capacity FROM capacity_requests WHERE id=?", (int(rid),))
                row=cur.fetchone()
                if row:
                    uid,new_lim=row
                    cur.execute("UPDATE users SET capacity_limit=? WHERE id=?", (int(new_lim), int(uid)))
                    cur.execute("UPDATE capacity_requests SET status='approved' WHERE id=?", (int(rid),))
                    con.commit()
                    st.success(f"Approved. User {uid} → limit {new_lim}")
                    st.rerun()
                else:
                    st.error("Invalid request ID.")
        with c2:
            if st.button("Deny"):
                cur.execute("UPDATE capacity_requests SET status='denied' WHERE id=?", (int(rid),))
                con.commit()
                st.warning("Denied.")
                st.rerun()
    con.close()

def help_page():
    lang = st.session_state.lang
    topbar()
    st.header(t("help",lang))
    st.markdown(f"""
How to use
1) Choose {t('stage_type',lang)} → {t('single',lang)}, {t('two',lang)}, {t('three',lang)}.
2) Fill {t('plant_name',lang)} / {t('site_name',lang)} / {t('capacity',lang)} / {t('temp',lang)}.
3) Enter TDS, flows, pressures.
4) Enter {t('per_vessel',lang)} (paged).
5) Review {t('results',lang)}, **{t('status_hdr',lang)}, *{t('max_out',lang)} and {t('flags',lang)}.
6) {t('save',lang)} to keep in {t('history',lang)}, or export **Excel/PDF.
7) If you hit the 5 capacity limit, click **{t('req_more',lang)} to ask admin.
""")

# -------------------- Router --------------------
if st.session_state.user is None or st.session_state.page == "auth":
    auth_page()
else:
    if   st.session_state.page == "app":      app_page()
    elif st.session_state.page == "history":  history_page()
    elif st.session_state.page == "admin":    admin_page()
    elif st.session_state.page == "help":     help_page()
    else:                                     app_page()