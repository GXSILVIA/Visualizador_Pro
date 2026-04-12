#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap
import geopandas as gpd
import os
import io
import yaml
import numpy as np
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

if 'dict_datos' not in st.session_state: st.session_state.dict_datos = {}

def area_interseccion(r1, r2, d):
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return np.pi * min(r1, r2)**2
    p1 = r1**2 * np.arccos(np.clip((d**2 + r1**2 - r2**2) / (2 * d * r1), -1, 1))
    p2 = r2**2 * np.arccos(np.clip((d**2 + r2**2 - r1**2) / (2 * d * r2), -1, 1))
    p3 = 0.5 * np.sqrt(max(0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return p1 + p2 - p3

def obtener_rango_id(valor, modo_poligonos):
    # Lógica de cortes basada en labels: 100,200,300,400 o 15,20,30,40
    limites = [100, 200, 300, 400] if modo_poligonos else [15, 20, 30, 40]
    if valor <= 0: return 0
    for i, limite in enumerate(limites, 1):
        if valor <= limite: return i
    return 5

def normalizar_df(df, modo_ref):
    df.columns = df.columns.str.strip().str.upper()
    mapa_cols = {'LAT':['LAT','LATITUD'],'LON':['LON','LONGITUD'],'VOL':['VOL','VOLUMEN'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA'],'PER':['PERSONA','RESPONSABLE'], 'FEC':['FECHA','DATE']}
    rename_dict = {c: k for k, v in mapa_cols.items() for c in df.columns if c in v}
    df = df.rename(columns=rename_dict)
    
    for c in ['LAT', 'LON', 'VOL']: df[c] = pd.to_numeric(df.get(c, 0), errors='coerce').fillna(0)
    df['RAD'] = pd.to_numeric(df.get('RAD', 750), errors='coerce').fillna(750)
    
    if 'FEC' in df.columns:
        df['FEC'] = pd.to_datetime(df['FEC'], errors='coerce')
    
    if 'CP' in df.columns:
        df['CP'] = df['CP'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
    
    if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'ZONA-S/N')
    if 'PER' not in df.columns: df['PER'] = "N/A"
    
    es_poligono = "Polígonos" in modo_ref
    df['RANGO_ID'] = df['VOL'].apply(lambda x: obtener_rango_id(x, es_poligono))
    return df

# --- 2. SEGURIDAD ---
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, auth_status, username = authenticator.login(location='main')
except: st.error("Error en config.yaml o falta el archivo."); st.stop()

if auth_status:
    # --- 3. PANEL ---
    col_mapa, col_panel = st.columns([3, 1.3])
    with col_panel:
        st.title("🛡️ Panel AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP"])
        archivo_excel = st.file_uploader("📂 Cargar Datos", type=["xlsx"])
        
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            st.rerun()

        modo_analisis = st.toggle("🔍 Análisis Total", value=False)
        
        if st.session_state.dict_datos:
            fecha_sel = st.select_slider("🕒 Pestaña:", options=list(st.session_state.dict_datos.keys()))
            df_act = st.session_state.dict_datos[fecha_sel].copy()
            
            # Línea de tiempo segura
            if 'FEC' in df_act.columns:
                fechas_validas = sorted(df_act['FEC'].dropna().unique())
                if len(fechas_validas) > 1:
                    if st.toggle("🕒 Capa de Tiempo"):
                        f_slider = st.select_slider("Filtrar hasta:", options=fechas_validas)
                        df_act = df_act[df_act['FEC'] <= f_slider]

            labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
            activos = [i for i, lab in enumerate(labels) if st.checkbox(lab, value=True, key=f"r_{i}_{fecha_sel}")]
            ver_nombres = st.toggle("🏷️ Ver Nombres Fijos", value=True)

    # --- 4. MAPA E INFORME ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act[(df_act['LAT'] != 0) & (df_act['LON'] != 0)].copy()
            df_vis = df_m[df_m['RANGO_ID'].isin(activos)]
            
            m = folium.Map(location=[df_m['LAT'].mean(), df_m['LON'].mean()] if not df_m.empty else [19.4, -99.1], zoom_start=12, tiles="CartoDB Voyager")
            
            dict_reporte = []
            if not df_vis.empty:
                puntos = df_vis.to_dict('records')
                COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FFA500", 3:"#FF0000", 4:"#FF4500", 5:"#800000"}

                for i, p1 in enumerate(puntos):
                    area_p1 = np.pi * (p1['RAD']**2)
                    choques_info = []
                    total_empalme_p = 0
                    
                    for j, p2 in enumerate(puntos):
                        if i == j: continue
                        dist = np.sqrt((p1['LAT']-p2['LAT'])**2 + (p1['LON']-p2['LON'])**2) * 111139
                        if dist < (p1['RAD'] + p2['RAD']):
                            a_int = area_interseccion(p1['RAD'], p2['RAD'], dist)
                            if a_int > 0:
                                p_ind = round((a_int / area_p1) * 100, 1)
                                choques_info.append(f"{p2['NOM']} ({p_ind}%)")
                                total_empalme_p += p_ind

                    # Dibujar Círculo con Tooltip (incluye Volumen)
                    folium.Circle(
                        [p1['LAT'], p1['LON']], 
                        radius=p1['RAD'], 
                        color=COLORS.get(p1['RANGO_ID'], "#888"), 
                        fill=True, fill_opacity=0.35,
                        tooltip=f"<b>Zona:</b> {p1['NOM']}<br><b>Resp:</b> {p1['PER']}<br><b>Vol:</b> {int(p1['VOL'])}"
                    ).add_to(m)

                    # Nombres fijos en NEGRO (con sombra para lectura)
                    if ver_nombres:
                        folium.Marker(
                            [p1['LAT'], p1['LON']], 
                            icon=folium.features.DivIcon(html=f'<div style="font-size:9pt; font-weight:bold; color:black; text-shadow: 0px 0px 3px white; width:150px; pointer-events:none;">{p1["NOM"]}</div>')
                        ).add_to(m)

                    dict_reporte.append({
                        "Estatus": "🔴" if total_empalme_p > 50 else "🟡" if total_empalme_p > 15 else "🟢",
                        "Zona": p1['NOM'],
                        "Responsable": p1['PER'],
                        "% Traslape Total": f"{round(min(100, total_empalme_p), 1)}%",
                        "Empalmado con": ", ".join(choques_info) if choques_info else "Sin traslape"
                    })

                try: m.fit_bounds([[df_vis['LAT'].min(), df_vis['LON'].min()], [df_vis['LAT'].max(), df_vis['LON'].max()]])
                except: pass

            st_folium(m, width="100%", height=550, key=f"m_{fecha_sel}")

            if modo_analisis and dict_reporte:
                st.markdown("### 📊 Análisis Detallado de Empalmes")
                df_final = pd.DataFrame(dict_reporte)
                st.table(df_final)
