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

# --- 1. CONFIGURACIÓN Y FUNCIONES ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

if 'dict_datos' not in st.session_state: st.session_state.dict_datos = {}
if 'zona_seleccionada' not in st.session_state: st.session_state.zona_seleccionada = None

def area_interseccion(r1, r2, d):
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return np.pi * min(r1, r2)**2
    p1 = r1**2 * np.arccos((d**2 + r1**2 - r2**2) / (2 * d * r1))
    p2 = r2**2 * np.arccos((d**2 + r2**2 - r1**2) / (2 * d * r2))
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
except: st.error("Error de configuración de seguridad."); st.stop()

if auth_status:
    def normalizar_df(df, modo_ref):
        df.columns = df.columns.str.strip().str.upper()
        mapa = {'LAT':['LAT','LATITUD'],'LON':['LON','LONGITUD'],'VOL':['VOL','VOLUMEN'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA'],'PER':['PERSONA','RESPONSABLE']}
        rename_dict = {c: k for k, v in mapa.items() for c in df.columns if c in v}
        df = df.rename(columns=rename_dict)
        df['VOL'] = pd.to_numeric(df.get('VOL',0), errors='coerce').fillna(0)
        df['RAD'] = pd.to_numeric(df.get('RAD',750), errors='coerce').fillna(750)
        df['CP'] = df.get('CP', '0').astype(str).str.zfill(5)
        if 'NOM' not in df.columns: df['NOM'] = df['CP']
        if 'PER' not in df.columns: df['PER'] = "N/A"
        
        # --- RANGOS SEGÚN TU LÓGICA ---
        lim = [100, 200, 300, 400] if "Polígonos" in modo_ref else [15, 20, 30, 40]
        df['RANGO_ID'] = df['VOL'].apply(lambda v: next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0)
        df['COORD_KEY'] = df['LAT'].round(4).astype(str) + "," + df['LON'].round(4).astype(str)
        return df

    # --- 3. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3, 1.3])
    with col_controles:
        st.title("🛡️ Panel AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            pd.DataFrame(columns=['LAT', 'LON', 'VOL', 'RAD', 'CP', 'NOMBRE', 'RESPONSABLE']).to_excel(writer, index=False)
        st.download_button("📥 Descargar Plantilla", data=buffer.getvalue(), file_name="plantilla_amzl.xlsx")

        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP", "Mapa de Calor"])
        archivo_excel = st.file_uploader("📂 Cargar Datos", type=["xlsx"])
        
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            st.rerun()

        if st.session_state.dict_datos:
            fecha_sel = st.select_slider("🕒 Periodos:", options=list(st.session_state.dict_datos.keys()))
            df_act = st.session_state.dict_datos[fecha_sel]
            modo_analisis = st.toggle("🔍 Análisis Intersección Total", value=False)
            
            # --- ETIQUETAS PERSONALIZADAS ---
            if "Polígonos" in modo:
                labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"]
            else:
                labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
            
            activos = []
            f1, f2 = st.columns(2)
            for i in range(6):
                if (f1 if i < 3 else f2).checkbox(labels[i], value=True, key=f"r_{i}"): activos.append(i)
            
            ver_nombres = st.toggle("🏷️ Ver Nombres", value=True)
            archivo_sel = st.selectbox("GeoJSON", sorted([f for f in os.listdir('mapas') if f.endswith(('.json', '.geojson'))])) if "Polígonos" in modo else None

    # --- 4. MAPA ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act[df_act['RANGO_ID'].isin(activos)].copy()
            m = folium.Map(location=[df_m['LAT'].mean(), df_m['LON'].mean()], zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if "Calor" in modo:
                HeatMap(df_m[['LAT', 'LON', 'VOL']].dropna()).add_to(m)
            elif "Polígonos" in modo and archivo_sel:
                gdf, col_geo = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    merged = gdf.merge(df_m, left_on=col_geo, right_on='CP')
                    for _, f in merged.iterrows():
                        c = COLORS.get(f['RANGO_ID'], "#888")
                        folium.GeoJson(f['geometry'], style_function=lambda x, col=c: {'fillColor':col, 'color':'#444', 'fillOpacity':0.5, 'weight':1},
                                       tooltip=f"CP: {f['CP']} | Vol: {f['VOL']}").add_to(m)
            else:
                for _, f in df_m.drop_duplicates('COORD_KEY').iterrows():
                    c = COLORS.get(f['RANGO_ID'], "#888")
                    folium.Circle([f['LAT'], f['LON']], radius=f['RAD'], color=c, fill=True, fill_opacity=0.3, tooltip=f['NOM']).add_to(m)
                    if ver_nombres:
                        folium.Marker([f['LAT'], f['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; width:120px;">{f["PER"]}</div>')).add_to(m)

            map_out = st_folium(m, width="100%", height=550, key="map_amzl")
            if map_out.get('last_object_clicked'):
                lc = map_out['last_object_clicked']
                df_act['d_tmp'] = ((df_act['LAT']-lc['lat'])**2 + (df_act['LON']-lc['lng'])**2)**0.5
                st.session_state.zona_seleccionada = df_act.nsmallest(1, 'd_tmp')['COORD_KEY'].iloc[0]
                st.rerun()

            # --- 5. INFORME ---
            st.markdown("---")
            df_base = df_act if modo_analisis else df_m
            if st.session_state.zona_seleccionada:
                m_row = df_act[df_act['COORD_KEY'] == st.session_state.zona_seleccionada].iloc[0]
                df_calc = df_base.copy()
                df_calc['dist_m'] = (((df_calc['LAT'] - m_row['LAT'])**2 + (df_calc['LON'] - m_row['LON'])**2)**0.5) * 111139
                df_calc['%_ENCIMADO'] = df_calc.apply(lambda r: (area_interseccion(m_row['RAD'], r['RAD'], r['dist_m']) / (np.pi * min(m_row['RAD'], r['RAD'])**2)) * 100, axis=1)
                df_rep = df_calc[df_calc['%_ENCIMADO'] >= 30].sort_values('%_ENCIMADO', ascending=False)

                if not df_rep.empty:
                    if len(df_rep[df_rep['%_ENCIMADO'] >= 99]) > 1: st.error("🚨 DUPLICIDAD AL 100% DETECTADA")
                    c1, c2 = st.columns()
                    c1.bar_chart(df_rep.groupby('PER')['VOL'].sum())
                    def est(v): return 'background-color: #721c24; color: white' if v >= 99 else ('background-color: #ff4b4b' if v >= 80 else ('background-color: #ffa500' if v >= 50 else 'background-color: #f1c40f'))
                    c2.dataframe(df_rep[['NOM', 'PER', 'VOL', '%_ENCIMADO']].style.applymap(est, subset=['%_ENCIMADO']).format({'%_ENCIMADO': '{:.1f}%'}), use_container_width=True, hide_index=True)
                    if st.button("🗑️ Limpiar"): st.session_state.zona_seleccionada = None; st.rerun()
            else: st.info("👆 Selecciona un punto para ver traslapes.")

elif auth_status is False: st.error('Credenciales incorrectas')
elif auth_status is None: st.warning('Ingrese credenciales')
