# --- RO_Designer.py (LeeWave • RO Plant Designer) ---
import math, json, io
from datetime import date
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="LeeWave • RO Designer", page_icon="🧮", layout="wide")

# ---------- Helpers ----------
def m3d_to_m3h(x): return x/24.0
def m3h_to_lpm(x): return x*1000/60
def lpm_to_m3h(x): return x*60/1000
def tcf_approx(temp_c):  # temperature correction factor (simple)
    return max(0.6, min(1.6, 1.0 + 0.03*(temp_c-25.0)))

def permeate_flux_lmh(permeate_m3h, membrane_area_m2):
    return (permeate_m3h*1000)/max(membrane_area_m2,1e-6)

def ro_pump_power_kw(pressure_bar, feed_m3h, pump_eff=0.75):
    # kW ≈ (ΔP[bar] * Q[m3/h]) / (36 * η)
    return (pressure_bar * feed_m3h) / (36.0 * max(pump_eff,0.05))

def osmotic_bar(tds_mgL, temp_c):
    # very rough π ≈ 0.0008 * TDS(mg/L) * (T/298). Good enough for concept sizing.
    return 0.0008*max(tds_mgL,0)*(temp_c+273.15)/298.0

def antiscalant_dose_mgL(feed_tds, recovery_pct):
    # heuristic dose range (very rough guideline)
    base = 2.0 if feed_tds < 1500 else 3.0 if feed_tds < 3000 else 4.0 if feed_tds < 6000 else 5.0
    bump = 0 if recovery_pct <= 65 else 0.5 if recovery_pct <= 75 else 1.0
    return base + bump

def cartridge_filter_size_lpm(feed_lpm, vmax_lpm_per_10inch=120):
    # rule: ~120 LPM per 10" cartridge (5µ) for comfortable ΔP
    n = math.ceil(feed_lpm/max(vmax_lpm_per_10inch,1))
    return n, n*10  # count, "equivalent length” (for label only)

def suggest_array_split(vessels_total, stages):
    # evenly split, slightly front-heavy (e.g., 2-1, 3-2-1)
    split = []
    rem = vessels_total
    for i in range(stages):
        v = math.ceil(rem/(stages-i))
        split.append(v); rem -= v
    return split

# ---------- Sidebar Inputs ----------
st.title("LeeWave • RO Plant Designer")
st.caption("Concept-to-BOM in minutes — professional, capacity-agnostic.")

with st.sidebar:
    st.header("🌐 Language")
    lang = st.selectbox("Select Language", ["English","Arabic"], index=0)

# minimal i18n wrapper for few key labels (English default):
L = {
    "Capacity (m³/day)":"Capacity (m³/day)",
    "Design Recovery (%)":"Design Recovery (%)",
    "Target Product TDS (ppm)":"Target Product TDS (ppm)",
    "Feed TDS (ppm)":"Feed TDS (ppm)",
    "Temperature (°C)":"Temperature (°C)",
    "Membrane family":"Membrane family",
    "Element area (m²)":"Element area (m²)",
    "Max flux (LMH)":"Max flux (LMH)",
    "Stages":"Stages",
    "Membranes per vessel":"Membranes per vessel",
    "HP Pump efficiency (%)":"HP Pump efficiency (%)",
    "Pretreatment":"Pretreatment",
    "SDI (15-min)":"SDI (15-min)",
    "Turbidity (NTU)":"Turbidity (NTU)",
    "Alkalinity (as CaCO₃, mg/L)":"Alkalinity (as CaCO₃, mg/L)",
    "Silica (mg/L)":"Silica (mg/L)",
    "Disinfection":"Disinfection",
    "Free Chlorine (mg/L)":"Free Chlorine (mg/L)",
}
if lang=="Arabic":
    L.update({
        "Capacity (m³/day)":"السعة (م³/يوم)",
        "Design Recovery (%)":"نسبة الاسترجاع (%)",
        "Target Product TDS (ppm)":"TDS المطلوب للمنتج (ppm)",
        "Feed TDS (ppm)":"TDS للمغذي (ppm)",
        "Temperature (°C)":"درجة الحرارة (°م)",
        "Membrane family":"عائلة الغشاء",
        "Element area (m²)":"مساحة العنصر (م²)",
        "Max flux (LMH)":"التدفق السطحي الأقصى (LMH)",
        "Stages":"المراحل",
        "Membranes per vessel":"الأغشية لكل وعاء",
        "HP Pump efficiency (%)":"كفاءة مضخة الضغط العالي (%)",
        "Pretreatment":"المعالجة الأولية",
        "SDI (15-min)":"SDI (15 دقيقة)",
        "Turbidity (NTU)":"العكارة (NTU)",
        "Alkalinity (as CaCO₃, mg/L)":"القلوية (CaCO₃، ملغم/ل)",
        "Silica (mg/L)":"السيليكا (ملغم/ل)",
        "Disinfection":"التطهير",
        "Free Chlorine (mg/L)":"الكلور الحر (ملغم/ل)",
    })

