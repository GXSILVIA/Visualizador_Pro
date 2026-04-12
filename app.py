#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap
import geopandas as gpd
import os
import yaml
import numpy as np
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium

# --- 1. CONFIGURACIÓN Y FUNCIONES MATEMÁTICAS ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

if 'dict_datos' not in st.session_state: st.session_state.dict_datos = {}
if 'map_center' not in st.session_state: st.session_state.map_center = [19.4326, -99.1332]
if 'zona_seleccionada' not in st.session_state: st.session_state.zona_seleccionada = None

def area_interseccion(r1, r2, d):
    """Cálculo geométrico de intersección de dos círculos."""
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return np.pi * min(r1, r2)**2
    p1 = r1**2 * np.arccos((d**2 + r1**2 - r2**2) / (2 * d * r1))
    p2 = r2**2 * np.arccos((d**2 + r2**2 - r1**2) / (2 * d * r2))
    p3 = 0.5 * np.sqrt(max(0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return p1 + p2 - p3

# --- 2. SEGURIDAD ---
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, auth_status, username = authenticator.login(location='main')
except: 
    st.error("Error de configuración de seguridad."); st.stop()

if auth_status:
    def normalizar_df(df, modo_ref):
        df.columns = df.columns.str.strip().str.upper()
        mapa = {'LAT':['LAT','LATITUD'],'LON':['LON','LONGITUD'],'VOL':['VOL','VOLUMEN'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA'],'PER':['PERSONA','RESPONSABLE']}
        rename_dict = {c: k for k, v in mapa.items() for c in df.columns if c in v}
        df = df.rename(columns=rename_dict)
        df['VOL'] = pd.to_numeric(df.get('VOL',0), errors='coerce').fillna(0)
        df['RAD'] = pd.to_numeric(df.get('RAD',750), errors='coerce').fillna(750)
        if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'Punto')
        if 'PER' not in df.columns: df['PER'] = "N/A"
        
        def asignar_rango(v):
            if v <= 0: return 0
            lim = [100, 200, 300, 400] if "Polígonos" in modo_ref else [15, 20, 30, 40]
            for i, l in enumerate(lim, 1):
                if v <= l: return i
            return 5
        df['RANGO_ID'] = df['VOL'].apply(asignar_rango)
        df['COORD_KEY'] = df['LAT'].round(4).astype(str) + "," + df['LON'].round(4).astype(str)
        return df

    # --- 3. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3, 1.3])
    with col_controles:
        st.title("🛡️ Panel AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP", "Mapa de Calor"])
        
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            st.rerun()

        if st.session_state.dict_datos:
            periodos = list(st.session_state.dict_datos.keys())
            fecha_sel = st.select_slider("🕒 Historial:", options=periodos)
            df_act = st.session_state.dict_datos[fecha_sel]
            
            st.markdown("---")
            modo_analisis = st.toggle("🔍 Análisis de Intersección Total", value=False, help="Ignora rangos para buscar traslapes en toda la base.")
            
            stats = df_act.groupby('RANGO_ID')['VOL'].agg(['count', 'sum'])
            activos = []
            f1, f2 = st.columns(2)
            lbls = ["⚪ R0", "🟡 R1", "🟠 R2", "🔴 R3", "🏮 R4", "🍷 R5"]
            for i in range(6):
                n = int(stats.loc[i, 'count']) if i in stats.index else 0
                if (f1 if i < 3 else f2).checkbox(f"{lbls[i]} ({n})", value=True, key=f"r_{i}"): activos.append(i)
            
            ver_nombres = st.toggle("🏷️ Ver Nombres Fijos", value=True)

    # --- 4. RENDERIZADO MAPA ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act[df_act['RANGO_ID'].isin(activos)].copy()
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if "Calor" in modo:
                HeatMap([[f['LAT'], f['LON'], f['VOL']] for _, f in df_m.dropna(subset=['LAT', 'LON']).iterrows()], radius=50).add_to(m)
            else:
                df_visual = df_m.drop_duplicates('COORD_KEY')
                for _, f in df_visual.dropna(subset=['LAT', 'LON']).iterrows():
                    c = COLORS.get(f['RANGO_ID'], "#888")
                    folium.Circle(location=[f['LAT'], f['LON']], radius=f['RAD'], color=c, fill=True, fill_opacity=0.3, tooltip=f['NOM']).add_to(m)
                    if ver_nombres:
                        folium.Marker([f['LAT'], f['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; text-shadow: 2px 2px 3px #FFF;">{f["PER"]}</div>')).add_to(m)

            if not df_m.empty: m.fit_bounds([[df_m['LAT'].min(), df_m['LON'].min()], [df_m['LAT'].max(), df_m['LON'].max()]])
            map_output = st_folium(m, width="100%", height=500, key=f"map_{fecha_sel}")

            if map_output.get('last_object_clicked'):
                lat_c, lon_c = map_output['last_object_clicked']['lat'], map_output['last_object_clicked']['lng']
                df_act['dist_tmp'] = ((df_act['LAT'] - lat_c)**2 + (df_act['LON'] - lon_c)**2)**0.5
                st.session_state.zona_seleccionada = df_act.nsmallest(1, 'dist_tmp')['COORD_KEY'].iloc[0]
                st.rerun()

            # --- 5. INFORME DE TRASLAPES ---
            st.markdown("---")
            df_base = df_act if modo_analisis else df_m
            
            if st.session_state.zona_seleccionada:
                m_row = df_act[df_act['COORD_KEY'] == st.session_state.zona_seleccionada].iloc[0]
                df_calc = df_base.copy()
                df_calc['dist_m'] = (((df_calc['LAT'] - m_row['LAT'])**2 + (df_calc['LON'] - m_row['LON'])**2)**0.5) * 111139
                
                def get_pct(row):
                    a_int = area_interseccion(m_row['RAD'], row['RAD'], row['dist_m'])
                    return (a_int / (np.pi * min(m_row['RAD'], row['RAD'])**2)) * 100

                df_calc['%_ENCIMADO'] = df_calc.apply(get_pct, axis=1)
                df_reporte = df_calc[df_calc['%_ENCIMADO'] >= 30].sort_values('%_ENCIMADO', ascending=False)

                if not df_reporte.empty:
                    dups = df_reporte[df_reporte['%_ENCIMADO'] >= 99.9]
                    if len(dups) > 1: st.error(f"🚨 **DUPLICIDAD DETECTADA:** {len(dups)} círculos al 100%.")
                    
                    c1, c2 = st.columns([1, 2])
                    c1.bar_chart(df_reporte.groupby('PER')['VOL'].sum())
                    if c1.button("🗑️ Limpiar"): 
                        st.session_state.zona_seleccionada = None; st.rerun()
                    
                    def estilo(v):
                        if v >= 99.9: return 'background-color: #721c24; color: white'
                        if v >= 80: return 'background-color: #ff4b4b'
                        return 'background-color: #f1c40f'

                    c2.dataframe(df_reporte[['NOM', 'PER', 'VOL', '%_ENCIMADO']].style.applymap(estilo, subset=['%_ENCIMADO']).format({'%_ENCIMADO': '{:.1f}%'}), use_container_width=True)
            else:
                st.info("👆 Selecciona un punto para analizar intersecciones.")

elif auth_status is False: st.error('Credenciales incorrectas')
elif auth_status is None: st.warning('Ingrese credenciales')
