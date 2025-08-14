# ================== LeeWave RO Reporter — Professional (FINAL, PART 1/2) ==================
# Focus: plant health, quality, hydraulics & maintenance (NO electrical inputs)
# English + Arabic UI, rich outputs, per-vessel rejection, weekly/monthly, exports (in Part 2)

import os, io, re, json, smtplib, base64, hashlib, hmac
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path
from datetime import datetime, date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

# -------------------- optional deps --------------------
try:
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
except Exception:
    class SignatureExpired(Exception): ...
    class BadSignature(Exception): ...
    class _MiniSerializer:
        def _init_(self, secret): self.secret = secret.encode()
        def dumps(self, text, salt=""):
            msg = (salt + "|" + text).encode()
            sig = hmac.new(self.secret, msg, hashlib.sha256).digest()
            return base64.urlsafe_b64encode(msg + b"." + sig).decode()
        def loads(self, token, salt="", max_age=None):
            raw = base64.urlsafe_b64decode(token.encode())
            msg, sig = raw.rsplit(b".", 1)
            if not hmac.compare_digest(hmac.new(self.secret, msg, hashlib.sha256).digest(), sig):
                raise BadSignature("bad sig")
            _salt, text = msg.decode().split("|", 1)
            if _salt != salt: raise BadSignature("bad salt")
            return text
    def URLSafeTimedSerializer(secret): return _MiniSerializer(secret)

try:
    import bcrypt; BCRYPT_OK = True
except Exception:
    bcrypt = None; BCRYPT_OK = False

# exports (used in Part 2)
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

try:
    import xlsxwriter
    XLSX_OK = True
except Exception:
    XLSX_OK = False

# -------------------- app meta & theme --------------------
BRAND = "LeeWave"
PRIMARY_HEX = "#0B7285"
ACCENT_HEX  = "#E3FAFC"

APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = APP_DIR / "data"
USERS_DIR = DATA_DIR / "users"
REPORTS_DIRNAME = "reports"
for d in [DATA_DIR, USERS_DIR]: d.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title=f"{BRAND} — RO Dashboard", page_icon="💧", layout="wide")
st.markdown(
    f"""
    <style>
      .block-container{{padding-top:0.7rem}}
      h1,h2,h3,h4{{color:{PRIMARY_HEX}}}
      .lee-badge{{background:{ACCENT_HEX};border:1px solid #b8f2f7;padding:6px 10px;border-radius:10px;display:inline-block}}
      .good{{background:#eaf8ef;border-radius:8px;padding:6px 10px}}
      .warn{{background:#fff8e1;border-radius:8px;padding:6px 10px}}
      .bad{{background:#fdecea;border-radius:8px;padding:6px 10px}}
      .kcard div[data-testid="stMetricValue"]{{font-size:22px}}
      .tight-table td, .tight-table th {{ padding: 6px 8px !important; }}
    </style>
    """,
    unsafe_allow_html=True
)

# -------------------- env (reset links) --------------------
SECRET_KEY   = os.environ.get("SECRET_KEY", "dev-change-me-please")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8501")
SMTP_HOST    = os.environ.get("SMTP_HOST", "")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER    = os.environ.get("SMTP_USER", "")
SMTP_PASS    = os.environ.get("SMTP_PASS", "")
MAIL_FROM    = os.environ.get("MAIL_FROM", "no-reply@leewave.app")
ts = URLSafeTimedSerializer(SECRET_KEY)

# -------------------- password helpers --------------------
def _hash_bcrypt(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
def _verify_bcrypt(pw: str, hashed: str) -> bool:
    try: return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception: return False
def _hash_pbkdf2(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000)
    return "pbkdf2$" + base64.b64encode(salt + dk).decode()
def _verify_pbkdf2(pw: str, hashed: str) -> bool:
    try:
        b = base64.b64decode(hashed.split("pbkdf2$")[1].encode())
        salt, dk = b[:16], b[16:]
        dk2 = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000)
        return hmac.compare_digest(dk, dk2)
    except Exception: return False
def hash_password(pw: str) -> str:
    return _hash_bcrypt(pw) if BCRYPT_OK else _hash_pbkdf2(pw)
def verify_password(pw: str, hashed: str) -> bool:
    if hashed.startswith("pbkdf2$"): return _verify_pbkdf2(pw, hashed)
    return _verify_bcrypt(pw, hashed) if BCRYPT_OK else False

# -------------------- users db --------------------
USERS_DB_PATH = DATA_DIR / "users.json"

def _default_users():
    return {
        "users": {
            "admin@leewave.app": {
                "password_hash": hash_password("Admin123"),
                "role": "admin", "status": "active", "created": str(date.today()),
                "name": "Admin", "capacity_quota": 9999, "capacities_used": []
            }
        },
        "requests": []
    }

def save_users(obj: dict): USERS_DB_PATH.write_text(json.dumps(obj, indent=2))
def load_users() -> dict:
    if not USERS_DB_PATH.exists(): save_users(_default_users())
    try: return json.loads(USERS_DB_PATH.read_text())
    except Exception:
        save_users(_default_users()); return json.loads(USERS_DB_PATH.read_text())

def normalize_email(e: str) -> str: return (e or "").strip().lower()
def email_safe(e: str) -> str: return re.sub(r"[^a-zA-Z0-9_.-]+", "_", normalize_email(e))

def user_dir(email: str) -> Path:
    d = USERS_DIR / email_safe(email)
    d.mkdir(parents=True, exist_ok=True)
    for sub in ["daily","weekly","monthly"]:
        (d / REPORTS_DIRNAME / sub).mkdir(parents=True, exist_ok=True)
    return d

def set_user_status(email: str, status: str):
    db = load_users(); u = db["users"].get(normalize_email(email))
    if not u: return False
    u["status"]=status; save_users(db); return True

def send_reset_email(to_email: str, reset_link: str) -> bool:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and MAIL_FROM):
        st.info(f"🔗 Reset link (SMTP not configured): {reset_link}"); return True
    msg = MIMEText(f"Reset your {BRAND} password:\n{reset_link}\n(Link valid ~30 min)", "plain", "utf-8")
    msg["Subject"] = f"{BRAND} — Reset your password"; msg["From"]=MAIL_FROM; msg["To"]=to_email
    msg["Date"] = formatdate(localtime=True)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.sendmail(MAIL_FROM, [to_email], msg.as_string())
        return True
    except Exception as e:
        st.error(f"Email send failed: {e}"); return False

# -------------------- session & auth --------------------
if "authed" not in st.session_state:
    st.session_state.authed=False; st.session_state.user_email=None; st.session_state.user_role=None
if "login_attempts" not in st.session_state: st.session_state.login_attempts=0
if "lock_until" not in st.session_state: st.session_state.lock_until=None

def is_locked(): lu=st.session_state.lock_until; return (lu is not None) and (datetime.now()<lu)

def register_view():
    st.title("Create your account")
    with st.form("register"):
        email = st.text_input("Email"); name = st.text_input("Name (optional)")
        pw = st.text_input("Password", type="password"); pw2 = st.text_input("Confirm Password", type="password")
        ok = st.form_submit_button("Register")
    if ok:
        e = normalize_email(email)
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", e): st.error("Invalid email."); return
        if len(pw)<8 or not re.search(r"\d", pw): st.error("Password must be ≥ 8 characters and include a number."); return
        if pw!=pw2: st.error("Passwords do not match."); return
        db=load_users()
        if e in db["users"]: st.error("Email already registered."); return
        db["users"][e] = {
            "password_hash": hash_password(pw), "role":"user", "status":"active",
            "created": str(date.today()), "name": name.strip() or e, "capacity_quota": 5, "capacities_used":[]
        }
        save_users(db); user_dir(e); st.success("Registered. You can sign in now.")

def reset_password_view(token: str):
    try: email = ts.loads(token, salt="reset", max_age=1800)
    except SignatureExpired: st.error("Reset link expired."); return
    except BadSignature: st.error("Invalid reset link."); return
    st.title("Set a new password")
    with st.form("set_new_pw"):
        pw = st.text_input("New Password", type="password"); pw2 = st.text_input("Confirm New Password", type="password")
        ok = st.form_submit_button("Update Password")
    if ok:
        if len(pw)<8 or not re.search(r"\d", pw): st.error("Password must be ≥ 8 characters and include a number."); return
        if pw!=pw2: st.error("Passwords do not match."); return
        db=load_users(); u=db["users"].get(normalize_email(email))
        if not u: st.error("User not found."); return
        u["password_hash"]=hash_password(pw); db["users"][normalize_email(email)]=u; save_users(db)
        st.success("Password updated. Please sign in.")