col1,col2,col3 = st.columns(3)
with col1:
    cap_m3d   = st.number_input(L["Capacity (m³/day)"], 10, 200000, 500, 10)
    recovery  = st.slider(L["Design Recovery (%)"], 40, 85, 70, 1)
    prod_tds_target = st.number_input(L["Target Product TDS (ppm)"], 1, 2000, 50, 1)
with col2:
    feed_tds  = st.number_input(L["Feed TDS (ppm)"], 50, 45000, 1500, 10)
    temp_c    = st.number_input(L["Temperature (°C)"], 5.0, 45.0, 25.0, 0.5)
    sdi       = st.number_input(L["SDI (15-min)"], 0.0, 10.0, 3.0, 0.1)
with col3:
    turb      = st.number_input(L["Turbidity (NTU)"], 0.0, 100.0, 0.5, 0.1)
    alk       = st.number_input(L["Alkalinity (as CaCO₃, mg/L)"], 0.0, 1000.0, 150.0, 1.0)
    silica    = st.number_input(L["Silica (mg/L)"], 0.0, 200.0, 15.0, 0.5)

st.markdown("---")

colA,colB,colC = st.columns(3)
with colA:
    family = st.selectbox(L["Membrane family"], [
        "BWRO (brackish)", "SWRO (seawater)", "URO (ultra-low pressure)"
    ], index=0)
    area_m2 = st.number_input(L["Element area (m²)"], 35.0, 41.0, 37.0, 0.5)  # typical 8" 34–41 m²
with colB:
    max_flux = st.number_input(L["Max flux (LMH)"], 10.0, 28.0, 18.0, 0.5)
    stages   = st.slider(L["Stages"], 1, 6, 2)
with colC:
    mpv      = st.slider(L["Membranes per vessel"], 1, 8, 6)
    pump_eff = st.slider(L["HP Pump efficiency (%)"], 40, 90, 75)

st.markdown("---")
st.subheader(L["Pretreatment"])
colP1,colP2,colP3,colP4 = st.columns(4)
with colP1: pre_cart = st.checkbox("5µ Cartridge", True)
with colP2: pre_mm   = st.checkbox("MM/UF", True)
with colP3: pre_acid = st.checkbox("Acid Dosing", False)
with colP4: pre_as   = st.checkbox("Antiscalant", True)

st.subheader(L["Disinfection"])
colD1,colD2 = st.columns(2)
with colD1: free_cl = st.number_input(L["Free Chlorine (mg/L)"], 0.0, 5.0, 0.0, 0.1)
with colD2: post_uv = st.checkbox("Post UV / Chlorination", True)

# ---------- Core Sizing ----------
prod_m3h = m3d_to_m3h(cap_m3d)
feed_m3h = prod_m3h / max(recovery/100.0, 0.01)
feed_lpm = m3h_to_lpm(feed_m3h)

tcf = tcf_approx(temp_c)
# Per element comfortable permeate (m3/h) from flux cap:
per_elem_m3h_flux = (max_flux/1000.0)*area_m2
# Also compute design permeate per element using nominal 18–20 LMH adjusted by TCF:
design_lmh = max_flux*0.85  # run under max
per_elem_m3h = (design_lmh/1000.0) * area_m2

need_elements = math.ceil(prod_m3h / max(per_elem_m3h,1e-6))
need_vessels  = math.ceil(need_elements / mpv)
split = suggest_array_split(need_vessels, stages)

# Pressures (very coarse concept):
pi = osmotic_bar(feed_tds, temp_c)
pp = osmotic_bar(prod_tds_target, temp_c)
ndp_target = 8.0 if family!="SWRO" else 15.0  # bar
deltaP_array = 2.0 if family!="SWRO" else 4.0 # bar
required_hp_out = ndp_target + (pi-pp) + deltaP_array
pump_kw = ro_pump_power_kw(required_hp_out, feed_m3h, pump_eff/100.0)

# Antiscalant + acid suggestion
as_dose = antiscalant_dose_mgL(feed_tds, recovery)
acid_needed = pre_acid or (alk>200 and recovery>70)

