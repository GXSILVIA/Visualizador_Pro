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
import time
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

if 'dict_datos' not in st.session_state: st.session_state.dict_datos = {}
if 'reproduciendo' not in st.session_state: st.session_state.reproduciendo = False
if 'fec_slider_idx' not in st.session_state: st.session_state.fec_slider_idx = 0

def area_interseccion(r1, r2, d):
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return np.pi * min(r1, r2)**2
    p1 = r1**2 * np.arccos(np.clip((d**2 + r1**2 - r2**2) / (2 * d * r1), -1, 1))
    p2 = r2**2 * np.arccos(np.clip((d**2 + r2**2 - r1**2) / (2 * d * r2), -1, 1))
    p3 = 0.5 * np.sqrt(max(0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return p1 + p2 - p3

@st.cache_data
def cargar_capa_estado(archivo):
    ruta = f"mapas/{archivo}"
    if os.path.exists(ruta):
        gdf = gpd.read_file(ruta).to_crs("EPSG:4326")
        gdf['geometry'] = gdf['geometry'].simplify(0.002)
        col_geo = next((p for p in ['d_cp', 'CP', 'CODIGOPOSTAL', 'ZONA'] if p in gdf.columns), gdf.columns[0])
        return gdf, col_geo
    return None, None

# --- 2. SEGURIDAD ---
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, auth_status, username = authenticator.login(location='main')
except: st.error("Error en config.yaml"); st.stop()

if auth_status:
    def normalizar_df(df, modo_ref):
        df.columns = df.columns.str.strip().str.upper()
        mapa_cols = {'LAT':['LAT','LATITUD'],'LON':['LON','LONGITUD'],'VOL':['VOL','VOLUMEN'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA'],'PER':['PERSONA','RESPONSABLE'], 'FEC':['FECHA','DATE']}
        rename_dict = {c: k for k, v in mapa_cols.items() for c in df.columns if c in v}
        df = df.rename(columns=rename_dict)
        for c in ['LAT', 'LON', 'VOL']: df[c] = pd.to_numeric(df.get(c, 0), errors='coerce').fillna(0)
        df['RAD'] = pd.to_numeric(df.get('RAD', 750), errors='coerce').fillna(750)
        if 'FEC' in df.columns: df['FEC'] = pd.to_datetime(df['FEC'], errors='coerce')
        
        # Validación CP
        if 'CP' in df.columns:
            df['CP'] = df['CP'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
        else: df['CP'] = '00000'
        
        if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'Punto')
        if 'PER' not in df.columns: df['PER'] = "N/A"
        lim = [100, 200, 300, 400] if "Polígonos" in modo_ref else [15, 20, 30, 40]
        df['RANGO_ID'] = df['VOL'].apply(lambda v: next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0)
        return df

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
            fecha_sel = st.select_slider("🕒 Periodo:", options=list(st.session_state.dict_datos.keys()))
            df_act = st.session_state.dict_datos[fecha_sel].copy()
            
            if 'FEC' in df_act.columns and not df_act['FEC'].dropna().empty:
                if st.toggle("🕒 Modo Línea de Tiempo"):
                    lista_fec = sorted(df_act['FEC'].dropna().unique())
                    f_idx = st.session_state.fec_slider_idx
                    fec_actual = st.select_slider("Fecha", options=lista_fec, value=lista_fec[f_idx])
                    df_act = df_act[df_act['FEC'] <= fec_actual]

            activos = [i for i in range(6) if st.checkbox(f"Rango {i}", value=True, key=f"r_{i}_{fecha_sel}")]
            ver_nombres = st.toggle("🏷️ Ver Nombres", value=True)
            archivo_sel = st.selectbox("GeoJSON", sorted([f for f in os.listdir('mapas') if f.endswith('.geojson')])) if "Polígonos" in modo else None

    # --- 4. MAPA E INFORME ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act[(df_act['LAT'] != 0) & (df_act['LON'] != 0)].copy()
            m = folium.Map(location=[df_m['LAT'].mean(), df_m['LON'].mean()] if not df_m.empty else [19.4, -99.1], zoom_start=12, tiles="CartoDB Voyager")
            df_vis = df_m[df_m['RANGO_ID'].isin(activos)]
            
            # --- CÁLCULO DE EMPALMES ---
            dict_encimados = {}
            if not df_vis.empty:
                puntos = df_vis.to_dict('records')
                for i, p1 in enumerate(puntos):
                    area_p1 = np.pi * (p1['RAD']**2)
                    area_cubierta, encimado_con = 0, []
                    for j, p2 in enumerate(puntos):
                        if i == j: continue
                        dist = np.sqrt((p1['LAT']-p2['LAT'])**2 + (p1['LON']-p2['LON'])**2) * 111139
                        if dist < (p1['RAD'] + p2['RAD']):
                            a_int = area_interseccion(p1['RAD'], p2['RAD'], dist)
                            if a_int > 0:
                                area_cubierta += a_int
                                encimado_con.append(p2['PER'])
                    
                    porc = min(100, (area_cubierta / area_p1) * 100)
                    dict_encimados[p1['PER']] = {"Estatus": "🔴" if porc > 50 else "🟡" if porc > 15 else "🟢", "Porc": round(porc, 1), "Con": ", ".join(list(set(encimado_con))) if encimado_con else "Nadie"}

                # --- DIBUJAR ---
                COLORS = {0:"#FFF", 1:"#FF0", 2:"#F90", 3:"#F44", 4:"#F00", 5:"#600"}
                for _, f in df_vis.iterrows():
                    res = dict_encimados.get(f['PER'], {"Porc": 0})
                    color_txt = "red" if res["Porc"] > 50 else "black"
                    folium.Circle([f['LAT'], f['LON']], radius=f['RAD'], color=COLORS.get(f['RANGO_ID'], "#888"), fill=True, fill_opacity=0.3).add_to(m)
                    if ver_nombres:
                        folium.Marker([f['LAT'], f['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:{color_txt}; text-shadow: -1px -1px 0 #fff; width:150px;">{f["PER"]}</div>')).add_to(m)

                try: m.fit_bounds([[df_vis['LAT'].min(), df_vis['LON'].min()], [df_vis['LAT'].max(), df_vis['LON'].max()]])
                except: pass

            st_folium(m, width="100%", height=500, key=f"m_{fecha_sel}")

            # --- INFORME ---
            if modo_analisis:
                st.markdown("### 📊 Análisis de Empalmes")
                if dict_encimados:
                    df_rep = pd.DataFrame([{"Estatus": v["Estatus"], "Responsable": k, "% Encimado": f"{v['Porc']}%", "Encimado con": v["Con"]} for k, v in dict_encimados.items()])
                    
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as writer: df_rep.to_excel(writer, index=False)
                    st.download_button("📥 Descargar Reporte Excel", data=buf.getvalue(), file_name=f"analisis_{fecha_sel}.xlsx", use_container_width=True)
                    st.table(df_rep)
