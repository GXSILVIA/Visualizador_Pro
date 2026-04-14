
#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os
import io
import yaml
import numpy as np
import time
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium

# --- 1. CONFIGURACIÓN INICIAL ---
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

def calcular_traslape_real(p1, otros_pts):
    """Calcula el porcentaje de área de p1 cubierto por la unión de otros círculos (Monte Carlo 2000 pts)."""
    if not otros_pts: return 0.0
    n_muestras = 2000 # Precisión quirúrgica aumentada
    angulos = np.random.uniform(0, 2*np.pi, n_muestras)
    radios = np.sqrt(np.random.uniform(0, 1, n_muestras)) * p1['RAD']
    dx = radios * np.cos(angulos)
    dy = radios * np.sin(angulos)
    m_a_grado = 111139
    puntos_lat = p1['LAT'] + (dy / m_a_grado)
    puntos_lon = p1['LON'] + (dx / (m_a_grado * np.cos(np.radians(p1['LAT']))))
    cubiertos = np.zeros(n_muestras, dtype=bool)
    for p2 in otros_pts:
        dist_sq = ((puntos_lat - p2['LAT'])**2 + 
                   ((puntos_lon - p2['LON']) * np.cos(np.radians(p1['LAT'])))**2) * (m_a_grado**2)
        cubiertos |= (dist_sq <= p2['RAD']**2)
        if cubiertos.all(): return 100.0
    return (np.sum(cubiertos) / n_muestras) * 100

def obtener_rango_id(valor, modo_poligonos):
    limites = [100, 200, 300, 400] if modo_poligonos else [15, 20, 30, 40]
    if valor <= 0: return 0
    for i, limite in enumerate(limites, 1):
        if valor <= limite: return i
    return 5

@st.cache_data
def cargar_capa_geojson(archivo):
    ruta = f"mapas/{archivo}"
    if os.path.exists(ruta):
        gdf = gpd.read_file(ruta).to_crs("EPSG:4326")
        gdf['geometry'] = gdf['geometry'].simplify(0.001)
        col_cp = next((c for c in ['d_cp', 'CP', 'CODIGOPOSTAL', 'cp', 'id', 'postal_code'] if c in gdf.columns), gdf.columns[0])
        return gdf, col_cp
    return None, None