# Cartridge count
cart_n, _cart_len = cartridge_filter_size_lpm(feed_lpm)

# Bill of Materials dataframe
bom = []
bom.append(["HP Pump", f"{required_hp_out:.1f} bar @ {feed_m3h:.2f} m³/h", f"{pump_kw:.1f} kW (η={pump_eff}%)"])
bom.append(["Pressure Vessels", f"{need_vessels} ea", f"{mpv} membranes/vessel"])
bom.append(["RO Membranes", f"{need_elements} ea", f"{area_m2:.1f} m²/element"])
bom.append(["Array Split", f"{'-'.join(map(str,split))}", f"{stages} stages"])
if pre_cart:
    bom.append(["5µ Cartridge Filter", f"{cart_n} x 10\" cartridges", f"~{feed_lpm/cart_n:.0f} LPM each"])
if pre_mm: bom.append(["MM/UF Pretreatment", "As required", f"SDI {sdi:.1f}, NTU {turb:.2f}"])
if pre_as: bom.append(["Antiscalant System", f"{as_dose:.1f} mg/L (guide)", "Auto-dosing skid"])
if acid_needed:
    bom.append(["Acid Dosing", "pH trim for scaling control", f"Alk={alk:.0f} mg/L"])
if post_uv: bom.append(["Post Disinfection", "UV/Chlorination", f"Free Cl={free_cl:.2f} mg/L"])

bom_df = pd.DataFrame(bom, columns=["Item","Spec","Note"])

# ---------- Output ----------
st.markdown("### Design Summary")
c1,c2,c3,c4,c5,c6 = st.columns(6)
with c1: st.metric("Product", f"{prod_m3h:.2f} m³/h")
with c2: st.metric("Feed", f"{feed_m3h:.2f} m³/h")
with c3: st.metric("Recovery", f"{recovery:.0f}%")
with c4: st.metric("Required HP Out", f"{required_hp_out:.1f} bar")
with c5: st.metric("Pump Power", f"{pump_kw:.1f} kW")
with c6: st.metric("Vessels / Membranes", f"{need_vessels} / {need_elements}")

st.markdown("#### Array & Hydraulics")
st.write(f"Stages: *{stages}* → Split: *{' - '.join(map(str,split))}* (vessels per stage)")
st.write(f"Design LMH ≈ *{design_lmh:.1f}; Per-element permeate ≈ **{per_elem_m3h:.3f} m³/h*")
st.write(f"Osmotic feed/product ≈ *{pi:.1f}/{pp:.1f} bar, ΔP array ≈ **{deltaP_array:.1f} bar, NDP target ≈ **{ndp_target:.1f} bar*")

st.markdown("#### Pretreatment & Chemicals")
st.write(f"SDI={sdi:.1f}, NTU={turb:.2f}, Alkalinity={alk:.0f} mg/L, Silica={silica:.1f} mg/L")
st.write(f"Antiscalant guide dose ≈ *{as_dose:.1f} mg/L; Acid dosing needed: **{'Yes' if acid_needed else 'No'}*")

st.markdown("#### Bill of Materials (BOM)")
st.dataframe(bom_df, use_container_width=True)

# ---------- Exports ----------
exp = {
  "date": str(date.today()),
  "inputs": {
    "capacity_m3d": cap_m3d, "recovery_pct": recovery, "feed_tds_ppm": feed_tds,
    "temp_c": temp_c, "area_m2": area_m2, "max_flux_lmh": max_flux, "stages": stages,
    "membranes_per_vessel": mpv, "pump_eff_pct": pump_eff
  },
  "hydraulics":{
    "prod_m3h": prod_m3h, "feed_m3h": feed_m3h, "required_hp_bar": required_hp_out,
    "pump_kw": pump_kw, "array_split": split
  },
  "pretreatment":{
    "sdi": sdi, "turbidity": turb, "alkalinity": alk, "silica": silica,
    "cartridge_count": cart_n, "antiscalant_mgL": as_dose, "acid_needed": bool(acid_needed),
    "post_uv": bool(post_uv), "free_chlorine": free_cl
  },
  "bom": bom_df.to_dict(orient="records")
}
st.download_button("Download RO Design (JSON)", data=json.dumps(exp, indent=2).encode(), file_name="RO_design.json", mime="application/json")
csv_buf = io.StringIO(); bom_df.to_csv(csv_buf, index=False)
st.download_button("Download BOM (CSV)", data=csv_buf.getvalue(), file_name="RO_BOM.csv", mime="text/csv")

st.caption("Note: Concept-level sizing. Validate with manufacturer datasheets and detailed process simulation before procurement.")