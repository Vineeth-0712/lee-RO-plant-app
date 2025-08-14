# --- STP_Designer.py (LeeWave • STP Designer) ---
import math, json, io
from datetime import date
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="LeeWave • STP Designer", page_icon="🧫", layout="wide")

# ---------- Helpers ----------
def m3d_to_m3h(x): return x/24.0

def aeration_tank_size(Q_m3d, influent_BOD_mgL, target_SRT_days=10, MLSS_mgL=3500, F_M=0.2):
    # Very common ASP rule-of-thumb approach
    Q_m3h = m3d_to_m3h(Q_m3d)
    BOD_kgd = Q_m3d * influent_BOD_mgL/1000.0
    # Biomass needed (kg MLSS) from F/M : F/M = (kg BOD/day) / (kg MLSS in reactor)
    MLSS_kg_needed = BOD_kgd / max(F_M, 0.05)
    # Reactor volume from MLSS conc: MLSS_kg = MLSS_mgL * V_m3 / 1e6
    V_reactor_m3 = MLSS_kg_needed * 1e6 / max(MLSS_mgL, 1.0)
    # HRT (check)
    HRT_h = V_reactor_m3 / max(Q_m3h, 1e-6)
    return V_reactor_m3, HRT_h, BOD_kgd

def air_req_kgO2_per_h(BOD_kgd, aeration_alpha=0.8, OTR_kgO2_per_kWh=1.8):
    # thumb rule: ~1.1–1.5 kg O2 per kg BOD removed (here use 1.2)
    kgO2_per_day = 1.2 * BOD_kgd / max(aeration_alpha,0.3)
    return kgO2_per_day/24.0  # kg O2/h

def blower_power_kW(kgO2_h, OTR_kgO2_per_kWh=1.8):
    return kgO2_h / max(OTR_kgO2_per_kWh, 0.5)

def secondary_clarifier_area(Q_m3d, overflow_rate_m3_m2_d=18):
    return Q_m3d / max(overflow_rate_m3_m2_d, 1.0)

def sludge_production_kgd(BOD_kgd, Y_obs=0.6):
    return Y_obs * BOD_kgd  # very rough

def chlorination_dose_mgL(target_residual_mgL=1.0, demand_mgL=3.0):
    return target_residual_mgL + demand_mgL

# ---------- UI ----------
st.title("LeeWave • STP Designer")
st.caption("From influent to layout: aeration, clarifiers, blowers & basic BOM.")

with st.sidebar:
    st.header("🌐 Language")
    lang = st.selectbox("Select Language", ["English","Arabic"], index=0)

L = {
    "Capacity (m³/day)":"Capacity (m³/day)",
    "Influent BOD (mg/L)":"Influent BOD (mg/L)",
    "Influent TSS (mg/L)":"Influent TSS (mg/L)",
    "Effluent Class / Target":"Effluent Class / Target",
    "Process":"Process",
    "MLSS (mg/L)":"MLSS (mg/L)",
    "Design SRT (days)":"Design SRT (days)",
    "F/M ratio":"F/M ratio",
    "Alpha (wastewater)":"Alpha (wastewater)",
    "OTR (kgO₂/kWh)":"OTR (kgO₂/kWh)",
    "Clarifier surface OLR (m³/m²·d)":"Clarifier surface OLR (m³/m²·d)",
}
if lang=="Arabic":
    L.update({
        "Capacity (m³/day)":"السعة (م³/يوم)",
        "Influent BOD (mg/L)":"BOD الداخل (ملغم/ل)",
        "Influent TSS (mg/L)":"TSS الداخل (ملغم/ل)",
        "Effluent Class / Target":"فئة/متطلبات المياه الخارجة",
        "Process":"المعالجة",
        "MLSS (mg/L)":"MLSS (ملغم/ل)",
        "Design SRT (days)":"SRT التصميمي (أيام)",
        "F/M ratio":"نسبة الغذاء/الكتلة (F/M)",
        "Alpha (wastewater)":"ألفا (مياه صرف)",
        "OTR (kgO₂/kWh)":"OTR (كغ O₂/ك.و.س)",
        "Clarifier surface OLR (m³/m²·d)":"حمل سطحية المروّق (م³/م²·يوم)",
    })

col1,col2,col3 = st.columns(3)
with col1:
    cap_m3d = st.number_input(L["Capacity (m³/day)"], 50, 500000, 5000, 50)
    influent_BOD = st.number_input(L["Influent BOD (mg/L)"], 100, 1000, 300, 10)
    influent_TSS = st.number_input(L["Influent TSS (mg/L)"], 50, 1500, 250, 10)
with col2:
    eff_target = st.selectbox(L["Effluent Class / Target"], ["Secondary", "Tertiary (N,P)", "Recycling+UF"])
    process = st.selectbox(L["Process"], ["ASP (Conventional)", "SBR", "MBBR", "MBR"], index=0)
    MLSS = st.number_input(L["MLSS (mg/L)"], 2000, 12000, 3500, 100)