def login_view():
    st.title("LeeWave RO • Sign in")
    qp = st.query_params
    if "reset_token" in qp: reset_password_view(qp["reset_token"]); st.stop()
    if is_locked(): st.error("Too many attempts. Try again later."); st.stop()
    with st.form("login"):
        email_in = st.text_input("Email", placeholder="you@company.com")
        pwd_in   = st.text_input("Password", type="password", placeholder="••••••••")
        c1,c2,c3 = st.columns([1,1,1])
        ok = c1.form_submit_button("Sign in")
        go_register = c2.form_submit_button("Register")
        forgot = c3.form_submit_button("Forgot password?")
    if go_register:
        register_view(); st.stop()
    if forgot:
        enter = st.text_input("Enter your registered email", key="reset_email")
        if st.button("Send reset link"):
            e = normalize_email(enter); db=load_users(); u=db["users"].get(e)
            if not u: st.error("No account found for that email.")
            elif u.get("status")=="disabled": st.error("Account disabled. Contact admin.")
            else:
                token = ts.dumps(e, salt="reset"); link = f"{APP_BASE_URL}?reset_token={token}"
                if send_reset_email(e, link): st.success("Reset link sent (also shown above if SMTP not set).")
        st.stop()
    if ok:
        e = normalize_email(email_in); db=load_users(); u=db["users"].get(e)
        if not u or not verify_password(pwd_in, u.get("password_hash","")):
            st.error("Invalid email or password."); st.session_state.login_attempts += 1
        elif u.get("status")!="active":
            st.error("Account not active.")
        else:
            st.session_state.authed=True; st.session_state.user_email=e; st.session_state.user_role=u.get("role","user")
            st.session_state.login_attempts=0; user_dir(e); st.rerun()
        if st.session_state.login_attempts>=5:
            st.session_state.lock_until = datetime.now()+timedelta(minutes=2)
            st.warning("Too many attempts. Locked for 2 minutes.")

def logout_button():
    with st.sidebar:
        st.markdown("---")
        st.caption(f"Signed in as: *{st.session_state.user_email}* ({st.session_state.user_role})")
        if st.button("Logout"):
            st.session_state.authed=False; st.session_state.user_email=None; st.session_state.user_role=None; st.rerun()

if not st.session_state.get("authed", False):
    login_view(); st.stop()
else:
    logout_button()

# -------------------- language pack (English + Arabic) --------------------
T = {
    "English": {
        "Language":"Language","Select Language":"Select Language","Plant Setup":"Plant Setup","Number of Stages":"Number of Stages",
        "Vessels / Membranes":"Vessels / Membranes","Vessels":"Vessels",'Membranes per vessel (8")':'Membranes per vessel (8")',
        "Plant Capacity":"Plant Capacity","Design Recovery %":"Design Recovery %",
        "Dashboard":"Dashboard","Daily Report":"Daily Report","Weekly Report":"Weekly Report","Monthly Report":"Monthly Report",
        "History & Exports":"History & Exports","RO Design":"RO Design","RO Design — Quick Sizing":"RO Design — Quick Sizing",
        "Daily Inputs":"Daily Inputs","Date":"Date","Operator (optional)":"Operator (optional)","Operator Notes":"Operator Notes",
        "Feed TDS (ppm)":"Feed TDS (ppm)","Product TDS (ppm)":"Product TDS (ppm)",
        "Feed Pressure IN (bar)":"Feed Pressure IN (bar)","Feed Pressure OUT (bar)":"Feed Pressure OUT (bar)",
        "Cartridge Filter Pressure (bar)":"Cartridge Filter Pressure (bar)",
        "HP Pump IN (bar)":"HP Pump IN (bar)","HP Pump OUT (bar)":"HP Pump OUT (bar)",
        "Feed Flow (LPM)":"Feed Flow (LPM)","Product Flow (LPM)":"Product Flow (LPM)",
        "Per-Vessel Output TDS (optional)":"Per-Vessel Output TDS (optional)",
        "Water Temperature (°C)":"Water Temperature (°C)","pH":"pH",
        "Alkalinity as CaCO₃ (mg/L)":"Alkalinity as CaCO₃ (mg/L)","Hardness as CaCO₃ (mg/L)":"Hardness as CaCO₃ (mg/L)",
        "SDI":"SDI","Turbidity (NTU)":"Turbidity (NTU)","TSS (mg/L)":"TSS (mg/L)","Free Chlorine (mg/L)":"Free Chlorine (mg/L)",
        "CO₂ (mg/L)":"CO₂ (mg/L)","Silica (mg/L)":"Silica (mg/L)","HP Pump Efficiency (%)":"HP Pump Efficiency (%)",
        "Calculate & Save":"Calculate & Save",
        "Recovery %":"Recovery %","Rejection %":"Rejection %","Pressure Recovery %":"Pressure Recovery %",
        "ΔP Cartridge (bar)":"ΔP Cartridge (bar)","ΔP Vessels (bar)":"ΔP Vessels (bar)","HP ΔP (bar)":"HP ΔP (bar)",
        "PQI (0–100)":"PQI (0–100)","NDP (bar)":"NDP (bar)","Salt Passage (%)":"Salt Passage (%)","NPF (LPM)":"NPF (LPM)",
        "Reject Flow (LPM) (calc)":"Reject Flow (LPM) (calc)","Mass Balance Error (%)":"Mass Balance Error (%)",
        "Flow balance OK (Feed ≈ Product + Reject)":"Flow balance OK (Feed ≈ Product + Reject)",
        "Flow mismatch: check meters/valves.":"Flow mismatch: check meters/valves.",
        "Daily Note":"Daily Note","Field":"Field","Value":"Value","Metric":"Metric",
        "Design summary":"Design summary","Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}":"Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}",
        "Inputs":"Inputs","Outputs / KPIs":"Outputs / KPIs","Stage & Vessel Snapshot":"Stage & Vessel Snapshot",
        "Vessel":"Vessel","Permeate TDS (ppm)":"Permeate TDS (ppm)","Rejection % (vessel)":"Rejection %",
        "Download Daily Excel":"Download Daily Excel","Download Daily PDF":"Download Daily PDF",
        "TDS Trend (last 30 days)":"TDS Trend (last 30 days)","Date (short)":"Date",
        "Avg Feed TDS":"Avg Feed TDS","Avg Product TDS":"Avg Product TDS","Avg Recovery":"Avg Recovery","Avg Rejection":"Avg Rejection",
        "Avg ΔP Cartridge":"Avg ΔP Cartridge","Avg ΔP Vessels":"Avg ΔP Vessels","Health Score":"Health Score",
        "No data yet.":"No data yet.","Page":"Page"
    },
    "Arabic": {
        "Language":"اللغة","Select Language":"اختر اللغة","Plant Setup":"إعداد المحطة","Number of Stages":"عدد المراحل",
        "Vessels / Membranes":"الأوعية / الأغشية","Vessels":"أوعية",'Membranes per vessel (8")':'أغشية لكل وعاء (8")',
        "Plant Capacity":"سعة المحطة","Design Recovery %":"نسبة الاسترجاع التصميمية",
        "Dashboard":"لوحة التحكم","Daily Report":"تقرير يومي","Weekly Report":"تقرير أسبوعي","Monthly Report":"تقرير شهري",
        "History & Exports":"السجل والتنزيلات","RO Design":"تصميم RO","RO Design — Quick Sizing":"تصميم RO — حساب سريع",
        "Daily Inputs":"مدخلات يومية","Date":"التاريخ","Operator (optional)":"المشغل (اختياري)","Operator Notes":"ملاحظات المشغل",
        "Feed TDS (ppm)":"TDS المغذي (ppm)","Product TDS (ppm)":"TDS المنتج (ppm)",
        "Feed Pressure IN (bar)":"ضغط دخول المغذي (بار)","Feed Pressure OUT (bar)":"ضغط خروج المغذي (بار)",
        "Cartridge Filter Pressure (bar)":"ضغط فلتر الخرطوشة (بار)","HP Pump IN (bar)":"دخول مضخة الضغط العالي (بار)","HP Pump OUT (بار)":"خروج مضخة الضغط العالي (بار)",
        "Feed Flow (LPM)":"تدفق المغذي (ل/د)","Product Flow (LPM)":"تدفق المنتج (ل/د)",
        "Per-Vessel Output TDS (optional)":"TDS لكل وعاء (اختياري)","Water Temperature (°C)":"درجة حرارة الماء (°م)","pH":"الرقم الهيدروجيني",
        "Alkalinity as CaCO₃ (mg/L)":"القلوية كـ CaCO₃ (ملغم/ل)","Hardness as CaCO₃ (mg/L)":"الصلابة كـ CaCO₃ (ملغم/ل)",
        "SDI":"SDI","Turbidity (NTU)":"العكارة (NTU)","TSS (mg/L)":"TSS (ملغم/ل)","Free Chlorine (mg/L)":"الكلور الحر (ملغم/ل)",
        "CO₂ (mg/L)":"ثاني أكسيد الكربون (ملغم/ل)","Silica (mg/L)":"السيليكا (ملغم/ل)","HP Pump Efficiency (%)":"كفاءة مضخة الضغط العالي (%)",
        "Calculate & Save":"احسب واحفظ",
        "Recovery %":"نسبة الاسترجاع %","Rejection %":"نسبة الرفض %","Pressure Recovery %":"استرجاع الضغط %",
        "ΔP Cartridge (bar)":"فرق الضغط عبر الخرطوشة (بار)","ΔP Vessels (bar)":"فرق الضغط عبر الأوعية (بار)","HP ΔP (bar)":"فرق ضغط المضخة العالية (بار)",
        "PQI (0–100)":"مؤشر جودة النفاذ (0–100)","NDP (bar)":"الضغط الدافع الصافي (بار)","Salt Passage (%)":"مرور الأملاح (%)","NPF (LPM)":"التدفق المنظَّم (ل/د)",
        "Reject Flow (LPM) (calc)":"تدفق الرفض (ل/د) (حساب)","Mass Balance Error (%)":"خطأ الاتزان الكتلي (%)",
        "Flow balance OK (Feed ≈ Product + Reject)":"توازن التدفق جيد (المغذي ≈ المنتج + الرفض)","Flow mismatch: check meters/valves.":"اختلال التدفق: افحص العدادات/الصمامات.",
        "Daily Note":"ملاحظة يومية","Field":"الحقل","Value":"القيمة","Metric":"المؤشر",
        "Design summary":"ملخص التصميم","Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}":"التصميم: {breakup} • الأوعية: {tot_v} • الأغشية: {tot_m}",
        "Inputs":"المدخلات","Outputs / KPIs":"المخرجات / المؤشرات","Stage & Vessel Snapshot":"ملخص المراحل والأوعية",
        "Vessel":"وعاء","Permeate TDS (ppm)":"TDS النفاذ (ppm)","Rejection % (vessel)":"نسبة الرفض",
        "Download Daily Excel":"تنزيل إكسل اليومي","Download Daily PDF":"تنزيل PDF اليومي",
        "TDS Trend (last 30 days)":"اتجاه TDS (آخر 30 يومًا)","Date (short)":"التاريخ",
        "Avg Feed TDS":"متوسط TDS المغذي","Avg Product TDS":"متوسط TDS المنتج","Avg Recovery":"متوسط الاسترجاع","Avg Rejection":"متوسط الرفض",
        "Avg ΔP Cartridge":"متوسط ΔP الخرطوشة","Avg ΔP Vessels":"متوسط ΔP الأوعية","Health Score":"مؤشر الصحة",
        "No data yet.":"لا توجد بيانات بعد.","Page":"الصفحة"
    }
}
def tr(s, lang): return T.get(lang, {}).get(s, s)
def tr_fmt(key, lang, **kw):
    s = tr(key, lang)
    try: return s.format(**kw)
    except Exception: return s
