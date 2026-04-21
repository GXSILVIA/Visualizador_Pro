#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa - Versión Profesional Integrada

import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os, io, yaml, numpy as np, re
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
import streamlit.components.v1 as components
import xlsxwriter 
from folium.plugins import Fullscreen

# --- 1. CONFIGURACIÓN Y CÁLCULOS ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

@st.cache_data
def area_interseccion(r1, r2, d):
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return np.pi * min(r1, r2)**2
    p1 = r1**2 * np.arccos(np.clip((d**2 + r1**2 - r2**2) / (2 * d * r1), -1, 1))
    p2 = r2**2 * np.arccos(np.clip((d**2 + r2**2 - r1**2) / (2 * d * r2), -1, 1))
    p3 = 0.5 * np.sqrt(max(0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return p1 + p2 - p3

@st.cache_data
def calcular_traslape_real(p1, otros_pts):
    if not otros_pts: return 0.0
    n = 8000 # Precisión profesional
    ang = np.random.uniform(0, 2*np.pi, n)
    rad = np.sqrt(np.random.uniform(0, 1, n)) * p1['RAD']
    m_grado = 111139
    cos_lat = np.cos(np.radians(p1['LAT']))
    p_lat = p1['LAT'] + ((rad * np.sin(ang)) / m_grado)
    p_lon = p1['LON'] + ((rad * np.cos(ang)) / (m_grado * cos_lat))
    cubiertos = np.zeros(n, dtype=bool)
    for p2 in otros_pts:
        d2 = ((p_lat - p2['LAT'])**2 + ((p_lon - p2['LON']) * cos_lat)**2) * (m_grado**2)
        cubiertos |= (d2 <= p2['RAD']**2)
        if np.all(cubiertos): break 
    return (np.sum(cubiertos) / n) * 100

def obtener_rango_id(v, modo_p):
    lim = [100, 200, 300, 400] if modo_p else [15, 20, 30, 40]
    return next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0

def normalizar(df, modo):
    df.columns = df.columns.str.strip().str.upper()
    mapa = {'LAT':['LATITUD','LAT'],'LON':['LONGITUD','LON'],'VOL':['VOLUMEN','VOL'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA']}
    df = df.rename(columns={c: k for k, v in mapa.items() for c in df.columns if c in v})
    for c in ['LAT','LON','VOL','RAD']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    if 'RAD' not in df.columns or (df['RAD'] == 0).all(): df['RAD'] = 750
    if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'ZONA')
    df['R_ID'] = df['VOL'].apply(lambda x: obtener_rango_id(x, "Polígonos" in modo))
    return df

# --- 2. SEGURIDAD ---
with open('config.yaml') as f: config = yaml.load(f, SafeLoader)
auth = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
auth.login(location='main')

if st.session_state.get("authentication_status"):
    # Inicialización de estados para Crecimiento
    if 'dict_hojas' not in st.session_state: st.session_state.dict_hojas = None
    if 'idx_hoja' not in st.session_state: st.session_state.idx_hoja = 0
    if 'df_datos' not in st.session_state: st.session_state.df_datos = None

    col_m, col_p = st.columns([3, 1.3])
   
    with col_p:
        st.title("🛡️ Panel Pro")
        auth.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa", ["Coordenadas", "Polígonos CP", "Crecimiento"])
        m_ana = st.toggle("🔍 Tabla de Análisis", value=False)
        
        xl_file = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if xl_file:
            if modo == "Crecimiento":
                if st.button("🚀 Procesar Multi-Pestaña"):
                    xl = pd.ExcelFile(xl_file)
                    st.session_state.dict_hojas = {s: normalizar(xl.parse(s), modo) for s in xl.sheet_names}
                    st.session_state.idx_hoja = 0
                    st.rerun()
            else:
                if st.button("🔄 Procesar"):
                    st.session_state.df_datos = normalizar(pd.read_excel(xl_file), modo)
                    st.rerun()

        # Controles de Navegación Crecimiento
        if modo == "Crecimiento" and st.session_state.dict_hojas:
            nombres = list(st.session_state.dict_hojas.keys())
            st.info(f"Pestaña: {nombres[st.session_state.idx_hoja]}")
            c1, c2 = st.columns(2)
            if c1.button("⬅️ Anterior") and st.session_state.idx_hoja > 0:
                st.session_state.idx_hoja -= 1
                st.rerun()
            if c2.button("Siguiente ➡️") and st.session_state.idx_hoja < len(nombres)-1:
                st.session_state.idx_hoja += 1
                st.rerun()

        st.write("---")
        labs = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
        cols_f = st.columns(3); acts = [i for i, l in enumerate(labs) if cols_f[i%3].checkbox(l, value=True, key=f"r{i}")]
        ver_n = st.toggle("🏷️ Ver Nombres Fijos", value=True)
        if m_ana:
            f_estatus = st.multiselect("ST:", ["🟢 Sano", "🟡 Medio", "🟠 Bajo", "🔴 Crítico", "⚪ Fuera de Rango"], default=["🟢 Sano", "🟡 Medio", "🟠 Bajo", "🔴 Crítico"])
        
    # --- 3. LÓGICA DE MAPA ---
    with col_m:
        df_act = None
        if modo == "Crecimiento" and st.session_state.dict_hojas:
            df_act = st.session_state.dict_hojas[list(st.session_state.dict_hojas.keys())[st.session_state.idx_hoja]]
        else:
            df_act = st.session_state.df_datos

        if df_act is not None:
            df_v = df_act[df_act['R_ID'].isin(acts)].copy()
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            clrs = {0:"#FFF", 1:"#FF0", 2:"#FFA500", 3:"#F00", 4:"#FF4500", 5:"#800000"}
            rep = []

            # --- PROCESAMIENTO COORDENADAS / CRECIMIENTO ---
            if 'LAT' in df_v.columns and 'LON' in df_v.columns:
                df_c = df_v[(df_v['LAT'] != 0) & (df_v['LON'] != 0)]
                if not df_c.empty:
                    m.fit_bounds([[df_c['LAT'].min(), df_c['LON'].min()], [df_c['LAT'].max(), df_c['LON'].max()]])
                    pts = df_c.to_dict('records')
                    for i, p1 in enumerate(pts):
                        otros = [p for j, p in enumerate(pts) if i != j]
                        ints = [{"nom": p2['NOM'], "porc": round((area_interseccion(p1['RAD'], p2['RAD'], np.sqrt((p1['LAT']-p2['LAT'])**2 + ((p1['LON']-p2['LON'])*np.cos(np.radians(p1['LAT'])))**2)*111139) / (np.pi * p1['RAD']**2))*100, 1)} for p2 in otros if np.sqrt((p1['LAT']-p2['LAT'])**2 + ((p1['LON']-p2['LON'])*np.cos(np.radians(p1['LAT'])))**2)*111139 < (p1['RAD']+p2['RAD'])]
                        ints = [x for x in ints if x['porc'] > 0]
                        
                        tr_total = round(calcular_traslape_real(p1, otros), 1)
                        vol_act = p1['VOL']
                        pq_perdidos = round(sum([(vol_act * (n['porc'] / 100)) / 2 for n in ints]), 1)
                        potencial = round(vol_act + pq_perdidos, 1)

                        salud = "🟢 Sano" if 30 <= vol_act <= 50 else "🟡 Medio" if 21 <= vol_act <= 29 else "🟠 Bajo" if 15 <= vol_act <= 20 else "🔴 Crítico" if vol_act >= 51 else "⚪ Fuera de Rango"
                        
                        folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=clrs[p1['R_ID']], fill=True, fill_opacity=0.35, tooltip=f"<b>{p1['NOM']}</b><br>Vol: {int(vol_act)}<br>Traslape: {tr_total}%").add_to(m)
                        if ver_n: folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-shadow: 0 0 2px #FFF; width:100px;">{p1["NOM"]}</div>')).add_to(m)
                        
                        rep.append({"ST": salud, "Zona": p1['NOM'], "Paquetes Actual": int(vol_act), "Pq Perdidos": pq_perdidos, "Potencial Ideal": potencial, "% Traslape Real": f"{tr_total}%", "Detalle": ", ".join([f"{n['nom']}({n['porc']}%)" for n in ints]) if ints else "Sano"})

            mapa_html = m.get_root().render()
            components.html(mapa_html, height=550)

            # --- EXPORTACIÓN Y TABLA ---
            if m_ana and rep:
                st.write("---")
                if modo == "Crecimiento" and st.session_state.idx_hoja > 0:
                    prev_nom = list(st.session_state.dict_hojas.keys())[st.session_state.idx_hoja - 1]
                    nuevas = len(set(df_v['NOM']) - set(st.session_state.dict_hojas[prev_nom]['NOM']))
                    c1, c2 = st.columns(2)
                    c1.metric("Zonas Nuevas vs Anterior", nuevas)
                    c2.metric("Pestaña", list(st.session_state.dict_hojas.keys())[st.session_state.idx_hoja])

                df_rep = pd.DataFrame(rep)
                st.dataframe(df_rep[df_rep['ST'].isin(f_estatus)], use_container_width=True, hide_index=True)

            c1, c2 = st.columns(2)
            c1.download_button("🗺️ Exportar Mapa HTML", data=mapa_html, file_name=f"mapa_{modo}.html", use_container_width=True)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                if modo == "Crecimiento":
                    for n, df_h in st.session_state.dict_hojas.items(): df_h.to_excel(writer, sheet_name=n[:31], index=False)
                else: pd.DataFrame(rep).to_excel(writer, index=False, sheet_name='Analisis')
            c2.download_button("📊 Exportar Análisis Excel", data=buf.getvalue(), file_name="analisis_amzl.xlsx", use_container_width=True)
