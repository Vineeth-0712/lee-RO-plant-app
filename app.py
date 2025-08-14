# No electrical inputs. Focused on plant health, quality, hydraulics & maintenance.

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

# Exports
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

try:
    import xlsxwriter  # noqa
    XLSX_OK = True
except Exception:
    XLSX_OK = False

# -------------------- app meta & theme --------------------
BRAND = "LeeWave"
PRIMARY_HEX = "#0B7285"   # teal
ACCENT_HEX  = "#E3FAFC"   # light teal bg

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
      .muted{{color:#666}}
    </style>
    """,
    unsafe_allow_html=True
)

# -------------------- ENV (reset links) --------------------
SECRET_KEY   = os.environ.get("SECRET_KEY", "dev-change-me-please")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8501")
SMTP_HOST    = os.environ.get("SMTP_HOST", "")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER    = os.environ.get("SMTP_USER", "")
SMTP_PASS    = os.environ.get("SMTP_PASS", "")
MAIL_FROM    = os.environ.get("MAIL_FROM", "no-reply@leewave.app")
ts = URLSafeTimedSerializer(SECRET_KEY)

# -------------------- Password helpers --------------------
def _hash_bcrypt(pw: str) -> str: return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
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
def hash_password(pw: str) -> str: return _hash_bcrypt(pw) if BCRYPT_OK else _hash_pbkdf2(pw)
def verify_password(pw: str, hashed: str) -> bool:
    if hashed.startswith("pbkdf2$"): return _verify_pbkdf2(pw, hashed)
    return _verify_bcrypt(pw, hashed) if BCRYPT_OK else False

# -------------------- Users DB --------------------
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

def add_capacity_request(email: str, requested_extra: int = 10, reason: str = ""):
    db = load_users()
    db["requests"].append({
        "email": normalize_email(email),
        "requested_extra": int(requested_extra),
        "reason": reason.strip(),
        "status": "pending",
        "ts": datetime.now().isoformat(timespec="seconds"),
    })
    save_users(db)

# -------------------- Email helper --------------------
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

# -------------------- Session & Auth --------------------
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

# -------------------- Language pack --------------------
T = {
    "English": {
        "Language":"Language","Select Language":"Select Language","Plant Setup":"Plant Setup","Number of Stages":"Number of Stages",
        "Vessels / Membranes":"Vessels / Membranes","Vessels":"Vessels",'Membranes per vessel (8")':'Membranes per vessel (8")',
        "Plant Capacity":"Plant Capacity","Design Recovery %":"Design Recovery %",
        "Dashboard":"Dashboard","Daily Report":"Daily Report","Weekly Report":"Weekly Report","Monthly Report":"Monthly Report",
        "History & Exports":"History & Exports","RO Design":"RO Design",
        "Request more capacity slots":"Request more capacity slots","How many more slots?":"How many more slots?",
        "Reason (optional)":"Reason (optional)","Send request":"Send request",
        "Capacity slots: {used}/{quota} used":"Capacity slots: {used}/{quota} used",
        "Added capacity {cap} m³/day • {used}/{quota} used.":"Added capacity {cap} m³/day • {used}/{quota} used.",
        "Using existing capacity {cap} m³/day (does not count).":"Using existing capacity {cap} m³/day (does not count).",
        "Limit reached ({used}/{quota}). Request more capacity slots.":"Limit reached ({used}/{quota}). Request more capacity slots.",
        "Admin Panel":"Admin Panel","Users":"Users","Approve User":"Approve User","Disable User":"Disable User","Reset Password":"Reset Password",
        "Requests":"Requests","Approve":"Approve","Reject":"Reject","No pending requests.":"No pending requests."
    },
    "Arabic": {
        "Language":"اللغة","Select Language":"اختر اللغة","Plant Setup":"إعداد المحطة","Number of Stages":"عدد المراحل",
        "Vessels / Membranes":"الأوعية / الأغشية","Vessels":"أوعية",'Membranes per vessel (8")':'أغشية لكل وعاء (8")',
        "Plant Capacity":"سعة المحطة","Design Recovery %":"نسبة الاسترجاع التصميمية",
        "Dashboard":"لوحة التحكم","Daily Report":"تقرير يومي","Weekly Report":"تقرير أسبوعي","Monthly Report":"تقرير شهري",
        "History & Exports":"السجل والتنزيلات","RO Design":"تصميم RO",
        "Request more capacity slots":"طلب زيادة عدد السعات","How many more slots?":"كم عدد السعات؟",
        "Reason (optional)":"السبب (اختياري)","Send request":"إرسال الطلب",
        "Capacity slots: {used}/{quota} used":"خانات السعة: {used}/{quota} مستخدمة",
        "Added capacity {cap} m³/day • {used}/{quota} used.":"تمت إضافة سعة {cap} م³/يوم • {used}/{quota} مستخدمة.",
        "Using existing capacity {cap} m³/day (does not count).":"سعة سابقة {cap} م³/يوم (لا تُحتسب).",
        "Limit reached ({used}/{quota}). Request more capacity slots.":"تم بلوغ الحد ({used}/{quota}). اطلب المزيد.",
        "Admin Panel":"لوحة المشرف","Users":"المستخدمون","Approve User":"اعتماد المستخدم","Disable User":"تعطيل المستخدم","Reset Password":"إعادة تعيين كلمة المرور",
        "Requests":"الطلبات","Approve":"موافقة","Reject":"رفض","No pending requests.":"لا توجد طلبات معلقة."
    },
    "Malayalam": {
        "Language":"ഭാഷ","Select Language":"ഭാഷ തിരഞ്ഞെടുക്കുക","Plant Setup":"പ്ലാന്റ് ക്രമീകരണം","Number of Stages":"സ്റ്റേജ് എണ്ണം",
        "Vessels / Membranes":"വെസൽസ് / മെംബ്രെയ്ൻസ്","Vessels":"വെസൽസ്",'Membranes per vessel (8")':'ഓരോ വെസലിലും മെംബ്രെയ്ൻസ് (8")',
        "Plant Capacity":"പ്ലാന്റ് ശേഷി","Design Recovery %":"ഡിസൈൻ റിക്കവറി %",
        "Dashboard":"ഡാഷ്ബോർഡ്","Daily Report":"ഡെയ്‌ലി റിപ്പോർട്ട്","Weekly Report":"വീക്ലി റിപ്പോർട്ട്","Monthly Report":"മന്ത്‌ലി റിപ്പോർട്ട്",
        "History & Exports":"ഹിസ്റ്ററി/ഡൗൺലോഡ്സ്","RO Design":"RO ഡിസൈൻ",
        "Request more capacity slots":"കൂടുതൽ കപ്പാസിറ്റി സ്ലോട്ടുകൾ","How many more slots?":"എത്ര സ്ലോട്ടുകൾ വേണം?",
        "Reason (optional)":"കാരണം (ഐച്ഛികം)","Send request":"റിക്വസ്റ്റ് അയയ്‌ക്കുക",
        "Capacity slots: {used}/{quota} used":"കപ്പാസിറ്റി സ്ലോട്ടുകൾ: {used}/{quota} ഉപയോഗിച്ചു",
        "Added capacity {cap} m³/day • {used}/{quota} used.":"{cap} m³/day ചേർത്തു • {used}/{quota} ഉപയോഗിച്ചു.",
        "Using existing capacity {cap} m³/day (does not count).":"മുമ്പ് ഉപയോഗിച്ചത് {cap} m³/day (കൗണ്ട് ഇല്ല).",
        "Limit reached ({used}/{quota}). Request more capacity slots.":"പരിധി തീർന്നു ({used}/{quota}). കൂടുതൽ സ്ലോട്ടുകൾ ആവശ്യപ്പെടൂ.",
        "Admin Panel":"അഡ്മിൻ പാനൽ","Users":"ഉപയോക്താക്കൾ","Approve User":"അംഗീകരിക്കുക","Disable User":"ഡിസ്‌ബിൾ","Reset Password":"പാസ്‌വേഡ് റീസെറ്റ്",
        "Requests":"റിക്വസ്റ്റ്","Approve":"അംഗീകരിക്കുക","Reject":"നിരസിക്കുക","No pending requests.":"പെൻഡിംഗ് ഒന്നുമില്ല."
    },
    "Hindi": {
        "Language":"भाषा","Select Language":"भाषा चुनें","Plant Setup":"प्लांट सेटअप","Number of Stages":"स्टेज की संख्या",
        "Vessels / Membranes":"वेसल्स / मेंब्रेन","Vessels":"वेसल्स",'Membranes per vessel (8")':'प्रति वेसल मेंब्रेन (8")',
        "Plant Capacity":"प्लांट क्षमता","Design Recovery %":"डिज़ाइन रिकवरी %",
        "Dashboard":"डैशबोर्ड","Daily Report":"डेली रिपोर्ट","Weekly Report":"वीकली रिपोर्ट","Monthly Report":"मंथली रिपोर्ट",
        "History & Exports":"इतिहास/डाउनलोड","RO Design":"RO डिज़ाइन",
        "Request more capacity slots":"अधिक क्षमता स्लॉट","How many more slots?":"कितने और स्लॉट?",
        "Reason (optional)":"कारण (वैकल्पिक)","Send request":"अनुरोध भेजें",
        "Capacity slots: {used}/{quota} used":"क्षमता स्लॉट: {used}/{quota} उपयोग",
        "Added capacity {cap} m³/day • {used}/{quota} used.":"क्षमता {cap} m³/day जोड़ी गई • {used}/{quota} उपयोग।",
        "Using existing capacity {cap} m³/day (does not count).":"पहले से वही क्षमता (काउंट नहीं)।",
        "Limit reached ({used}/{quota}). Request more capacity slots.":"सीमा पूरी ({used}/{quota}). अधिक स्लॉट माँगें।",
        "Admin Panel":"एडमिन पैनल","Users":"यूज़र्स","Approve User":"स्वीकृत करें","Disable User":"निष्क्रिय करें","Reset Password":"पासवर्ड रीसेट",
        "Requests":"अनुरोध","Approve":"स्वीकृत","Reject":"अस्वीकृत","No pending requests.":"कोई लंबित अनुरोध नहीं।"
    }
}
def tr(s, lang): return T.get(lang, {}).get(s, s)
def tr_fmt(key, lang, **kw):
    s = tr(key, lang)
    try: return s.format(**kw)
    except Exception: return s

# -------------------- Sidebar --------------------
with st.sidebar:
    st.header("🌐 " + tr("Language", "English"))
    lang = st.selectbox(tr("Select Language", "English"), list(T.keys()), index=0)

with st.sidebar:
    st.header("⚙ " + tr("Plant Setup", lang))
    num_stages = st.number_input(tr("Number of Stages", lang), 1, 10, 3, 1)

with st.sidebar:
    st.subheader("🧱 " + tr("Vessels / Membranes", lang))
    default_vessels = [8,4,2] + [1]*max(num_stages-3,0)
    vessels_per_stage=[]
    for s in range(num_stages):
        vessels_per_stage.append(st.number_input(f"Stage {s+1} • {tr('Vessels', lang)}", 1, 500, default_vessels[s] if s<len(default_vessels) else 1, 1))
    membranes_per_vessel = st.number_input(tr('Membranes per vessel (8")', lang), 1, 8, 6, 1)

def m3d_to_lpm(m3d): return (m3d*1000.0)/1440.0

with st.sidebar:
    st.subheader("📊 " + tr("Plant Capacity", lang))
    plant_capacity = st.number_input(tr("Plant Capacity", lang) + " (m³/day)", 10, 20000, 500, 10)
    design_rec    = st.slider(tr("Design Recovery %", lang), 40, 85, 70)
    d_feed = m3d_to_lpm(plant_capacity); d_prod = round(d_feed*(design_rec/100.0), 1); d_rej = max(round(d_feed - d_prod, 1), 0.0)
    st.caption(f"Design @ {design_rec}% → Product ~ {d_prod} LPM, Feed ~ {d_feed:.1f} LPM, Reject ~ {d_rej} LPM")
    page_mode = st.radio("Page", [tr("Dashboard", lang), tr("Daily Report", lang), tr("Weekly Report", lang), tr("Monthly Report", lang), tr("History & Exports", lang), tr("RO Design", lang)], index=0)

# persist for reuse
st.session_state["lang"]=lang; st.session_state["page_mode"]=page_mode
st.session_state["num_stages"]=num_stages; st.session_state["vessels_per_stage"]=vessels_per_stage
st.session_state["membranes_per_vessel"]=membranes_per_vessel
st.session_state["design_rec"]=design_rec; st.session_state["plant_capacity"]=plant_capacity

# -------------------- Paths --------------------
def plant_key(capacity_m3d: int) -> str: return f"{capacity_m3d}m3d_{st.session_state['num_stages']}stages"
def user_csv_path(email: str, capacity_m3d: int) -> Path: return user_dir(email) / f"daily_{plant_key(capacity_m3d)}.csv"
def user_reports_dir(email: str, kind: str) -> Path: return user_dir(email) / REPORTS_DIRNAME / kind
def csv_path_for_current(): return user_csv_path(st.session_state.user_email, int(st.session_state["plant_capacity"]))

# -------------------- KPI helpers & maintenance --------------------
def safe_div(a,b): b=1e-9 if (b in (None,0)) else b; a=0.0 if a is None else a; return a/b
def kpi_recovery_pct(product_lpm, feed_lpm): return max(0.0, min(100.0, safe_div(product_lpm, feed_lpm)*100.0))
def kpi_rejection_pct(prod_tds, upstream_tds):
    if prod_tds is None or upstream_tds in (None,0): return None
    return max(0.0, min(100.0, (1.0 - (prod_tds/max(upstream_tds,1e-6)))*100.0))
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

DEFAULT_LIMITS = {"product_tds_max": 60.0, "cartridge_dp_max": 0.7, "vessel_dp_max": 1.5,
                  "rejection_min": 60.0, "recovery_target": 70.0, "recovery_high_margin": 3.0}

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

# -------------------- Header --------------------
st.title(f"{BRAND} • RO Dashboard")
st.markdown(f'<span class="lee-badge">User: {st.session_state.user_email}</span>', unsafe_allow_html=True)
cap = int(st.session_state["plant_capacity"])
brk = " | ".join([f"S{i+1}:{v}" for i,v in enumerate(st.session_state["vessels_per_stage"])])
tot_v = int(sum(st.session_state["vessels_per_stage"]))
tot_m = int(tot_v * st.session_state["membranes_per_vessel"])
st.caption(f"Design: {brk} • Vessels: {tot_v} • Membranes: {tot_m} • Capacity: {cap} m³/day")
# ---------- DASHBOARD QUICK KPIs ----------
if st.session_state["page_mode"] == tr("Dashboard", st.session_state["lang"]):
    path = csv_path_for_current()
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    if path.exists():
        df = pd.read_csv(path)
        if not df.empty:
            last = df.iloc[-1]
            c1.metric("Recovery %", f"{last.get('recovery_pct',0):.1f}")
            c2.metric("Rejection %", f"{last.get('rejection_pct',0):.1f}")
            c3.metric("Product TDS (ppm)", f"{last.get('product_tds',0):.0f}")
            c4.metric("ΔP Cartridge (bar)", f"{last.get('cartridge_dp',0):.2f}")
            c5.metric("ΔP Vessels (bar)", f"{last.get('vessel_dp',0):.2f}")
            pqi = permeate_quality_index(last.get("product_tds",0)); c6.metric("PQI", f"{(pqi or 0):.0f}/100")
        else:
            c1.write("No data yet.")
    else:
        c1.write("No data yet.")

# ---------- DAILY REPORT ----------
if st.session_state["page_mode"] == tr("Daily Report", st.session_state["lang"]):
    st.markdown("### 🗓 Daily Inputs")

    colA,colB,colC = st.columns(3)
    with colA:
        report_date = st.date_input("Date", value=date.today())
        operator = st.text_input("Operator (optional)", "")
        feed_tds = st.number_input("Feed TDS (ppm)", 1.0, 200000.0, 120.0, 1.0)
        product_tds = st.number_input("Product TDS (ppm)", 0.1, 200000.0, 45.0, 0.1)
    with colB:
        feed_p_in  = st.number_input("Feed Pressure IN (bar)", 0.0, 100.0, 1.2, 0.1)
        feed_p_out = st.number_input("Feed Pressure OUT (bar)",0.0, 100.0, 1.0, 0.1)
        cartridge_p = st.number_input("Cartridge Filter Pressure (bar)", 0.0, 100.0, 1.7, 0.1)
        hp_in  = st.number_input("HP Pump IN (bar)", 0.0, 200.0, 2.0, 0.1)
        hp_out = st.number_input("HP Pump OUT (bar)",0.0, 200.0, 12.0, 0.1)
    with colC:
        d_feed = (st.session_state["plant_capacity"]*1000.0/1440.0)
        d_prod = round(d_feed*(st.session_state["design_rec"]/100.0), 1)
        feed_flow   = st.number_input("Feed Flow (LPM)",    1.0, 200000.0, float(d_feed), 1.0)
        product_flow= st.number_input("Product Flow (LPM)", 0.1, 200000.0, float(d_prod), 0.1)
        notes_free  = st.text_area("Operator Notes", "")

    # Per-vessel permeate TDS (optional)
    per_vessel_rows=[]
    with st.expander("Per-Vessel Output TDS (optional)"):
        for s_idx, vessels in enumerate(st.session_state["vessels_per_stage"], start=1):
            st.caption(f"Stage {s_idx} — {vessels} vessel(s)")
            cols = st.columns(min(6, vessels))
            for v in range(1, vessels+1):
                col = cols[(v-1)%len(cols)]
                with col:
                    val = st.number_input(f"S{s_idx} V{v} permeate TDS", 0.1, 200000.0, float(product_tds if s_idx==st.session_state["num_stages"] else product_tds*1.2), 0.1, key=f"s{s_idx}_v{v}")
                per_vessel_rows.append({"Stage": s_idx, "Vessel": v, "Permeate TDS (ppm)": float(val)})

    # Advanced water/operation (optional)
    with st.expander("Advanced Water & Operation Inputs (optional)"):
        col1,col2,col3 = st.columns(3)
        with col1:
            temp_c = st.number_input("Water Temperature (°C)", 1.0, 50.0, 25.0, 0.5)
            ph = st.number_input("pH", 1.0, 14.0, 7.2, 0.1)
            alkalinity_mgL = st.number_input("Alkalinity as CaCO₃ (mg/L)", 0.0, 1000.0, 120.0, 1.0)
            hardness_mgL   = st.number_input("Hardness as CaCO₃ (mg/L)", 0.0, 3000.0, 200.0, 1.0)
        with col2:
            sdi = st.number_input("SDI", 0.0, 10.0, 3.0, 0.1)
            turbidity_ntu = st.number_input("Turbidity (NTU)", 0.0, 1000.0, 0.5, 0.1)
            tss_mgL = st.number_input("TSS (mg/L)", 0.0, 5000.0, 5.0, 0.5)
            free_chlorine_mgL = st.number_input("Free Chlorine (mg/L)", 0.0, 10.0, 0.0, 0.1)
        with col3:
            co2_mgL = st.number_input("CO₂ (mg/L)", 0.0, 100.0, 5.0, 0.5)
            silica_mgL = st.number_input("Silica (mg/L)", 0.0, 200.0, 10.0, 0.5)
            pump_efficiency = st.number_input("HP Pump Efficiency (%)", 30.0, 90.0, 75.0, 1.0)

    if st.button("Calculate & Save"):
        # Hydraulics
        reject_flow = max(feed_flow - product_flow, 0.0)

        # Core KPIs
        recovery_pct  = kpi_recovery_pct(product_flow, feed_flow)
        rejection_pct = kpi_rejection_pct(product_tds, feed_tds)
        cartridge_dp  = kpi_delta_p(cartridge_p, feed_p_out)
        vessel_dp     = kpi_delta_p(hp_out, feed_p_out)
        hp_dp         = kpi_delta_p(hp_out, hp_in)

        # Build per-vessel DF + stage averages + per-vessel rejection
        per_vessel_df = None
        stage_avgs = []        # [(stage, avg_tds, stage_rej_pct)]
        if per_vessel_rows:
            # Calculate stage averages first pass (only permeate TDS)
            stage_groups = {}
            for r in per_vessel_rows:
                stage_groups.setdefault(r["Stage"], []).append(r["Permeate TDS (ppm)"])
            # compute rejections using upstream: S1 vs feed_tds; S(n) vs previous stage avg
            prev_stage_avg = None
            rows_out=[]
            for s in range(1, st.session_state["num_stages"]+1):
                vals = stage_groups.get(s, [])
                avg_tds = float(np.mean(vals)) if vals else None
                upstream = feed_tds if s==1 else (prev_stage_avg if prev_stage_avg is not None else feed_tds)
                stage_rej = kpi_rejection_pct(avg_tds, upstream) if avg_tds is not None else None
                stage_avgs.append((s, avg_tds, stage_rej))
                prev_stage_avg = avg_tds if avg_tds is not None else prev_stage_avg
                # per-vessel rows with rejection %
                if vals:
                    for v_idx, val in enumerate(vals, start=1):
                        rej = kpi_rejection_pct(val, upstream)
                        rows_out.append({"Stage": s, "Vessel": v_idx, "Permeate TDS (ppm)": float(val), "Rejection %": rej})
            if 'rows_out' in locals() and rows_out:
                per_vessel_df = pd.DataFrame(rows_out)

        # More KPIs
        tcf = temperature_correction_factor(temp_c)
        ndp = net_driving_pressure_bar(hp_out, feed_p_out, feed_tds, product_tds, temp_c)
        salt_passage_pct = 100.0 - (rejection_pct or 0.0)
        spec_energy = specific_energy_kwh_m3(hp_out, feed_flow, pump_efficiency, product_flow)
        daily_kwh = spec_energy * (product_flow*60/1000.0)*24
        total_flow_check = product_flow + reject_flow
        feed_match = abs(total_flow_check - feed_flow) <= max(2.0, 0.02*feed_flow)
        pqi = permeate_quality_index(product_tds, target_tds=50.0)
        npf = normalized_permeate_flow(product_flow, tcf)

        # Collect row
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
            "cartridge_dp": float(cartridge_dp) if cartridge_dp is not None else None,
            "vessel_dp": float(vessel_dp) if vessel_dp is not None else None,
            "hp_dp": float(hp_dp) if hp_dp is not None else None,
            "feed_vs_sum_ok": bool(feed_match), "notes": notes_free,
            "temp_c": float(temp_c), "ph": float(ph), "alkalinity_mgL": float(alkalinity_mgL), "hardness_mgL": float(hardness_mgL),
            "sdi": float(sdi), "turbidity_ntu": float(turbidity_ntu), "tss_mgL": float(tss_mgL), "free_chlorine_mgL": float(free_chlorine_mgL),
            "co2_mgL": float(co2_mgL), "silica_mgL": float(silica_mgL),
            "pump_efficiency_pct": float(pump_efficiency),
            "tcf": float(tcf), "ndp_bar": float(ndp), "salt_passage_pct": float(salt_passage_pct),
            "specific_energy_kwh_m3": float(spec_energy), "daily_kwh": float(daily_kwh),
            "pqi": float(pqi) if pqi is not None else None, "npf_lpm": float(npf)
        }

        # Save / merge
        df_new=pd.DataFrame([row])
        if path.exists():
            df_old=pd.read_csv(path); df_old["date"]=df_old["date"].astype(str)
            df_all=pd.concat([df_old[df_old["date"]!=row["date"]], df_new], ignore_index=True).sort_values("date")
        else:
            df_all=df_new
        df_all.to_csv(path, index=False)
        st.success(f"Saved to {path.name}")

        # KPI cards (richer)
        k1,k2,k3,k4 = st.columns(4)
        k1.metric("Recovery %", f"{row['recovery_pct']:.1f}")
        k2.metric("Rejection %", f"{(row['rejection_pct'] or 0):.1f}")
        k3.metric("PQI (0–100)", f"{(row['pqi'] or 0):.0f}")
        k4.metric("Salt Passage (%)", f"{row['salt_passage_pct']:.2f}")

        h1,h2,h3,h4 = st.columns(4)
        h1.metric("Feed Flow (LPM)", f"{row['feed_flow_lpm']:.1f}")
        h2.metric("Product Flow (LPM)", f"{row['product_flow_lpm']:.1f}")
        h3.metric("Reject Flow (LPM)", f"{row['reject_flow_lpm']:.1f}")
        h4.metric("NDP (bar)", f"{row['ndp_bar']:.2f}")

        p1,p2,p3 = st.columns(3)
        p1.metric("ΔP Cartridge (bar)", f"{(row['cartridge_dp'] or 0):.2f}")
        p2.metric("ΔP Vessels (bar)", f"{(row['vessel_dp'] or 0):.2f}")
        p3.metric("HP ΔP (bar)", f"{(row['hp_dp'] or 0):.2f}")

        e1,e2 = st.columns(2)
        e1.metric("NPF (LPM)", f"{row['npf_lpm']:.1f}")
        e2.metric("Specific Energy (kWh/m³)", f"{row['specific_energy_kwh_m3']:.2f}")

        # Maintenance note
        row["maintenance_note"] = maintenance_note_from_row(row)
        st.markdown(f"<div class='warn'><b>Daily Note:</b> {row['maintenance_note']}</div>", unsafe_allow_html=True)
        if row["feed_vs_sum_ok"]:
            st.markdown("<div class='good'>Flow balance OK (Feed ≈ Product + Reject)</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='bad'>Flow mismatch: check meters/valves.</div>", unsafe_allow_html=True)

        # Per-vessel table
        if per_vessel_df is not None and not per_vessel_df.empty:
            st.subheader("Per-Vessel Performance")
            st.dataframe(per_vessel_df.style.format({"Permeate TDS (ppm)":"{:.1f}","Rejection %":"{:.1f}"}),
                         use_container_width=True)
            # Stage summary from averages
            stage_rows = []
            for s, avg_tds, stage_rej in stage_avgs:
                stage_rows.append({"Stage": f"S{s}", "Avg Permeate TDS (ppm)": avg_tds if avg_tds is not None else "",
                                   "Stage Rejection %": stage_rej if stage_rej is not None else ""})
            if stage_rows:
                st.caption("Stage Summary (from per-vessel averages)")
                st.dataframe(pd.DataFrame(stage_rows), use_container_width=True)

        # Design summary
        tot_v = int(sum(st.session_state['vessels_per_stage']))
        tot_m = int(tot_v*st.session_state['membranes_per_vessel'])
        breakup=" | ".join([f"S{i+1}:{v}" for i,v in enumerate(st.session_state['vessels_per_stage'])])
        st.info(f"Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}")

        # ---------- EXCEL EXPORT ----------
        if XLSX_OK:
            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine="xlsxwriter") as writer:
                wb = writer.book
                h = wb.add_format({"bold": True, "bg_color": "#F0F4FF", "border": 1})
                sub = wb.add_format({"italic": True, "font_color": "#666"})
                badfmt = wb.add_format({"bg_color": "#FFEBEE"})
                title = wb.add_format({"bold": True, "font_size": 14})

                ws = wb.add_worksheet("Summary")
                ws.write("A1", f"{BRAND} — Daily RO Report", title)
                ws.write("A2", f"Plant {int(st.session_state['plant_capacity'])} m³/d | {row['date']}", sub)
                ws.write("A3", f"Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}", sub)

                inputs = [
                    ["Feed TDS (ppm)", row.get("feed_tds", 0)],
                    ["Product TDS (ppm)", row.get("product_tds", 0)],
                    ["Feed P IN (bar)", row.get("feed_p_in", 0)],
                    ["Feed P OUT (bar)", row.get("feed_p_out", 0)],
                    ["Cartridge P (bar)", row.get("cartridge_p", 0)],
                    ["HP IN (bar)", row.get("hp_in", 0)],
                    ["HP OUT (bar)", row.get("hp_out", 0)],
                    ["Feed Flow (LPM)", row.get("feed_flow_lpm", 0)],
                    ["Product Flow (LPM)", row.get("product_flow_lpm", 0)],
                    ["Reject Flow (LPM) (calc)", row.get("reject_flow_lpm", 0)],
                    ["Water Temp (°C)", row.get("temp_c", 0)],
                    ["pH", row.get("ph", 0)],
                    ["SDI", row.get("sdi", 0)],
                ]
                ws.add_table(4,0,4+len(inputs),1,{"data":inputs,"columns":[{"header":"Field"},{"header":"Value"}],"style":"Table Style Light 9"})

                out = [
                    ["Recovery %", row.get("recovery_pct", 0)],
                    ["Rejection %", row.get("rejection_pct", 0) or 0.0],
                    ["Salt Passage %", row.get("salt_passage_pct", 0)],
                    ["ΔP Cartridge (bar)", row.get("cartridge_dp", 0) or 0.0],
                    ["ΔP Vessels (bar)", row.get("vessel_dp", 0) or 0.0],
                    ["HP ΔP (bar)", row.get("hp_dp", 0) or 0.0],
                    ["NDP (bar)", row.get("ndp_bar", 0)],
                    ["NPF (LPM)", row.get("npf_lpm", 0)],
                    ["PQI (0–100)", row.get("pqi", 0) or 0.0],
                    ["Specific Energy (kWh/m³)", row.get("specific_energy_kwh_m3", 0)],
                    ["Energy Today (kWh)", row.get("daily_kwh", 0)],
                    ["Flow Balance OK", "Yes" if row.get("feed_vs_sum_ok") else "No"],
                ]
                ws.add_table(4,4,4+len(out),5,{"data":out,"columns":[{"header":"Metric"},{"header":"Value"}],"style":"Table Style Light 9"})
                ws.write("A20","Maintenance Note", h); ws.write("A21", row.get("maintenance_note",""))

                # Stage summary sheet (from averages)
                stage_rows_x = []
                for s, avg_tds, stage_rej in stage_avgs:
                    stage_rows_x.append({"Stage": f"S{s}",
                                         "Avg Permeate TDS (ppm)": avg_tds if avg_tds is not None else "",
                                         "Stage Rejection %": stage_rej if stage_rej is not None else ""})
                pd.DataFrame(stage_rows_x).to_excel(writer, index=False, sheet_name="Stage_Summary")
                writer.sheets["Stage_Summary"].set_column(0, 2, 22)

                # Per-vessel sheet (conditional formatting for low rejection)
                pv_df_out = per_vessel_df if (per_vessel_df is not None and not per_vessel_df.empty) \
                    else pd.DataFrame(columns=["Stage","Vessel","Permeate TDS (ppm)","Rejection %"])
                pv_df_out.to_excel(writer, index=False, sheet_name="Per_Vessel")
                ws2 = writer.sheets["Per_Vessel"]; ws2.set_column(0, len(pv_df_out.columns)-1, 20)
                if not pv_df_out.empty and "Rejection %" in pv_df_out.columns:
                    rej_idx = list(pv_df_out.columns).index("Rejection %")
                    ws2.conditional_format(1, rej_idx, len(pv_df_out)+1, rej_idx,
                                           {"type":"cell","criteria":"<","value":60,"format":badfmt})

                # Recent 30-day trend
                recent = df_all.tail(30).copy()
                if not recent.empty:
                    recent["date"]=pd.to_datetime(recent["date"])
                    cols = ["date","feed_tds","product_tds","recovery_pct","rejection_pct","cartridge_dp","vessel_dp"]
                    existing = [c for c in cols if c in recent.columns]
                    recent = recent[existing]
                    recent.to_excel(writer, index=False, sheet_name="Recent_30d")
                    ws3 = writer.sheets["Recent_30d"]; ws3.set_column(0, 0, 12); ws3.set_column(1, len(existing)-1, 16)
                    if {"feed_tds","product_tds"}.issubset(set(existing)):
                        ch = wb.add_chart({"type":"line"})
                        ch.add_series({"name":"Feed TDS","categories":["Recent_30d",1,0,len(recent),0],"values":["Recent_30d",1,1,len(recent),1]})
                        ch.add_series({"name":"Product TDS","categories":["Recent_30d",1,0,len(recent),0],"values":["Recent_30d",1,2,len(recent),2]})
                        ch.set_title({"name":"TDS Trend (last 30 days)"}); ch.set_x_axis({"name":"Date"}); ch.set_y_axis({"name":"ppm"})
                        ws3.insert_chart("H3", ch, {"x_scale":1.2,"y_scale":1.0})

            fn_x=f"daily_{int(st.session_state['plant_capacity'])}m3d_{int(st.session_state['num_stages'])}stages_{row['date']}.xlsx"
            st.download_button("Download Daily Excel", excel_buf.getvalue(), file_name=fn_x,
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            (user_reports_dir(st.session_state.user_email,"daily")/fn_x).write_bytes(excel_buf.getvalue())

        # ---------- PDF EXPORT ----------
        if REPORTLAB_OK:
            pdf=io.BytesIO()
            doc=SimpleDocTemplate(pdf, pagesize=A4, leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=28)
            styles=getSampleStyleSheet(); title_s=styles["Title"]; normal=styles["Normal"]
            elements=[]
            elements.append(Paragraph(f"<b>{BRAND} — Daily RO Report</b>", title_s))
            elements.append(Paragraph(f"Plant: {int(st.session_state['plant_capacity'])} m³/day • Date: {row['date']}", normal))
            elements.append(Paragraph(f"Design: {breakup} • Vessels: {tot_v} • Membranes: {tot_m}", normal))
            elements.append(Spacer(1,8))

            inputs_tbl=[["Field","Value"],
                        ["Feed TDS (ppm)", f"{row.get('feed_tds',0):.0f}"],["Product TDS (ppm)", f"{row.get('product_tds',0):.0f}"],
                        ["Feed P IN (bar)", f"{row.get('feed_p_in',0):.2f}"],["Feed P OUT (bar)", f"{row.get('feed_p_out',0):.2f}"],
                        ["Cartridge P (bar)", f"{row.get('cartridge_p',0):.2f}"],
                        ["HP IN (bar)", f"{row.get('hp_in',0):.2f}"],["HP OUT (bar)", f"{row.get('hp_out',0):.2f}"],
                        ["Feed Flow (LPM)", f"{row.get('feed_flow_lpm',0):.1f}"],["Product Flow (LPM)", f"{row.get('product_flow_lpm',0):.1f}"],
                        ["Reject Flow (LPM) (calc)", f"{row.get('reject_flow_lpm',0):.1f}"],
                        ["Water Temp (°C)", f"{row.get('temp_c',0):.1f}"],["pH", f"{row.get('ph',0):.1f}"],["SDI", f"{row.get('sdi',0):.1f}"]]
            t_in=Table(inputs_tbl, colWidths=[180, 120])
            t_in.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0), colors.HexColor("#EEF4FF")),
                                      ('BOX',(0,0),(-1,-1),0.6,colors.black),('INNERGRID',(0,0),(-1,-1),0.25,colors.grey),
                                      ('ALIGN',(0,0),(-1,-1),'CENTER')]))
            elements.append(Paragraph("<b>Inputs</b>", normal)); elements.append(t_in); elements.append(Spacer(1,8))

            out_tbl=[["Metric","Value","Metric","Value"],
                     ["Recovery %", f"{row.get('recovery_pct',0):.1f}", "Rejection %", f"{(row.get('rejection_pct') or 0):.1f}"],
                     ["Salt Passage %", f"{row.get('salt_passage_pct',0):.2f}", "PQI (0–100)", f"{(row.get('pqi') or 0):.0f}"],
                     ["ΔP Cartridge (bar)", f"{(row.get('cartridge_dp') or 0):.2f}", "ΔP Vessels (bar)", f"{(row.get('vessel_dp') or 0):.2f}"],
                     ["HP ΔP (bar)", f"{(row.get('hp_dp') or 0):.2f}", "NDP (bar)", f"{row.get('ndp_bar',0):.2f}"],
                     ["NPF (LPM)", f"{row.get('npf_lpm',0):.1f}", "Specific Energy (kWh/m³)", f"{row.get('specific_energy_kwh_m3',0):.2f}"],
                     ["Energy Today (kWh)", f"{row.get('daily_kwh',0):.0f}", "Flow Balance OK", "Yes" if row.get("feed_vs_sum_ok") else "No"]]
            t_out=Table(out_tbl, colWidths=[150,80,150,80])
            t_out.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0), colors.HexColor("#EEF4FF")),
                                       ('BOX',(0,0),(-1,-1),0.6,colors.black),('INNERGRID',(0,0),(-1,-1),0.25,colors.grey),
                                       ('ALIGN',(0,0),(-1,-1),'CENTER')]))
            elements.append(Paragraph("<b>Outputs / KPIs</b>", normal)); elements.append(t_out); elements.append(Spacer(1,8))

            # Stage snapshot (from averages) + compact per-vessel
            tbl=[["Stage","Avg Permeate TDS (ppm)","Stage Rej %","", "", "", ""]]
            for s, avg_tds, stage_rej in stage_avgs:
                tbl.append([f"S{s}", f"{(avg_tds if avg_tds is not None else 0):.1f}", f"{(stage_rej or 0):.1f}","","","",""])
            if per_vessel_df is not None and not per_vessel_df.empty:
                tbl.append(["","","","","","",""]); tbl.append(["Vessel","Permeate TDS","Rej %","Vessel","Permeate TDS","Rej %",""])
                max_print=min(12, len(per_vessel_df))
                for i in range(0, max_print, 2):
                    r1=per_vessel_df.iloc[i]
                    if i+1<max_print:
                        r2=per_vessel_df.iloc[i+1]
                        tbl.append([f"V{int(r1['Vessel'])} (S{int(r1['Stage'])})", f"{float(r1['Permeate TDS (ppm)']):.1f}", f"{(r1['Rejection %'] or 0):.1f}",
                                    f"V{int(r2['Vessel'])} (S{int(r2['Stage'])})", f"{float(r2['Permeate TDS (ppm)']):.1f}", f"{(r2['Rejection %'] or 0):.1f}",""])
                    else:
                        tbl.append([f"V{int(r1['Vessel'])} (S{int(r1['Stage'])})", f"{float(r1['Permeate TDS (ppm)']):.1f}", f"{(r1['Rejection %'] or 0):.1f}","","","",""])
            t_st=Table(tbl, colWidths=[90,80,70,90,80,70,10])
            t_st.setStyle(TableStyle([('BOX',(0,0),(-1,-1),0.6,colors.black),('INNERGRID',(0,0),(-1,-1),0.25,colors.grey),('ALIGN',(0,0),(-1,-1),'CENTER')]))
            elements.append(Paragraph("<b>Stage & Vessel Snapshot</b>", normal)); elements.append(t_st); elements.append(Spacer(1,6))

            elements.append(Paragraph(f"<b>Daily Note:</b> {row.get('maintenance_note','')}", normal))
            doc.build(elements)
            fn_p=f"daily_{int(st.session_state['plant_capacity'])}m3d_{int(st.session_state['num_stages'])}stages_{row['date']}.pdf"
            st.download_button("Download Daily PDF", pdf.getvalue(), file_name=fn_p, mime="application/pdf")
            (user_reports_dir(st.session_state.user_email,"daily")/fn_p).write_bytes(pdf.getvalue())

# ---------- FORECAST HELPERS ----------
def linear_forecast_next(values: list, horizon_days: int = 30):
    if len(values)<2: return [values[-1]]*horizon_days if values else [0.0]*horizon_days
    x=np.arange(len(values)); y=np.array(values, float)
    try:
        m,b=np.polyfit(x,y,1); xf=np.arange(len(values), len(values)+horizon_days)
        return (m*xf+b).tolist()
    except Exception: return [values[-1]]*horizon_days
def next_crossing_day(series_future, threshold, above=True):
    for i,v in enumerate(series_future):
        if (above and v>threshold) or ((not above) and v<threshold): return i
    return None

# ---------- WEEKLY ----------
if st.session_state["page_mode"] == tr("Weekly Report", st.session_state["lang"]):
    st.markdown("### 📅 Weekly Report")
    start_date = st.date_input("Select week start date", value=date.today()-timedelta(days=6))
    path = csv_path_for_current()
    if not path.exists():
        st.warning("No daily data found for this plant yet.")
    else:
        df=pd.read_csv(path); df["date"]=pd.to_datetime(df["date"]).dt.date
        df_week = df[(df["date"]>=start_date) & (df["date"]<=start_date+timedelta(days=6))].sort_values("date")
        if df_week.empty:
            st.warning("No entries found for this week.")
        else:
            try:
                last_conf = df_week.iloc[-1]
                vps=json.loads(last_conf["vessels_per_stage"]); mpv=int(last_conf.get("membranes_per_vessel",6))
                tot_v=int(sum(vps)); tot_m=int(tot_v*mpv); brk=" | ".join([f"S{i+1}:{v}" for i,v in enumerate(vps)])
                st.info(f"Design: {brk} • Vessels: {tot_v} • Membranes: {tot_m}")
            except Exception: pass

            st.dataframe(df_week, use_container_width=True)
            def avg(col): return float(df_week[col].dropna().astype(float).mean()) if col in df_week else None
            c1,c2,c3,c4,c5,c6=st.columns(6)
            c1.metric("Avg Feed TDS", f"{(avg('feed_tds') or 0):.0f} ppm")
            c2.metric("Avg Product TDS", f"{(avg('product_tds') or 0):.0f} ppm")
            c3.metric("Avg Recovery", f"{(avg('recovery_pct') or 0):.1f} %")
            c4.metric("Avg Rejection", f"{(avg('rejection_pct') or 0):.1f} %")
            c5.metric("Avg ΔP Cartridge", f"{(avg('cartridge_dp') or 0):.2f} bar")
            c6.metric("Avg ΔP Vessels", f"{(avg('vessel_dp') or 0):.2f} bar")

            # Predictions
            for col,label,thr,above in [
                ("product_tds","Product TDS (ppm)",DEFAULT_LIMITS["product_tds_max"],True),
                ("cartridge_dp","Cartridge ΔP (bar)",DEFAULT_LIMITS["cartridge_dp_max"],True),
                ("vessel_dp","Vessel ΔP (bar)",DEFAULT_LIMITS["vessel_dp_max"],True),
                ("recovery_pct","Recovery (%)",DEFAULT_LIMITS["recovery_target"]+DEFAULT_LIMITS["recovery_high_margin"],True),
            ]:
                if col in df_week and df_week[col].notna().any():
                    vals=df_week[col].astype(float).tolist(); forecast=linear_forecast_next(vals,30); cross=next_crossing_day(forecast,thr,above)
                    if cross is None: st.info(f"{label}: Safe for next 30 days.")
                    else:
                        due=(date.today()+timedelta(days=cross)).strftime("%Y-%m-%d")
                        st.warning(f"{label}: Will cross {thr} in ~{cross} days → Due: {due}")

# ---------- MONTHLY ----------
if st.session_state["page_mode"] == tr("Monthly Report", st.session_state["lang"]):
    st.markdown("### 📅 Monthly Report")
    month_input = st.date_input("Pick any date in the month", value=date.today())
    month_str = f"{month_input.year}-{str(month_input.month).zfill(2)}"
    path = csv_path_for_current()
    if not path.exists():
        st.warning("No daily data found for this plant yet.")
    else:
        df=pd.read_csv(path); df["date"]=pd.to_datetime(df["date"]).dt.date
        df_month = df[(df["date"].apply(lambda d: d.strftime("%Y-%m"))==month_str)].sort_values("date")
        if df_month.empty:
            st.warning(f"No entries found for {month_str}.")
        else:
            try:
                last_conf=df_month.iloc[-1]
                vps=json.loads(last_conf["vessels_per_stage"]); mpv=int(last_conf.get("membranes_per_vessel",6))
                tot_v=int(sum(vps)); tot_m=int(tot_v*mpv); brk=" | ".join([f"S{i+1}:{v}" for i,v in enumerate(vps)])
                st.info(f"Design: {brk} • Vessels: {tot_v} • Membranes: {tot_m}")
            except Exception: pass
            st.dataframe(df_month, use_container_width=True)
            st.caption(f"Monthly energy ≈ {float(df_month.get('daily_kwh', pd.Series([]))).sum():.0f} kWh")
            # simple health score
            score=100
            if "product_tds" in df_month: score -= min(15, 3*len(df_month[df_month["product_tds"]>DEFAULT_LIMITS["product_tds_max"]]))
            if "rejection_pct" in df_month: score -= min(15, 2*len(df_month[df_month["rejection_pct"]<DEFAULT_LIMITS["rejection_min"]]))
            score=max(0,min(100,score))
            st.metric("Health Score", f"{score}/100")

# ---------- HISTORY & EXPORTS ----------
if st.session_state["page_mode"] == tr("History & Exports", st.session_state["lang"]):
    st.markdown("### 📚 History & Exports")
    path = csv_path_for_current()
    if not path.exists(): st.info("No history yet for this plant.")
    else:
        df = pd.read_csv(path); df["date"]=pd.to_datetime(df["date"]).dt.date
        c1,c2,c3 = st.columns(3)
        date_from = c1.date_input("From", value=df["date"].min())
        date_to   = c2.date_input("To",   value=df["date"].max())
        tds_thr   = c3.number_input("Show Product TDS > (ppm)", 0.0, 1e6, 0.0, 1.0)
        mask = (df["date"]>=date_from) & (df["date"]<=date_to)
        if tds_thr>0: mask &= (df["product_tds"]>tds_thr)
        out = df[mask].sort_values("date")
        st.dataframe(out, use_container_width=True); st.caption(f"{len(out)} rows")
        if XLSX_OK and not out.empty:
            excel_buf=io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine="xlsxwriter") as writer:
                out.to_excel(writer, index=False, sheet_name="Filtered")
            st.download_button("Download Filtered Excel", excel_buf.getvalue(), file_name=f"history_{date_from}to{date_to}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------- RO DESIGN ----------
if st.session_state["page_mode"] == tr("RO Design", st.session_state["lang"]):
    st.markdown("### 🧮 RO Design — Quick Sizing")
    cap_m3d = st.number_input("Target Capacity (m³/day)", 10, 50000, int(st.session_state["plant_capacity"]), 10)
    recovery_target = st.slider("Target Recovery (%)", 40, 85, int(st.session_state["design_rec"]))
    prod_m3h = cap_m3d/24.0; per_elem_m3h = 1.2
    need_elements = int(np.ceil(prod_m3h / per_elem_m3h))
    per_vessel_elems = st.number_input('Membranes per vessel (8")', 1, 8, int(st.session_state["membranes_per_vessel"]), 1)
    need_vessels = int(np.ceil(need_elements / per_vessel_elems))
    stages = st.slider("Stages", 1, 6, int(st.session_state["num_stages"]))
    split=[]; rem=need_vessels
    for i in range(stages):
        v=int(np.ceil(rem/(stages-i))); split.append(v); rem-=v
    st.write(f"Suggested vessels per stage: {split} (total vessels: {sum(split)}, total membranes: {sum(split)*per_vessel_elems})")
    st.caption("Quick estimate — refine with feed TDS, temperature, and design constraints.")