def _(s: str) -> str: return tr(s, st.session_state.get("lang","English"))
def _fmt(key: str, **kw): return tr_fmt(key, st.session_state.get("lang","English"), **kw)

# -------------------- sidebar --------------------
with st.sidebar:
    st.header("🌐 " + tr("Language", "English"))
    lang = st.selectbox(tr("Select Language", "English"), ["English","Arabic"], index=0)

with st.sidebar:
    st.header("⚙ " + tr("Plant Setup", lang))
    num_stages = st.number_input(tr("Number of Stages", lang), 1, 10, 3, 1)

with st.sidebar:
    st.subheader("🧱 " + tr("Vessels / Membranes", lang))
    default_vessels = [8,4,2] + [1]*max(num_stages-3,0)
    vessels_per_stage=[]
    for s in range(num_stages):
        vessels_per_stage.append(st.number_input(f"Stage {s+1} • {tr('Vessels', lang)}", 1, 500,
                                                 default_vessels[s] if s<len(default_vessels) else 1, 1))
    membranes_per_vessel = st.number_input(tr('Membranes per vessel (8")', lang), 1, 8, 6, 1)

def m3d_to_lpm(m3d): return (m3d*1000.0)/1440.0

with st.sidebar:
    st.subheader("📊 " + tr("Plant Capacity", lang))
    plant_capacity = st.number_input(tr("Plant Capacity", lang) + " (m³/day)", 10, 20000, 500, 10)
    design_rec    = st.slider(tr("Design Recovery %", lang), 40, 85, 70)
    d_feed = m3d_to_lpm(plant_capacity)
    d_prod = round(d_feed*(design_rec/100.0), 1)
    d_rej  = max(round(d_feed - d_prod, 1), 0.0)
    st.caption(_fmt("Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}",
                    breakup=" | ".join([f"S{i+1}:{v}" for i,v in enumerate(vessels_per_stage)]),
                    tot_v=int(sum(vessels_per_stage)),
                    tot_m=int(sum(vessels_per_stage))*int(membranes_per_vessel)))
    page_mode = st.radio(tr("Page", lang), [tr("Dashboard", lang), tr("Daily Report", lang), tr("Weekly Report", lang),
                                            tr("Monthly Report", lang), tr("History & Exports", lang), tr("RO Design", lang)], index=0)

# persist
st.session_state["lang"]=lang; st.session_state["page_mode"]=page_mode
st.session_state["num_stages"]=num_stages; st.session_state["vessels_per_stage"]=vessels_per_stage
st.session_state["membranes_per_vessel"]=membranes_per_vessel
st.session_state["design_rec"]=design_rec; st.session_state["plant_capacity"]=plant_capacity

# -------------------- paths --------------------
def plant_key(capacity_m3d: int) -> str:
    return f"{capacity_m3d}m3d_{st.session_state['num_stages']}stages"
def user_csv_path(email: str, capacity_m3d: int) -> Path:
    d = user_dir(email); return d / f"daily_{plant_key(capacity_m3d)}.csv"
def user_reports_dir(email: str, kind: str) -> Path:
    return user_dir(email) / REPORTS_DIRNAME / kind
def csv_path_for_current():
    return user_csv_path(st.session_state.user_email, int(st.session_state["plant_capacity"]))

# -------------------- KPI helpers --------------------
def safe_div(a,b): b=1e-9 if (b in (None,0)) else b; a=0.0 if a is None else a; return a/b
def kpi_recovery_pct(product_lpm, feed_lpm): return max(0.0, min(100.0, safe_div(product_lpm, feed_lpm)*100.0))
def kpi_rejection_pct(prod_tds, feed_tds):
    if prod_tds is None or feed_tds in (None,0): return None
    return max(0.0, min(100.0, (1.0 - (prod_tds/max(feed_tds,1e-6)))*100.0))
def pressure_recovery_pct(hp_in_bar, hp_out_bar):
    if hp_out_bar in (None,0): return None
    rise = max(hp_out_bar - hp_in_bar, 0.0)
    return max(0.0, min(100.0, safe_div(rise, hp_out_bar)*100.0))
def kpi_delta_p(out_bar, in_bar):
    if out_bar is None or in_bar is None: return None
    return max(0.0, float(out_bar)-float(in_bar))
