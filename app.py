#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os, io, yaml, numpy as np, re
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
import streamlit.components.v1 as components

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

def area_interseccion(r1, r2, d):
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return np.pi * min(r1, r2)**2
    p1 = r1**2 * np.arccos(np.clip((d**2 + r1**2 - r2**2) / (2 * d * r1), -1, 1))
    p2 = r2**2 * np.arccos(np.clip((d**2 + r2**2 - r1**2) / (2 * d * r2), -1, 1))
    p3 = 0.5 * np.sqrt(max(0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return p1 + p2 - p3

def calcular_traslape_real(p1, otros_pts):
    if not otros_pts: return 0.0
    n = 3000 
    ang = np.random.uniform(0, 2*np.pi, n)
    rad = np.sqrt(np.random.uniform(0, 1, n)) * p1['RAD']
    m_grado = 111139
    p_lat = p1['LAT'] + ((rad * np.sin(ang)) / m_grado)
    p_lon = p1['LON'] + ((rad * np.cos(ang)) / (m_grado * np.cos(np.radians(p1['LAT']))))
    cubiertos = np.zeros(n, dtype=bool)
    for p2 in otros_pts:
        d2 = ((p_lat - p2['LAT'])**2 + ((p_lon - p2['LON']) * np.cos(np.radians(p1['LAT'])))**2) * (m_grado**2)
        cubiertos |= (d2 <= p2['RAD']**2)
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
    if 'CP' in df.columns: df['CP'] = df['CP'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
    if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'ZONA')
    df['R_ID'] = df['VOL'].apply(lambda x: obtener_rango_id(x, "Polígonos" in modo))
    return df

# --- 2. SEGURIDAD ---
with open('config.yaml') as f: config = yaml.load(f, SafeLoader)
auth = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
name, status, user = auth.login(location='main')

if status:
    if 'df_datos' not in st.session_state: st.session_state.df_datos = None
    col_m, col_p = st.columns([3, 1.3])
    
    with col_p:
        st.title("🛡️ Panel AMZL")
        auth.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa", ["Coordenadas", "Polígonos CP"])
        
        xl_file = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if xl_file and st.button("🔄 Procesar"):
            # Carga directa de la primera pestaña
            st.session_state.df_datos = normalizar(pd.read_excel(xl_file), modo)
            st.rerun()

        if st.session_state.df_datos is not None:
            df_act = st.session_state.df_datos.copy()
            st.write("---")
            labs = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
            cols = st.columns(3); acts = [i for i, l in enumerate(labs) if cols[i%3].checkbox(l, value=True, key=f"r{i}")]
            ver_n = st.toggle("🏷️ Ver Nombres Fijos", value=True)
            m_ana = st.toggle("🔍 Tabla de Análisis", value=False)
            if m_ana: f_estatus = st.multiselect("Salud Zona:", ["🟢 Sano", "🟡 Desviado", "🔴 Crítico"], default=["🟢 Sano", "🟡 Desviado", "🔴 Crítico"])

    # --- 3. LÓGICA DE MAPA ---
    with col_m:
        if st.session_state.df_datos is not None:
            df_v = df_act[df_act['R_ID'].isin(acts)].copy()
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            clrs = {0:"#FFF", 1:"#FF0", 2:"#FFA500", 3:"#F00", 4:"#FF4500", 5:"#800000"}
            rep = []

            if 'LAT' in df_v.columns and 'LON' in df_v.columns:
                df_c = df_v[(df_v['LAT'] != 0) & (df_v['LON'] != 0)]
                if not df_c.empty:
                    m.fit_bounds([[df_c['LAT'].min(), df_c['LON'].min()], [df_c['LAT'].max(), df_c['LON'].max()]])
                    pts = df_c.to_dict('records')
                    for i, p1 in enumerate(pts):
                        otros = [p for j, p in enumerate(pts) if i != j]
                        ints = []
                        for p2 in otros:
                            dist = np.sqrt((p1['LAT']-p2['LAT'])**2 + ((p1['LON']-p2['LON'])*np.cos(np.radians(p1['LAT'])))**2) * 111139
                            if dist < (p1['RAD'] + p2['RAD']):
                                p_int = round((area_interseccion(p1['RAD'], p2['RAD'], dist) / (np.pi * p1['RAD']**2)) * 100, 1)
                                if p_int > 0: ints.append({"nom": p2['NOM'], "porc": p_int})
                        
                        tr_total_area = ints[0]['porc'] if len(ints) == 1 else round(calcular_traslape_real(p1, otros), 1)
                        det_txt = ", ".join([f"{n['nom']} ({n['porc']}%)" for n in ints]) if ints else "No traslapado"
                        suma_acum = sum([n['porc'] for n in ints])
                        
                        vol_act = p1['VOL']
                        pq_perdidos = vol_act * (suma_acum / 100)
                        salud = "🟢 Sano" if 30 <= vol_act <= 45 else "🟡 Desviado" if (20 <= vol_act < 30 or 45 < vol_act <= 55) else "🔴 Crítico"
                        
                        tip = f"<b>{p1['NOM']}</b><br>Paquetes: {int(vol_act)}<br>Traslape Real: {tr_total_area}%" if m_ana else f"<b>{p1['NOM']}</b><br>Vol: {int(vol_act)}"
                        folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=clrs[p1['R_ID']], fill=True, fill_opacity=0.35, tooltip=tip).add_to(m)
                        if ver_n: folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:9pt; font-weight:bold; color:#000; text-shadow: 0 0 2px #FFF; width:150px;">{p1["NOM"]}</div>')).add_to(m)
                        
                        rep.append({
                            "Salud": salud, "Zona": p1['NOM'], "Paquetes Actual": int(vol_act), 
                            "Paquetes Perdidos": round(pq_perdidos, 1),
                            "Potencial Ideal": round(vol_act + pq_perdidos, 1),
                            "% Traslape Real": f"{tr_total_area}%",
                            "% Acumulado": f"{round(suma_acum, 1)}%", 
                            "Detalle": det_txt
                        })

            mapa_html = m.get_root().render()
            components.html(mapa_html, height=550)
            
            c1, c2 = st.columns(2)
            with c1: st.download_button("🗺️ Mapa HTML", data=mapa_html, file_name="mapa_amzl.html", mime="text/html", use_container_width=True)
            with c2:
                if rep:
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='xlsxwriter') as wr: pd.DataFrame(rep).to_excel(wr, index=False)
                    st.download_button("📊 Informe Excel", data=buf.getvalue(), file_name="analisis.xlsx", use_container_width=True)
            
            if m_ana and rep:
                st.write("---")
                df_rep = pd.DataFrame(rep)
                st.dataframe(df_rep[df_rep['Salud'].isin(f_estatus)], use_container_width=True, hide_index=True)
