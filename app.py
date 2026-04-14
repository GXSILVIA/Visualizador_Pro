
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
    if len(df) > 2000:
        st.warning("⚠️ Limitado a 2,000 filas.")
        df = df.head(2000)
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
except: st.error("Error en config.yaml o login"); st.stop()

if auth_status:
    col_mapa, col_panel = st.columns([3, 1.3])
    
    with col_panel:
        st.title("🛡️ Panel AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP", "Línea de Tiempo"])
        
        # --- FILTRO DE ESTADO ---
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
        archivo_excel = st.file_uploader("📂 Cargar XLSX", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            st.session_state.fec_slider_idx = 0
            st.rerun()

        if st.session_state.dict_datos:
            lista_p = list(st.session_state.dict_datos.keys())
            fecha_sel = st.select_slider("🕒 Pestaña:", options=lista_p) if len(lista_p) > 1 else lista_p[0]
            df_act = st.session_state.dict_datos[fecha_sel].copy()
            
            st.write("---")
            # --- RANGOS 3x3 RESTAURADO ---
            labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
            activos = []
            cols_r = st.columns(3)
            for i, lab in enumerate(labels):
                with cols_r[i % 3]:
                    if st.checkbox(lab, value=True, key=f"r_{i}_{fecha_sel}"): activos.append(i)

            ver_nombres = st.toggle("🏷️ Ver Nombres Fijos", value=True)
            modo_analisis = st.toggle("🔍 Tabla de Análisis", value=False)

    # --- 3. MAPA Y ANÁLISIS ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_vis = df_act[df_act['RANGO_ID'].isin(activos)].copy()
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FFA500", 3:"#FF0000", 4:"#FF4500", 5:"#800000"}

            # CAPA POLÍGONOS
            if "Polígonos" in modo and gdf_filtrado is not None:
                if limites_estado: m.fit_bounds(limites_estado)
                df_vis['CP_KEY'] = df_vis['CP'].astype(str).str.strip().str.zfill(5)
                dict_vol = pd.Series(df_vis.VOL.values, index=df_vis.CP_KEY).to_dict()
                dict_nom = pd.Series(df_vis.NOM.values, index=df_vis.CP_KEY).to_dict()

                for _, row in gdf_filtrado.iterrows():
                    cp_geo = str(row[col_cp_geo]).strip().zfill(5)
                    if cp_geo in dict_vol:
                        v = dict_vol[cp_geo]
                        folium.GeoJson(row['geometry'],
                            style_function=lambda x, r=obtener_rango_id(v, True): {
                                'fillColor': COLORS.get(r, "#888"), 'color': 'black', 'weight': 1, 'fillOpacity': 0.6
                            },
                            tooltip=f"Zona: {dict_nom[cp_geo]} | Vol: {int(v)}"
                        ).add_to(m)
                        if ver_nombres:
                            centroid = row['geometry'].centroid
                            folium.Marker([centroid.y, centroid.x], 
                                icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:black; text-align:center; width:80px; text-shadow: 0px 0px 3px white;">{dict_nom[cp_geo]}</div>')
                            ).add_to(m)

            # CAPA CÍRCULOS Y CORRECCIÓN DE TRASLAPE
            dict_reporte = []
            if 'LAT' in df_vis.columns and 'LON' in df_vis.columns:
                df_coords = df_vis[(df_vis['LAT'] != 0) & (df_vis['LON'] != 0)]
                if not df_coords.empty:
                    if "Polígonos" not in modo:
                        m.fit_bounds([df_coords[['LAT', 'LON']].min().tolist(), df_coords[['LAT', 'LON']].max().tolist()])
                    
                    pts = df_coords.to_dict('records')
                    for i, p1 in enumerate(pts):
                        area_p1 = np.pi * (p1['RAD']**2)
                        choques, suma_areas = [], 0
                        for j, p2 in enumerate(pts):
                            if i == j: continue
                            # Distancia en metros (aproximada)
                            d = np.sqrt((p1['LAT']-p2['LAT'])**2 + (p1['LON']-p2['LON'])**2) * 111139
                            if d < (p1['RAD'] + p2['RAD']):
                                a = area_interseccion(p1['RAD'], p2['RAD'], d)
                                if a > 0:
                                    suma_areas += a
                                    pi = round((a / area_p1) * 100, 1)
                                    choques.append(f"{p2['NOM']} ({pi}%)")
                        
                        # --- CORRECCIÓN DE TOTAL ---
                        # Para evitar que supere 100% erróneamente por múltiples traslapes
                        porc_total = min(98.5 if any(d > 20 for d in [np.sqrt((p1['LAT']-p2['LAT'])**2 + (p1['LON']-p2['LON'])**2)*111139 for j, p2 in enumerate(pts) if i!=j]) else 100, (suma_areas / area_p1) * 100)
                        
                        folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=COLORS.get(p1['RANGO_ID'], "#888"), fill=True, fill_opacity=0.35).add_to(m)
                        if ver_nombres:
                            folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:9pt; font-weight:bold; color:black; text-shadow: 0px 0px 3px white; width:150px;">{p1["NOM"]}</div>')).add_to(m)
                        
                        dict_reporte.append({
                            "Estatus": "🔴" if porc_total > 50 else "🟡" if porc_total > 15 else "🟢",
                            "Zona": p1['NOM'],
                            "% Traslape Total": f"{round(porc_total, 1)}%",
                            "Detalle": ", ".join(choques) if choques else "Sin traslape"
                        })

            st_folium(m, width="100%", height=550, key="mapa_fijo")

            # --- DESCARGAS ---
            c1, c2 = st.columns(2)
            with c1:
                map_io = io.BytesIO(); m.save(map_io, close_file=False)
                st.download_button("🗺️ Mapa HTML", data=map_io.getvalue(), file_name="mapa.html", use_container_width=True)
            with c2:
                if dict_reporte:
                    buf_r = io.BytesIO(); pd.DataFrame(dict_reporte).to_excel(buf_r, index=False)
                    st.download_button("📊 Informe Excel", data=buf_r.getvalue(), file_name="analisis.xlsx", use_container_width=True)
            
            if modo_analisis and dict_reporte:
                st.table(pd.DataFrame(dict_reporte))

    # --- REPRODUCCIÓN ---
    if st.session_state.reproduciendo:
        f_v = sorted(st.session_state.dict_datos[fecha_sel]['FEC'].dropna().unique())
        if st.session_state.fec_slider_idx < len(f_v) - 1:
            st.session_state.fec_slider_idx += 1
            time.sleep(1.0); st.rerun()
        else: st.session_state.reproduciendo = False; st.rerun()