def temperature_correction_factor(temp_c): return max(0.6, min(1.6, 1.0 + 0.03*(temp_c-25.0)))
def osmotic_pressure_approx(tds_mgL, temp_c): T=temp_c+273.15; return 0.0008*max(tds_mgL,0.0)*(T/298.0)
def net_driving_pressure_bar(hp_out_bar, feed_out_bar, feed_tds, prod_tds, temp_c):
    deltaP=max(hp_out_bar - feed_out_bar, 0.0)
    return max(deltaP - (osmotic_pressure_approx(feed_tds,temp_c) - osmotic_pressure_approx(prod_tds,temp_c)), 0.0)
def specific_energy_kwh_m3(hp_out_bar, feed_flow_lpm, efficiency_pct, product_flow_lpm):
    Q_ls=max(feed_flow_lpm,0.0)/60.0; eta=max(efficiency_pct/100.0,0.01)
    kW=(hp_out_bar*Q_ls)/(36.0*eta); prod_m3_h=(product_flow_lpm*60)/1000.0
    return kW / max(prod_m3_h,1e-6)
def permeate_quality_index(product_tds, target_tds=50.0):
    if product_tds is None: return None
    return max(0.0, 100.0 - min(100.0, (product_tds/max(target_tds,1e-6))*100.0))
def normalized_permeate_flow(permeate_flow_lpm, tcf): return safe_div(permeate_flow_lpm, tcf)

DEFAULT_LIMITS = {
    "product_tds_max": 60.0, "cartridge_dp_max": 0.7, "vessel_dp_max": 1.5,
    "rejection_min": 60.0, "recovery_target": 70.0, "recovery_high_margin": 3.0
}

def maintenance_note_from_row(row, limits=DEFAULT_LIMITS):
    tips=[]
    if (row.get("rejection_pct") or 100) < limits["rejection_min"]:
        tips.append("Rejection below target → inspect for fouling/bypass; plan alkaline+acid CIP.")
    if (row.get("product_tds") or 0) > limits["product_tds_max"]:
        tips.append("Product TDS high → check integrity (O-rings, interconnects), tighten concentrate valve.")
    if (row.get("cartridge_dp") or 0) > limits["cartridge_dp_max"]:
        tips.append("Cartridge ΔP high → replace cartridge / check clogging upstream.")
    if (row.get("vessel_dp") or 0) > limits["vessel_dp_max"]:
        tips.append("Vessel ΔP high → channeling/scaling risk; verify brine flow & antiscalant.")
    if not row.get("feed_vs_sum_ok", True):
        tips.append("Flow imbalance noted → verify flowmeters & throttling set-points.")
    if not tips:
        tips.append("Inputs vs outputs look healthy today. Keep PM on schedule (cartridge & CIP planning).")
    return " ".join(tips)

# -------------------- header --------------------
st.title(f"{BRAND} • RO Dashboard")
st.markdown(f'<span class="lee-badge">User: {st.session_state.user_email}</span>', unsafe_allow_html=True)
brk = " | ".join([f"S{i+1}:{v}" for i,v in enumerate(st.session_state["vessels_per_stage"])])
tot_v = int(sum(st.session_state["vessels_per_stage"]))
tot_m = int(tot_v * st.session_state["membranes_per_vessel"])
st.caption(_fmt("Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}", breakup=brk, tot_v=tot_v, tot_m=tot_m))

# ---------- DASHBOARD QUICK KPIs ----------
if st.session_state["page_mode"] == tr("Dashboard", st.session_state["lang"]):
    path = csv_path_for_current()
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    if path.exists():
        df = pd.read_csv(path)
        if not df.empty:
            last = df.iloc[-1]
            with c1: st.metric(_("Recovery %"), f"{last.get('recovery_pct',0):.1f}")
            with c2: st.metric(_("Rejection %"), f"{last.get('rejection_pct',0):.1f}")
            with c3: st.metric(_("Pressure Recovery %"), f"{last.get('pressure_recovery_pct',0):.1f}")
            with c4: st.metric(_("ΔP Cartridge (bar)"), f"{last.get('cartridge_dp',0):.2f}")
            with c5: st.metric(_("ΔP Vessels (bar)"), f"{last.get('vessel_dp',0):.2f}")
            pqi = permeate_quality_index(last.get("product_tds",0))
            with c6: st.metric(_("PQI (0–100)"), f"{(pqi or 0):.0f}/100")
        else:
            c1.write(_("No data yet."))
    else:
        c1.write(_("No data yet."))