with col3:
    SRT = st.slider(L["Design SRT (days)"], 5, 25, 12, 1)
    FM = st.slider(L["F/M ratio"], 0.05, 0.6, 0.20, 0.01)
    alpha = st.slider(L["Alpha (wastewater)"], 0.5, 1.0, 0.8, 0.01)

st.markdown("---")
col4,col5 = st.columns(2)
with col4:
    OTR = st.slider(L["OTR (kgO₂/kWh)"], 0.8, 2.5, 1.8, 0.1)
with col5:
    clar_olr = st.slider(L["Clarifier surface OLR (m³/m²·d)"], 10, 30, 18, 1)

# ---------- Sizing ----------
V_aer_m3, HRT_h, BOD_kgd = aeration_tank_size(cap_m3d, influent_BOD, SRT, MLSS, FM)
kgO2_h = air_req_kgO2_per_h(BOD_kgd, aeration_alpha=alpha, OTR_kgO2_per_kWh=OTR)
blower_kW = kgO2_h / max(OTR,0.5)

clar_area_m2 = secondary_clarifier_area(cap_m3d, overflow_rate_m3_m2_d=clar_olr)
sludge_kgd   = sludge_production_kgd(BOD_kgd, Y_obs=0.6)

# Effluent polishing suggestions
tertiary = []
if eff_target in ("Tertiary (N,P)", "Recycling+UF"): tertiary.append("Tertiary filter/UF")
if eff_target in ("Tertiary (N,P)",): tertiary.append("Chemical P-removal (Alum/Ferric)")
tertiary.append("UV/Chlorination")

# BOM
bom = []
bom.append(["Aeration Tank", f"{V_aer_m3:,.0f} m³", f"HRT ≈ {HRT_h:.1f} h, MLSS={MLSS} mg/L"])
bom.append(["Blowers (total)", f"{blower_kW:.1f} kW", f"O₂ demand ≈ {kgO2_h:.1f} kg/h"])
bom.append(["Secondary Clarifiers", f"{clar_area_m2:,.0f} m² (total surface)", f"OLR={clar_olr} m³/m²·d"])
bom.append(["Sludge Handling", f"{sludge_kgd:,.0f} kg/d", "Thickener/Filter press"])
for t in tertiary:
    bom.append(["Tertiary & Disinfection", t, ""])

bom_df = pd.DataFrame(bom, columns=["Item","Spec","Note"])

# ---------- Output ----------
st.markdown("### Design Summary")
c1,c2,c3,c4,c5,c6 = st.columns(6)
with c1: st.metric("BOD load", f"{BOD_kgd:,.0f} kg/d")
with c2: st.metric("Aeration Tank", f"{V_aer_m3:,.0f} m³")
with c3: st.metric("HRT", f"{HRT_h:.1f} h")
with c4: st.metric("Blower Power", f"{blower_kW:.1f} kW")
with c5: st.metric("Clarifier Area", f"{clar_area_m2:,.0f} m²")
with c6: st.metric("Sludge", f"{sludge_kgd:,.0f} kg/d")

st.markdown("#### Bill of Materials (BOM)")
st.dataframe(bom_df, use_container_width=True)

st.markdown("#### Notes")
st.write("- Values are *concept-level*. Refine with local standards, peak factors, return sludge (RAS/WAS) rates, and manufacturer curves.")
st.write("- For SBR/MBR/MBBR, tank volumes differ; this tool normalizes to equivalent ASP volume for quick feasibility.")

# ---------- Exports ----------
exp = {
  "date": str(date.today()),
  "inputs": {
    "capacity_m3d": cap_m3d, "influent_BOD_mgL": influent_BOD, "influent_TSS_mgL": influent_TSS,
    "effluent_target": eff_target, "process": process, "MLSS_mgL": MLSS, "SRT_days": SRT, "F_M": FM,
    "alpha": alpha, "OTR": OTR, "clarifier_OLR": clar_olr
  },
  "sizing": {
    "aeration_volume_m3": V_aer_m3, "HRT_h": HRT_h, "BOD_kgd": BOD_kgd,
    "oxygen_kg_per_h": kgO2_h, "blower_kW": blower_kW,
    "clarifier_area_m2": clar_area_m2, "sludge_kgd": sludge_kgd
  },
  "bom": bom_df.to_dict(orient="records")
}
st.download_button("Download STP Design (JSON)", data=json.dumps(exp, indent=2).encode(), file_name="STP_design.json", mime="application/json")
csv_buf = io.StringIO(); bom_df.to_csv(csv_buf, index=False)
st.download_button("Download BOM (CSV)", data=csv_buf.getvalue(), file_name="STP_BOM.csv", mime="text/csv")