def normalizar_df(df, modo_ref):
    df.columns = df.columns.str.strip().str.upper()
    mapa_cols = {'LAT':['LAT','LATITUD'],'LON':['LON','LONGITUD'],'VOL':['VOL','VOLUMEN'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA'], 'FEC':['FECHA','DATE']}
    rename_dict = {c: k for k, v in mapa_cols.items() for c in df.columns if c in v}
    df = df.rename(columns=rename_dict)
    for c in ['LAT', 'LON', 'VOL', 'RAD']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    if 'RAD' not in df.columns or (df['RAD'] == 0).all(): df['RAD'] = 750
    if 'FEC' in df.columns: df['FEC'] = pd.to_datetime(df['FEC'], errors='coerce')
    if 'CP' in df.columns: df['CP'] = df['CP'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
    if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'ZONA-S/N')
    df['RANGO_ID'] = df['VOL'].apply(lambda x: obtener_rango_id(x, "Polígonos" in modo_ref))
    return df

# --- 2. SEGURIDAD ---
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, auth_status, username = authenticator.login(location='main')
except: st.error("Error en config.yaml"); st.stop()

if auth_status:
    col_mapa, col_panel = st.columns([3, 1.3])
    with col_panel:
        st.title("🛡️ Panel AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP", "Línea de Tiempo"])
        
        gdf_filtrado, col_cp_geo, limites_estado = None, None, None
        if "Polígonos" in modo:
            archivos_geo = sorted([f for f in os.listdir('mapas') if f.endswith('.geojson')])
            nombres_edos = [f.replace('.geojson', '').replace('_', ' ') for f in archivos_geo]
            estado_sel = st.selectbox("📍 Seleccionar Estado:", nombres_edos)
            if estado_sel:
                archivo_real = archivos_geo[nombres_edos.index(estado_sel)]
                gdf_filtrado, col_cp_geo = cargar_capa_geojson(archivo_real)
                if gdf_filtrado is not None:
                    b = gdf_filtrado.total_bounds
                    limites_estado = [[b[1], b[0]], [b[3], b[2]]]

        st.subheader("📥 Datos")
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            st.rerun()

        if st.session_state.dict_datos:
            lista_p = list(st.session_state.dict_datos.keys())
            fecha_sel = st.select_slider("🕒 Pestaña:", options=lista_p) if len(lista_p) > 1 else lista_p[0]
            df_act = st.session_state.dict_datos[fecha_sel].copy()
            
            st.write("---")
            labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
            activos = []
            cols_r = st.columns(3)
            for i, lab in enumerate(labels):
                with cols_r[i % 3]:
                    if st.checkbox(lab, value=True, key=f"r_{i}_{fecha_sel}"): activos.append(i)
            ver_nombres = st.toggle("🏷️ Ver Nombres Fijos", value=True)
            modo_analisis = st.toggle("🔍 Tabla de Análisis", value=False)

    with col_mapa:
        if st.session_state.dict_datos:
            df_vis = df_act[df_act['RANGO_ID'].isin(activos)].copy()
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FFA500", 3:"#FF0000", 4:"#FF4500", 5:"#800000"}

            if "Polígonos" in modo and gdf_filtrado is not None:
                if limites_estado: m.fit_bounds(limites_estado)
                df_vis['CP_KEY'] = df_vis['CP'].astype(str).str.strip().str.zfill(5)
                dict_vol = pd.Series(df_vis.VOL.values, index=df_vis.CP_KEY).to_dict()
                dict_nom = pd.Series(df_vis.NOM.values, index=df_vis.CP_KEY).to_dict()
                for _, row in gdf_filtrado.iterrows():
                    cp_geo = str(row[col_cp_geo]).strip().zfill(5)
                    if cp_geo in dict_vol:
                        v, n = dict_vol[cp_geo], dict_nom[cp_geo]
                        folium.GeoJson(row['geometry'], 
                            style_function=lambda x, r=obtener_rango_id(v, True): {'fillColor': COLORS.get(r, "#888"), 'color': 'black', 'weight': 1, 'fillOpacity': 0.6},
                            tooltip=f"<b>Zona:</b> {n}<br><b>Volumen:</b> {int(v)}").add_to(m)
                        if ver_nombres:
                            c = row['geometry'].centroid
                            folium.Marker([c.y, c.x], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; text-align:center; width:80px; text-shadow: 0px 0px 3px white;">{n}</div>')).add_to(m)

            dict_reporte = []
            if 'LAT' in df_vis.columns and 'LON' in df_vis.columns:
                df_coords = df_vis[(df_vis['LAT'] != 0) & (df_vis['LON'] != 0)]
                if not df_coords.empty:
                    if "Polígonos" not in modo: m.fit_bounds([df_coords[['LAT', 'LON']].min().tolist(), df_coords[['LAT', 'LON']].max().tolist()])
                    pts = df_coords.to_dict('records')
                    for i, p1 in enumerate(pts):
                        otros = [p for j, p in enumerate(pts) if i != j]
                        choques = []
                        for p2 in otros:
                            d = np.sqrt((p1['LAT']-p2['LAT'])**2 + (p1['LON']-p2['LON'])**2) * 111139
                            if d < (p1['RAD'] + p2['RAD']):
                                a = area_interseccion(p1['RAD'], p2['RAD'], d)
                                if a > 0: choques.append(f"{p2['NOM']} ({round((a/(np.pi*p1['RAD']**2))*100,1)}%)")
                        
                        porc_total = calcular_traslape_real(p1, otros)
                        folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], 
                            color=COLORS.get(p1['RANGO_ID'], "#888"), fill=True, fill_opacity=0.35,
                            tooltip=f"<b>Zona:</b> {p1['NOM']}<br><b>Volumen:</b> {int(p1['VOL'])}").add_to(m)
                        if ver_nombres:
                            folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:9pt; font-weight:bold; color:black; text-shadow: 0px 0px 3px white; width:150px;">{p1["NOM"]}</div>')).add_to(m)
                        dict_reporte.append({"Estatus": "🔴" if porc_total > 50 else "🟡" if porc_total > 15 else "🟢", "Zona": p1['NOM'], "% Traslape Real": f"{round(porc_total, 1)}%", "Detalle": ", ".join(choques)})

            st_folium(m, width="100%", height=550, key="mapa_fijo")
            if dict_reporte:
                c1, c2 = st.columns(2)
                with c1: st.download_button("🗺️ Mapa HTML", data=io.BytesIO(m._repr_html_().encode()).getvalue(), file_name="mapa.html", use_container_width=True)
                with c2:
                    buf_r = io.BytesIO(); pd.DataFrame(dict_reporte).to_excel(buf_r, index=False)
                    st.download_button("📊 Informe Excel", data=buf_r.getvalue(), file_name="analisis.xlsx", use_container_width=True)
                if modo_analisis: st.table(pd.DataFrame(dict_reporte))