# ---------- DAILY REPORT ----------
if st.session_state["page_mode"] == tr("Daily Report", st.session_state["lang"]):
    st.markdown("### 🗓 " + _("Daily Inputs"))

    colA,colB,colC = st.columns(3)
    with colA:
        report_date = st.date_input(_("Date"), value=date.today())
        operator = st.text_input(_("Operator (optional)"), "")
        feed_tds = st.number_input(_("Feed TDS (ppm)"), 1.0, 200000.0, 120.0, 1.0)
        product_tds = st.number_input(_("Product TDS (ppm)"), 0.1, 200000.0, 45.0, 0.1)
    with colB:
        feed_p_in  = st.number_input(_("Feed Pressure IN (bar)"), 0.0, 100.0, 1.2, 0.1)
        feed_p_out = st.number_input(_("Feed Pressure OUT (bar)"),0.0, 100.0, 1.0, 0.1)
        cartridge_p = st.number_input(_("Cartridge Filter Pressure (bar)"), 0.0, 100.0, 1.7, 0.1)
        hp_in  = st.number_input(_("HP Pump IN (bar)"), 0.0, 200.0, 2.0, 0.1)
        hp_out = st.number_input(_("HP Pump OUT (bar)"),0.0, 200.0, 12.0, 0.1)
    with colC:
        design_feed = (st.session_state["plant_capacity"]*1000.0/1440.0)
        design_prod = round(design_feed*(st.session_state["design_rec"]/100.0), 1)
        feed_flow   = st.number_input(_("Feed Flow (LPM)"),    1.0, 200000.0, float(design_feed), 1.0)
        product_flow= st.number_input(_("Product Flow (LPM)"), 0.1, 200000.0, float(design_prod), 0.1)
        notes_free  = st.text_area(_("Operator Notes"), "")

    # per-vessel readings (optional). We compute stage averages automatically.
    per_vessel_rows=[]
    with st.expander(_("Per-Vessel Output TDS (optional)")):
        for s_idx, vessels in enumerate(st.session_state["vessels_per_stage"], start=1):
            st.caption(f"Stage {s_idx} — {vessels} vessel(s)")
            cols = st.columns(min(6, max(1, vessels)))
            for v in range(1, vessels+1):
                col = cols[(v-1)%len(cols)]
                with col:
                    val = st.number_input(f"S{s_idx} V{v} " + _("Permeate TDS (ppm)"), 0.1, 200000.0,
                                          float(product_tds), 0.1, key=f"s{s_idx}_v{v}")
                per_vessel_rows.append({"Stage": s_idx, "Vessel": v, "Permeate TDS (ppm)": float(val)})

    # advanced water/operation
    with st.expander("Advanced"):
        col1,col2,col3 = st.columns(3)
        with col1:
            temp_c = st.number_input(_("Water Temperature (°C)"), 1.0, 50.0, 25.0, 0.5)
            ph = st.number_input(_("pH"), 1.0, 14.0, 7.2, 0.1)
            alkalinity_mgL = st.number_input(_("Alkalinity as CaCO₃ (mg/L)"), 0.0, 1000.0, 120.0, 1.0)
            hardness_mgL   = st.number_input(_("Hardness as CaCO₃ (mg/L)"), 0.0, 3000.0, 200.0, 1.0)
        with col2:
            sdi = st.number_input(_("SDI"), 0.0, 10.0, 3.0, 0.1)
            turbidity_ntu = st.number_input(_("Turbidity (NTU)"), 0.0, 1000.0, 0.5, 0.1)
            tss_mgL = st.number_input(_("TSS (mg/L)"), 0.0, 5000.0, 5.0, 0.5)
            free_chlorine_mgL = st.number_input(_("Free Chlorine (mg/L)"), 0.0, 10.0, 0.0, 0.1)
        with col3:
            co2_mgL = st.number_input(_("CO₂ (mg/L)"), 0.0, 100.0, 5.0, 0.5)
            silica_mgL = st.number_input(_("Silica (mg/L)"), 0.0, 200.0, 10.0, 0.5)
            pump_efficiency = st.number_input(_("HP Pump Efficiency (%)"), 30.0, 90.0, 75.0, 1.0)

    # ==== Compute & Save ====
    if st.button(_("Calculate & Save")):
        # Reject flow (auto) + mass balance
        reject_flow = max(feed_flow - product_flow, 0.0)
        mass_balance_err = ((product_flow + reject_flow) - feed_flow) / max(feed_flow,1e-6) * 100.0

        # Core KPIs
        recovery_pct  = kpi_recovery_pct(product_flow, feed_flow)
        rejection_pct = kpi_rejection_pct(product_tds, feed_tds)
        cartridge_dp  = kpi_delta_p(cartridge_p, feed_p_out)
        vessel_dp     = kpi_delta_p(hp_out, feed_p_out)
        hp_dp         = kpi_delta_p(hp_out, hp_in)
        press_rec_pct = pressure_recovery_pct(hp_in, hp_out)

        # Stage averages from per-vessel (if provided)
        stage_avg = {}
        if len(per_vessel_rows) > 0:
            for s in range(1, st.session_state["num_stages"]+1):
                vals = [r["Permeate TDS (ppm)"] for r in per_vessel_rows if r["Stage"]==s]
                if vals:
                    avg_tds = float(np.mean(vals))
                    up_tds = feed_tds if s==1 else stage_avg.get(s-1, {}).get("avg_tds", feed_tds)
                    rej = kpi_rejection_pct(avg_tds, up_tds)
                    stage_avg[s] = {"avg_tds": avg_tds, "rejection_pct": rej}
                else:
                    stage_avg[s] = {"avg_tds": None, "rejection_pct": None}

        # Per-vessel DataFrame with rejection % (vs upstream stage)
        COL_PERM = _("Permeate TDS (ppm)")
        COL_REJ  = _("Rejection % (vessel)")
        per_vessel_df = pd.DataFrame(columns=["Stage","Vessel", COL_PERM, COL_REJ])
        if per_vessel_rows:
            rows=[]
            for r in per_vessel_rows:
                s = r["Stage"]
                upstream_tds = feed_tds if s==1 else (stage_avg.get(s-1, {}).get("avg_tds") or feed_tds)
                rej = kpi_rejection_pct(r["Permeate TDS (ppm)"], upstream_tds)
                rows.append({"Stage": s, "Vessel": r["Vessel"], COL_PERM: r["Permeate TDS (ppm)"], COL_REJ: rej})
            per_vessel_df = pd.DataFrame(rows).sort_values(["Stage","Vessel"]).reset_index(drop=True)

        # More KPIs
        tcf = temperature_correction_factor(temp_c)
        ndp = net_driving_pressure_bar(hp_out, feed_p_out, feed_tds, product_tds, temp_c)
        salt_passage_pct = 100.0 - (rejection_pct or 0.0)
        spec_energy = specific_energy_kwh_m3(hp_out, feed_flow, pump_efficiency, product_flow)
        daily_kwh = spec_energy * (product_flow*60/1000.0)*24
        feed_match = abs((product_flow + reject_flow) - feed_flow) <= max(2.0, 0.02*feed_flow)
        pqi = permeate_quality_index(product_tds, target_tds=50.0)
        npf = normalized_permeate_flow(product_flow, tcf)

        # collect row
        path = csv_path_for_current()
        row = {
            "date": report_date.strftime("%Y-%m-%d"),
            "user": st.session_state.user_email, "operator": operator,
            "capacity_m3d": int(st.session_state["plant_capacity"]),
            "design_recovery": float(st.session_state["design_rec"]),
            "stage_count": int(st.session_state["num_stages"]),
            "vessels_per_stage": json.dumps(st.session_state["vessels_per_stage"]),
            "membranes_per_vessel": int(st.session_state["membranes_per_vessel"]),
            # inputs
            "feed_tds": float(feed_tds), "product_tds": float(product_tds),
            "feed_p_in": float(feed_p_in), "feed_p_out": float(feed_p_out),
            "cartridge_p": float(cartridge_p), "hp_in": float(hp_in), "hp_out": float(hp_out),
            "feed_flow_lpm": float(feed_flow), "product_flow_lpm": float(product_flow),
            "reject_flow_lpm": float(reject_flow),
            # KPIs
            "recovery_pct": float(recovery_pct),
            "rejection_pct": float(rejection_pct) if rejection_pct is not None else None,
            "pressure_recovery_pct": float(press_rec_pct) if press_rec_pct is not None else None,
            "cartridge_dp": float(cartridge_dp) if cartridge_dp is not None else None,
            "vessel_dp": float(vessel_dp) if vessel_dp is not None else None,
            "hp_dp": float(hp_dp) if hp_dp is not None else None,
            "mass_balance_err_pct": float(mass_balance_err),
            "feed_vs_sum_ok": bool(feed_match), "notes": notes_free,
            "temp_c": float(temp_c), "ph": float(ph), "alkalinity_mgL": float(alkalinity_mgL), "hardness_mgL": float(hardness_mgL),
            "sdi": float(sdi), "turbidity_ntu": float(turbidity_ntu), "tss_mgL": float(tss_mgL), "free_chlorine_mgL": float(free_chlorine_mgL),
            "co2_mgL": float(co2_mgL), "silica_mgL": float(silica_mgL),
            "pump_efficiency_pct": float(pump_efficiency),
            "tcf": float(tcf), "ndp_bar": float(ndp), "salt_passage_pct": float(salt_passage_pct),
            "specific_energy_kwh_m3": float(spec_energy), "daily_kwh": float(daily_kwh),
            "pqi": float(pqi) if pqi is not None else None, "npf_lpm": float(npf)
        }
        for i in range(1, st.session_state["num_stages"]+1):
            st_avg = stage_avg.get(i, {})
            row[f"stage_{i}_avg_tds"]=float(st_avg.get("avg_tds")) if st_avg.get("avg_tds") is not None else None
            rj = st_avg.get("rejection_pct")
            row[f"stage_{i}_rejection_pct"]=float(rj) if rj is not None else None

        row["maintenance_note"] = maintenance_note_from_row(row)

        # save / merge
        df_new=pd.DataFrame([row])
        if path.exists():
            df_old=pd.read_csv(path); df_old["date"]=df_old["date"].astype(str)
            df_all=pd.concat([df_old[df_old["date"]!=row["date"]], df_new], ignore_index=True).sort_values("date")
        else:
            df_all=df_new
        df_all.to_csv(path, index=False)
        st.success(f"Saved to {path.name}")

        # KPI cards
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        with c1: st.metric(_("Recovery %"), f"{row['recovery_pct']:.1f}")
        with c2: st.metric(_("Rejection %"), f"{(row['rejection_pct'] or 0):.1f}")
        with c3: st.metric(_("Pressure Recovery %"), f"{(row['pressure_recovery_pct'] or 0):.1f}")
        with c4: st.metric(_("ΔP Cartridge (bar)"), f"{(row['cartridge_dp'] or 0):.2f}")
        with c5: st.metric(_("ΔP Vessels (bar)"), f"{(row['vessel_dp'] or 0):.2f}")
        with c6: st.metric(_("HP ΔP (bar)"), f"{(row['hp_dp'] or 0):.2f}")

        a1,a2,a3,a4,a5,a6 = st.columns(6)
        with a1: st.metric(_("Reject Flow (LPM) (calc)"), f"{row['reject_flow_lpm']:.1f}")
        with a2: st.metric(_("Mass Balance Error (%)"), f"{row['mass_balance_err_pct']:.2f}")
        with a3: st.metric(_("PQI (0–100)"), f"{(row['pqi'] or 0):.0f}")
        with a4: st.metric(_("NPF (LPM)"), f"{row['npf_lpm']:.1f}")
        with a5: st.metric(_("NDP (bar)"), f"{row['ndp_bar']:.2f}")
        with a6: st.metric(_("Salt Passage (%)"), f"{row['salt_passage_pct']:.2f}")

        # Maintenance & balance
        st.markdown(f"<div class='warn'><b>{_('Daily Note')}:</b> {row['maintenance_note']}</div>", unsafe_allow_html=True)
        if row["feed_vs_sum_ok"]:
            st.markdown("<div class='good'>" + _("Flow balance OK (Feed ≈ Product + Reject)") + "</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='bad'>" + _("Flow mismatch: check meters/valves.") + "</div>", unsafe_allow_html=True)

        # Per-vessel table on screen (with rejection %)
        if not per_vessel_df.empty:
            st.markdown("#### " + _("Stage & Vessel Snapshot"))
            st.dataframe(per_vessel_df, use_container_width=True, height=260)
        else:
            st.caption("No per-vessel readings provided.")

        # Exports (Excel/PDF) + Weekly/Monthly/History/Design -> in PART 2/2
        # ================== LeeWave RO Reporter — Professional (FINAL, PART 2/2) ==================
# Continues from PART 1 after:  # (Exports implemented in PART 2/2)

# ---------- EXPORT HELPERS ----------
def _ensure_per_vessel_df(pv_df: pd.DataFrame) -> pd.DataFrame:
    """Return a safe per-vessel dataframe with proper localized column headers."""
    if pv_df is None or pv_df.empty:
        return pd.DataFrame(columns=["Stage", "Vessel", _("Permeate TDS (ppm)"), _("Rejection % (vessel)")])
    # Standardize column names if user has old CSVs
    rename_map = {}
    for col in pv_df.columns:
        if str(col).lower().strip() in ["permeate tds (ppm)", "permeate_tds", "tds"]:
            rename_map[col] = _("Permeate TDS (ppm)")
        if str(col).lower().strip() in ["rejection %", "rejection_pct", "rejection", "rej %"]:
            rename_map[col] = _("Rejection % (vessel)")
    pv_df = pv_df.rename(columns=rename_map)
    # Make sure required cols exist
    for c in ["Stage", "Vessel", _("Permeate TDS (ppm)"), _("Rejection % (vessel)")]:
        if c not in pv_df.columns:
            pv_df[c] = np.nan
    # Sort nicely
    try:
        pv_df = pv_df.sort_values(["Stage", "Vessel"]).reset_index(drop=True)
    except Exception:
        pass
    return pv_df

def _stage_snapshot_table_data(row: dict, pv_df: pd.DataFrame, stage_count: int):
    """Build a compact table for PDF with stage avgs + first 12 vessel lines."""
    # Stage averages
    tbl=[[_("Metric"), _("Value"), "", "", "", "", ""]]
    for i in range(1, stage_count+1):
        avg_tds = row.get(f"stage_{i}_avg_tds")
        rej     = row.get(f"stage_{i}_rejection_pct")
        tbl.append([f"Stage {i} avg TDS", f"{(avg_tds if avg_tds is not None else 0):.1f}",
                    f"Stage {i} Rej %", f"{(rej if rej is not None else 0):.1f}", "", "", ""])
    # Per-vessel compact (up to 12)
    tbl.append(["", "", "", "", "", "", ""])
    tbl.append([_("Vessel"), _("Permeate TDS (ppm)"), _("Rejection % (vessel)"),
                _("Vessel"), _("Permeate TDS (ppm)"), _("Rejection % (vessel)"), ""])
    max_print = min(12, len(pv_df))
    for i in range(0, max_print, 2):
        r1 = pv_df.iloc[i]
        if i+1 < max_print:
            r2 = pv_df.iloc[i+1]
            tbl.append([f"S{int(r1['Stage'])} V{int(r1['Vessel'])}",
                        f"{float(r1[_('Permeate TDS (ppm)')]):.1f}",
                        f"{float(r1[_('Rejection % (vessel)')] or 0):.1f}",
                        f"S{int(r2['Stage'])} V{int(r2['Vessel'])}",
                        f"{float(r2[_('Permeate TDS (ppm)')]):.1f}",
                        f"{float(r2[_('Rejection % (vessel)')] or 0):.1f}",
                        ""])
        else:
            tbl.append([f"S{int(r1['Stage'])} V{int(r1['Vessel'])}",
                        f"{float(r1[_('Permeate TDS (ppm)')]):.1f}",
                        f"{float(r1[_('Rejection % (vessel)')] or 0):.1f}",
                        "", "", "", ""])
    return tbl

# ---------- EXCEL & PDF EXPORTS (called right after Calculate & Save in PART 1) ----------
if st.session_state.get("page_mode") == tr("Daily Report", st.session_state["lang"]) and 'row' in locals():
    # Make sure per_vessel_df is safe & localized
    per_vessel_df = _ensure_per_vessel_df(per_vessel_df)

    # -------- Excel ----------
    if XLSX_OK:
        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine="xlsxwriter") as writer:
            wb = writer.book
            # styles
            h = wb.add_format({"bold": True, "bg_color": "#F0F4FF", "border": 1})
            sub = wb.add_format({"italic": True, "font_color": "#666"})
            okfmt = wb.add_format({"bg_color": "#E8F5E9"})
            badfmt = wb.add_format({"bg_color": "#FFEBEE"})
            title = wb.add_format({"bold": True, "font_size": 14})

            # Summary sheet
            ws = wb.add_worksheet("Summary")
            breakup = " | ".join([f"S{i+1}:{v}" for i,v in enumerate(st.session_state['vessels_per_stage'])])
            tot_v = int(sum(st.session_state['vessels_per_stage']))
            tot_m = int(tot_v*st.session_state['membranes_per_vessel'])
            ws.write("A1", f"{BRAND} — " + _("Daily Report"), title)
            ws.write("A2", f"{_('Plant Capacity')}: {int(st.session_state['plant_capacity'])} m³/d | {row['date']}", sub)
            ws.write("A3", _fmt("Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}", breakup=breakup, tot_v=tot_v, tot_m=tot_m), sub)

            inputs = [
                [_("Feed TDS (ppm)"), row["feed_tds"]],
                [_("Product TDS (ppm)"), row["product_tds"]],
                [_("Feed Pressure IN (bar)"), row["feed_p_in"]],
                [_("Feed Pressure OUT (bar)"), row["feed_p_out"]],
                [_("Cartridge Filter Pressure (bar)"), row["cartridge_p"]],
                [_("HP Pump IN (bar)"), row["hp_in"]],
                [_("HP Pump OUT (bar)"), row["hp_out"]],
                [_("Feed Flow (LPM)"), row["feed_flow_lpm"]],
                [_("Product Flow (LPM)"), row["product_flow_lpm"]],
                [_("Reject Flow (LPM) (calc)"), row["reject_flow_lpm"]],
                [_("Water Temperature (°C)"), row["temp_c"]],
                [_("pH"), row["ph"]],
                [_("SDI"), row["sdi"]],
            ]
            ws.add_table(4,0,4+len(inputs),1,
                         {"data":inputs,"columns":[{"header":("Field")},{"header":("Value")}],
                          "style":"Table Style Light 9"})

            out = [
                [_("Recovery %"), row["recovery_pct"]],
                [_("Rejection %"), row.get("rejection_pct") or 0.0],
                [_("Pressure Recovery %"), row.get("pressure_recovery_pct") or 0.0],
                [_("Salt Passage (%)"), row["salt_passage_pct"]],
                [_("ΔP Cartridge (bar)"), row.get("cartridge_dp") or 0.0],
                [_("ΔP Vessels (bar)"), row.get("vessel_dp") or 0.0],
                [_("HP ΔP (bar)"), row.get("hp_dp") or 0.0],
                [_("NDP (bar)"), row["ndp_bar"]],
                [_("NPF (LPM)"), row["npf_lpm"]],
                [_("PQI (0–100)"), row.get("pqi") or 0.0],
                [_("Specific Energy (kWh/m³)"), row["specific_energy_kwh_m3"]],
                [_("Energy Today (kWh)"), row["daily_kwh"]],
                [_("Mass Balance Error (%)"), row["mass_balance_err_pct"]],
                [_("Flow balance OK (Feed ≈ Product + Reject)"), "Yes" if row.get("feed_vs_sum_ok") else "No"],
            ]
            ws.add_table(4,4,4+len(out),5,
                         {"data":out,"columns":[{"header":("Metric")},{"header":("Value")}],
                          "style":"Table Style Light 9"})
            ws.write("A20", _("Daily Note"), h); ws.write("A21", row["maintenance_note"])
            # Conditional YES/NO coloring
            ws.conditional_format(5,5,4+len(out),5,{"type":"text","criteria":"containing","value":"Yes","format":okfmt})
            ws.conditional_format(5,5,4+len(out),5,{"type":"text","criteria":"containing","value":"No","format":badfmt})

            # Per-vessel sheet
            pv_df = per_vessel_df.copy()
            pv_df.to_excel(writer, index=False, sheet_name="Per_Vessel")
            ws2 = writer.sheets["Per_Vessel"]
            ws2.set_column(0, len(pv_df.columns)-1, 18)
            # Conditional format on Rejection% column (localized name)
            rej_col_name = _("Rejection % (vessel)")
            if rej_col_name in pv_df.columns:
                rej_idx = list(pv_df.columns).index(rej_col_name)
                ws2.conditional_format(1, rej_idx, len(pv_df)+1, rej_idx,
                                       {"type":"cell","criteria":"<","value":60,"format":badfmt})

            # Stage averages sheet
            stage_rows=[]
            for i in range(1, st.session_state["num_stages"]+1):
                stage_rows.append({
                    "Stage": i,
                    "Avg TDS (ppm)": row.get(f"stage_{i}_avg_tds"),
                    "Stage Rejection (%)": row.get(f"stage_{i}_rejection_pct"),
                })
            pd.DataFrame(stage_rows).to_excel(writer, index=False, sheet_name="Stage_Avg")

            # 30d trend
            recent = df_all.tail(30).copy()
            if not recent.empty:
                recent["date"] = pd.to_datetime(recent["date"])
                recent = recent[["date","feed_tds","product_tds","recovery_pct","rejection_pct","cartridge_dp","vessel_dp"]]
                recent.to_excel(writer, index=False, sheet_name="Recent_30d")
                ws3 = writer.sheets["Recent_30d"]
                ws3.set_column(0, 0, 12); ws3.set_column(1, len(recent.columns)-1, 16)
                ch = wb.add_chart({"type":"line"})
                ch.add_series({"name":"Feed TDS","categories":["Recent_30d",1,0,len(recent),0],
                               "values":["Recent_30d",1,1,len(recent),1]})
                ch.add_series({"name":"Product TDS","categories":["Recent_30d",1,0,len(recent),0],
                               "values":["Recent_30d",1,2,len(recent),2]})
                ch.set_title({"name":("TDS Trend (last 30 days)")}); ch.set_x_axis({"name":("Date (short)")}); ch.set_y_axis({"name":"ppm"})
                ws3.insert_chart("H3", ch, {"x_scale":1.2,"y_scale":1.0})

        fn_x=f"daily_{int(st.session_state['plant_capacity'])}m3d_{int(st.session_state['num_stages'])}stages_{row['date']}.xlsx"
        st.download_button(_("Download Daily Excel"), excel_buf.getvalue(), file_name=fn_x,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        (user_reports_dir(st.session_state.user_email,"daily")/fn_x).write_bytes(excel_buf.getvalue())

    # -------- PDF ----------
    if REPORTLAB_OK:
        pdf=io.BytesIO()
        doc=SimpleDocTemplate(pdf, pagesize=A4, leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=28)
        styles=getSampleStyleSheet(); title_s=styles["Title"]; normal=styles["Normal"]
        elements=[]
        breakup=" | ".join([f"S{i+1}:{v}" for i,v in enumerate(st.session_state['vessels_per_stage'])])
        tot_v = int(sum(st.session_state['vessels_per_stage'])); tot_m = int(tot_v*st.session_state['membranes_per_vessel'])

        elements.append(Paragraph(f"<b>{BRAND} — " + _("Daily Report") + "</b>", title_s))
        elements.append(Paragraph(f"{_('Plant Capacity')}: {int(st.session_state['plant_capacity'])} m³/day • {row['date']}", normal))
        elements.append(Paragraph(_fmt("Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}", breakup=breakup, tot_v=tot_v, tot_m=tot_m), normal))
        elements.append(Spacer(1,8))

        inputs_tbl=[[("Field"),("Value")],
                    [("Feed TDS (ppm)"), f"{row['feed_tds']:.0f}"],[("Product TDS (ppm)"), f"{row['product_tds']:.0f}"],
                    [("Feed Pressure IN (bar)"), f"{row['feed_p_in']:.2f}"],[("Feed Pressure OUT (bar)"), f"{row['feed_p_out']:.2f}"],
                    [_("Cartridge Filter Pressure (bar)"), f"{row['cartridge_p']:.2f}"],
                    [("HP Pump IN (bar)"), f"{row['hp_in']:.2f}"],[("HP Pump OUT (bar)"), f"{row['hp_out']:.2f}"],
                    [("Feed Flow (LPM)"), f"{row['feed_flow_lpm']:.1f}"],[("Product Flow (LPM)"), f"{row['product_flow_lpm']:.1f}"],
                    [_("Reject Flow (LPM) (calc)"), f"{row['reject_flow_lpm']:.1f}"],
                    [("Water Temperature (°C)"), f"{row['temp_c']:.1f}"],[("pH"), f"{row['ph']:.1f}"],[_("SDI"), f"{row['sdi']:.1f}"]]
        t_in=Table(inputs_tbl, colWidths=[180, 120])
        t_in.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0), colors.HexColor("#EEF4FF")),
                                  ('BOX',(0,0),(-1,-1),0.6,colors.black),('INNERGRID',(0,0),(-1,-1),0.25,colors.grey),
                                  ('ALIGN',(0,0),(-1,-1),'CENTER')]))
        elements.append(Paragraph("<b>"+_("Inputs")+"</b>", normal)); elements.append(t_in); elements.append(Spacer(1,8))

        out_tbl=[[("Metric"),("Value"),("Metric"),("Value")],
                 [_("Recovery %"), f"{row['recovery_pct']:.1f}", _("Rejection %"), f"{(row.get('rejection_pct') or 0):.1f}"],
                 [_("Pressure Recovery %"), f"{(row.get('pressure_recovery_pct') or 0):.1f}", _("Salt Passage (%)"), f"{row['salt_passage_pct']:.2f}"],
                 [_("ΔP Cartridge (bar)"), f"{(row.get('cartridge_dp') or 0):.2f}", _("ΔP Vessels (bar)"), f"{(row.get('vessel_dp') or 0):.2f}"],
                 [_("HP ΔP (bar)"), f"{(row.get('hp_dp') or 0):.2f}", _("NDP (bar)"), f"{row['ndp_bar']:.2f}"],
                 [_("NPF (LPM)"), f"{row['npf_lpm']:.1f}", _("Specific Energy (kWh/m³)"), f"{row['specific_energy_kwh_m3']:.2f}"],
                 [_("Energy Today (kWh)"), f"{row['daily_kwh']:.0f}", _("Mass Balance Error (%)"), f"{row['mass_balance_err_pct']:.2f}"]]
        t_out=Table(out_tbl, colWidths=[150,80,150,80])
        t_out.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0), colors.HexColor("#EEF4FF")),
                                   ('BOX',(0,0),(-1,-1),0.6,colors.black),('INNERGRID',(0,0),(-1,-1),0.25,colors.grey),
                                   ('ALIGN',(0,0),(-1,-1),'CENTER')]))
        elements.append(Paragraph("<b>"+_("Outputs / KPIs")+"</b>", normal)); elements.append(t_out); elements.append(Spacer(1,8))

        # Stage & per-vessel snapshot
        pv_df = _ensure_per_vessel_df(per_vessel_df)
        tbl = _stage_snapshot_table_data(row, pv_df, int(st.session_state["num_stages"]))
        t_st=Table(tbl, colWidths=[90,80,70,90,80,70,10])
        t_st.setStyle(TableStyle([('BOX',(0,0),(-1,-1),0.6,colors.black),('INNERGRID',(0,0),(-1,-1),0.25,colors.grey),('ALIGN',(0,0),(-1,-1),'CENTER')]))
        elements.append(Paragraph("<b>"+_("Stage & Vessel Snapshot")+"</b>", normal)); elements.append(t_st); elements.append(Spacer(1,6))

        elements.append(Paragraph(f"<b>{_('Daily Note')}:</b> {row['maintenance_note']}", normal))
        doc.build(elements)
        fn_p=f"daily_{int(st.session_state['plant_capacity'])}m3d_{int(st.session_state['num_stages'])}stages_{row['date']}.pdf"
        st.download_button(_("Download Daily PDF"), pdf.getvalue(), file_name=fn_p, mime="application/pdf")
        (user_reports_dir(st.session_state.user_email,"daily")/fn_p).write_bytes(pdf.getvalue())

# ---------- FORECAST UTILS ----------
def linear_forecast_next(values: list, horizon_days: int = 30):
    if len(values)<2: return [values[-1]]*horizon_days if values else [0.0]*horizon_days
    x=np.arange(len(values)); y=np.array(values, float)
    try:
        m,b=np.polyfit(x,y,1); xf=np.arange(len(values), len(values)+horizon_days)
        return (m*xf+b).tolist()
    except Exception:
        return [values[-1]]*horizon_days

def next_crossing_day(series_future, threshold, above=True):
    for i,v in enumerate(series_future):
        if (above and v>threshold) or ((not above) and v<threshold): return i
    return None

# ---------- WEEKLY ----------
if st.session_state["page_mode"] == tr("Weekly Report", st.session_state["lang"]):
    st.markdown("### 📅 " + _("Weekly Report"))
    start_date = st.date_input(_("Date"), value=date.today()-timedelta(days=6))
    path = csv_path_for_current()
    if not path.exists():
        st.warning(_("No data yet."))
    else:
        df=pd.read_csv(path); df["date"]=pd.to_datetime(df["date"]).dt.date
        df_week = df[(df["date"]>=start_date) & (df["date"]<=start_date+timedelta(days=6))].sort_values("date")
        if df_week.empty:
            st.warning(_("No data yet."))
        else:
            try:
                last_conf = df_week.dropna(subset=["vessels_per_stage"]).iloc[-1]
                vps=json.loads(last_conf["vessels_per_stage"]); mpv=int(last_conf.get("membranes_per_vessel",6))
                tot_v=int(sum(vps)); tot_m=int(tot_v*mpv); brk=" | ".join([f"S{i+1}:{v}" for i,v in enumerate(vps)])
                st.info(_fmt("Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}", breakup=brk, tot_v=tot_v, tot_m=tot_m))
            except Exception:
                pass
            st.dataframe(df_week, use_container_width=True)
            def avg(col): return float(df_week[col].dropna().astype(float).mean()) if col in df_week else None
            c1,c2,c3,c4,c5,c6=st.columns(6)
            c1.metric(_("Avg Feed TDS"), f"{(avg('feed_tds') or 0):.0f} ppm")
            c2.metric(_("Avg Product TDS"), f"{(avg('product_tds') or 0):.0f} ppm")
            c3.metric(_("Avg Recovery"), f"{(avg('recovery_pct') or 0):.1f} %")
            c4.metric(_("Avg Rejection"), f"{(avg('rejection_pct') or 0):.1f} %")
            c5.metric(_("Avg ΔP Cartridge"), f"{(avg('cartridge_dp') or 0):.2f} bar")
            c6.metric(_("Avg ΔP Vessels"), f"{(avg('vessel_dp') or 0):.2f} bar")

            # Quick predictions
            df_for=df_week.copy()
            checks = [
                ("product_tds", _("Product TDS (ppm)"), DEFAULT_LIMITS["product_tds_max"], True),
                ("cartridge_dp", _("ΔP Cartridge (bar)"), DEFAULT_LIMITS["cartridge_dp_max"], True),
                ("vessel_dp", _("ΔP Vessels (bar)"), DEFAULT_LIMITS["vessel_dp_max"], True),
                ("recovery_pct", _("Recovery %"), DEFAULT_LIMITS["recovery_target"]+DEFAULT_LIMITS["recovery_high_margin"], True),
            ]
            for col,label,thr,above in checks:
                if col in df_for and df_for[col].notna().any():
                    vals=df_for[col].astype(float).tolist(); forecast=linear_forecast_next(vals,30); cross=next_crossing_day(forecast,thr,above)
                    if cross is None: st.info(f"{label}: safe for next 30 days.")
                    else:
                        due=(date.today()+timedelta(days=cross)).strftime("%Y-%m-%d")
                        st.warning(f"{label}: may cross {thr} in ~{cross} days → due: {due}")

# ---------- MONTHLY ----------
if st.session_state["page_mode"] == tr("Monthly Report", st.session_state["lang"]):
    st.markdown("### 📅 " + _("Monthly Report"))
    month_input = st.date_input(_("Date"), value=date.today())
    month_str = f"{month_input.year}-{str(month_input.month).zfill(2)}"
    path = csv_path_for_current()
    if not path.exists():
        st.warning(_("No data yet."))
    else:
        df=pd.read_csv(path); df["date"]=pd.to_datetime(df["date"]).dt.date
        df_month = df[(df["date"].apply(lambda d: d.strftime("%Y-%m"))==month_str)].sort_values("date")
        if df_month.empty:
            st.warning(_("No data yet."))
        else:
            try:
                last_conf=df_month.dropna(subset=["vessels_per_stage"]).iloc[-1]
                vps=json.loads(last_conf["vessels_per_stage"]); mpv=int(last_conf.get("membranes_per_vessel",6))
                tot_v=int(sum(vps)); tot_m=int(tot_v*mpv); brk=" | ".join([f"S{i+1}:{v}" for i,v in enumerate(vps)])
                st.info(_fmt("Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}", breakup=brk, tot_v=tot_v, tot_m=tot_m))
            except Exception:
                pass
            st.dataframe(df_month, use_container_width=True)
            # Monthly energy total
            monthly_kwh = float(df_month.get('daily_kwh', pd.Series([]))).sum()
            st.caption(f"{_('Energy Today (kWh)') if 'Energy Today (kWh)' in T['English'] else 'Monthly energy'} ≈ {monthly_kwh:.0f} kWh")
            # Simple health score
            score=100
            if "product_tds" in df_month: score -= min(15, 3*len(df_month[df_month["product_tds"]>DEFAULT_LIMITS["product_tds_max"]]))
            if "rejection_pct" in df_month: score -= min(15, 2*len(df_month[df_month["rejection_pct"]<DEFAULT_LIMITS["rejection_min"]]))
            score=max(0,min(100,score))
            st.metric(_("Health Score"), f"{score}/100")

# ---------- HISTORY & EXPORTS ----------
if st.session_state["page_mode"] == tr("History & Exports", st.session_state["lang"]):
    st.markdown("### 📚 " + _("History & Exports"))
    path = csv_path_for_current()
    if not path.exists():
        st.info(_("No data yet."))
    else:
        df = pd.read_csv(path); df["date"]=pd.to_datetime(df["date"]).dt.date
        c1,c2,c3 = st.columns(3)
        date_from = c1.date_input(_("Date") + " (from)", value=df["date"].min())
        date_to   = c2.date_input(_("Date") + " (to)",   value=df["date"].max())
        tds_thr   = c3.number_input(_("Product TDS (ppm)") + " >", 0.0, 1e6, 0.0, 1.0)
        mask = (df["date"]>=date_from) & (df["date"]<=date_to)
        if tds_thr>0: mask &= (df["product_tds"]>tds_thr)
        out = df[mask].sort_values("date")
        st.dataframe(out, use_container_width=True); st.caption(f"{len(out)} rows")
        if XLSX_OK and not out.empty:
            excel_buf=io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine="xlsxwriter") as writer:
                out.to_excel(writer, index=False, sheet_name="Filtered")
            st.download_button(_("Download Daily Excel"), excel_buf.getvalue(),
                               file_name=f"history_{date_from}to{date_to}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------- RO DESIGN (Quick Sizing) ----------
if st.session_state["page_mode"] == tr("RO Design", st.session_state["lang"]):
    st.markdown("### 🧮 " + _("RO Design — Quick Sizing"))
    cap_m3d = st.number_input(_("Plant Capacity") + " (m³/day)", 10, 50000, int(st.session_state["plant_capacity"]), 10)
    recovery_target = st.slider(_("Design Recovery %"), 40, 85, int(st.session_state["design_rec"]))
    prod_m3h = cap_m3d/24.0; per_elem_m3h = 1.2
    need_elements = int(np.ceil(prod_m3h / per_elem_m3h))
    per_vessel_elems = st.number_input(tr('Membranes per vessel (8")', st.session_state["lang"]), 1, 8, int(st.session_state["membranes_per_vessel"]), 1)
    need_vessels = int(np.ceil(need_elements / per_vessel_elems))
    stages = st.slider(_("Number of Stages"), 1, 6, int(st.session_state["num_stages"]))
    split=[]; rem=need_vessels
    for i in range(stages):
        v=int(np.ceil(rem/(stages-i))); split.append(v); rem-=v
    st.write(f"Suggested vessels per stage: {split} (total vessels: {sum(split)}, total membranes: {sum(split)*per_vessel_elems})")
    st.caption("Quick estimate — refine with feed TDS, temperature, and design constraints.")