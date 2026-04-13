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
        gdf['geometry'] = gdf['geometry'].simplify(0.002)
        col_cp = next((c for c in ['d_cp', 'CP', 'CODIGOPOSTAL'] if c in gdf.columns), gdf.columns[0])
        # Buscamos columna de estado
        col_edo = next((c for c in ['NOM_ENT', 'ESTADO', 'ENTIDAD', 'd_estado'] if c in gdf.columns), None)
        return gdf, col_cp, col_edo
    return None, None, None

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
except: st.error("Error en config.yaml"); st.stop()

if auth_status:
    col_mapa, col_panel = st.columns([3, 1.3])
    
    with col_panel:
        st.title("🛡️ Panel AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP", "Línea de Tiempo"])
        
        # PLANTILLAS
        st.subheader("📥 Plantillas")
        cols_p = {"Coordenadas": ["ZONA", "LATITUD", "LONGITUD", "RADIO", "VOLUMEN"],
                  "Polígonos CP": ["ZONA", "CP", "VOLUMEN"],
                  "Línea de Tiempo": ["ZONA", "LATITUD", "LONGITUD", "RADIO", "VOLUMEN", "FECHA"]}
        buf_p = io.BytesIO()
        pd.DataFrame(columns=cols_p[modo]).to_excel(buf_p, index=False)
        st.download_button(f"Base: {modo}", data=buf_p.getvalue(), file_name=f"base_{modo.lower()}.xlsx", use_container_width=True)

        archivo_excel = st.file_uploader("📂 Cargar Datos", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            st.session_state.fec_slider_idx = 0
            st.session_state.reproduciendo = False
            st.rerun()

        # CONTROLES SIEMPRE VISIBLES
        gdf_filtrado, col_cp_geo, limites_estado = None, None, None
        if st.session_state.dict_datos:
            lista_p = list(st.session_state.dict_datos.keys())
            fecha_sel = st.select_slider("🕒 Pestaña:", options=lista_p) if len(lista_p) > 1 else lista_p[0]
            df_act = st.session_state.dict_datos[fecha_sel].copy()
            
            # --- CONTROL DE TIEMPO (PLAY) ---
            vel = 1.0
            if modo == "Línea de Tiempo" and 'FEC' in df_act.columns:
                f_v = sorted(df_act['FEC'].dropna().unique())
                if len(f_v) > 1:
                    st.write("### 🎬 Modo Cine")
                    c1, c2, c3 = st.columns(3)
                    if c1.button("▶️ Play"): st.session_state.reproduciendo = True
                    if c2.button("⏸️ Stop"): st.session_state.reproduciendo = False
                    vel = c3.select_slider("Vel:", options=[0.5, 1.0, 2.0, 4.0], value=1.0, label_visibility="collapsed")
                    
                    st.session_state.fec_slider_idx = st.select_slider("Periodo:", options=range(len(f_v)), 
                                                                      format_func=lambda x: f_v[x].strftime('%Y-%m-%d'),
                                                                      value=st.session_state.fec_slider_idx)
                    df_act = df_act[df_act['FEC'] <= f_v[st.session_state.fec_slider_idx]]

            st.write("---")
            # RANGOS 3x3
            labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
            activos = []
            cols_r = st.columns(3)
            for i, lab in enumerate(labels):
                with cols_r[i % 3]:
                    if st.checkbox(lab, value=True, key=f"r_{i}_{fecha_sel}"): activos.append(i)

            ver_nombres = st.toggle("🏷️ Ver Nombres Fijos", value=True)
            modo_analisis = st.toggle("🔍 Tabla de Análisis", value=False)
            
            # NUEVO FILTRO DE ESTADO PARA POLÍGONOS
            archivo_geojson = st.selectbox("🗺️ GeoJSON", sorted([f for f in os.listdir('mapas') if f.endswith('.geojson')])) if "Polígonos" in modo else None
            if "Polígonos" in modo and archivo_geojson:
                gdf_completo, col_cp_geo, col_edo_geo = cargar_capa_geojson(archivo_geojson)
                if gdf_completo is not None:
                    if col_edo_geo:
                        lista_edos = sorted(gdf_completo[col_edo_geo].unique().tolist())
                        edo_sel = st.selectbox("📍 Filtrar por Estado:", ["Todos"] + lista_edos)
                        if edo_sel != "Todos":
                            gdf_filtrado = gdf_completo[gdf_completo[col_edo_geo] == edo_sel]
                            b = gdf_filtrado.total_bounds
                            limites_estado = [[b[1], b[0]], [b[3], b[2]]] # [miny, minx], [maxy, maxx]
                        else:
                            gdf_filtrado = gdf_completo
                    else:
                        gdf_filtrado = gdf_completo

    # --- 3. MAPA Y DESCARGAS ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_vis = df_act[df_act['RANGO_ID'].isin(activos)]
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FFA500", 3:"#FF0000", 4:"#FF4500", 5:"#800000"}

            # CAPA: POLÍGONOS CP (CON FILTRO DE ESTADO Y AUTO-ZOOM)
            if "Polígonos" in modo and gdf_filtrado is not None:
                if limites_estado: m.fit_bounds(limites_estado)
                for _, row in gdf_filtrado.iterrows():
                    cp_val = str(row[col_cp_geo]).zfill(5)
                    match = df_vis[df_vis['CP'] == cp_val]
                    if not match.empty:
                        v = match.iloc[0]['VOL']
                        folium.GeoJson(
                            row['geometry'], 
                            style_function=lambda x, r=obtener_rango_id(v, True): {
                                'fillColor': COLORS.get(r, "#888"), 'color': 'black', 'weight': 1, 'fillOpacity': 0.5
                            },
                            tooltip=f"Zona: {match.iloc[0]['NOM']} | Vol: {int(v)}"
                        ).add_to(m)

            # CAPA: CÍRCULOS (COORDENADAS Y TIEMPO)
            df_coords = df_vis[(df_vis['LAT'] != 0) & (df_vis['LON'] != 0)]
            dict_reporte = []
            
            if not df_coords.empty:
                if "Polígonos" not in modo: # Solo auto-zoom si no estamos en modo polígonos filtrados
                    m.fit_bounds([df_coords[['LAT', 'LON']].min().values.tolist(), df_coords[['LAT', 'LON']].max().values.tolist()])
                
                pts = df_coords.to_dict('records')
                for i, p1 in enumerate(pts):
                    area_p1 = np.pi * (p1['RAD']**2)
                    choques, total_p = [], 0
                    for j, p2 in enumerate(pts):
                        if i == j: continue
                        d = np.sqrt((p1['LAT']-p2['LAT'])**2 + (p1['LON']-p2['LON'])**2) * 111139
                        if d < (p1['RAD'] + p2['RAD']):
                            a = area_interseccion(p1['RAD'], p2['RAD'], d)
                            if a > 0:
                                pi = round((a / area_p1) * 100, 1)
                                choques.append(f"{p2['NOM']} ({pi}%)")
                                total_p += pi
                    
                    folium.Circle(
                        [p1['LAT'], p1['LON']], radius=p1['RAD'], 
                        color=COLORS.get(p1['RANGO_ID'], "#888"), 
                        fill=True, fill_opacity=0.35, 
                        tooltip=f"Zona: {p1['NOM']} | Vol: {int(p1['VOL'])}"
                    ).add_to(m)
                    
                    if ver_nombres:
                        folium.Marker(
                            [p1['LAT'], p1['LON']], 
                            icon=folium.features.DivIcon(html=f'<div style="font-size:9pt; font-weight:bold; color:black; text-shadow: 0px 0px 3px white; width:150px; pointer-events:none;">{p1["NOM"]}</div>')
                        ).add_to(m)
                    
                    dict_reporte.append({
                        "Estatus": "🔴" if total_p > 50 else "🟡" if total_p > 15 else "🟢", 
                        "Zona": p1['NOM'], 
                        "% Traslape Total": f"{round(min(100, total_p), 1)}%", 
                        "Empalmado con": ", ".join(choques) if choques else "Sin traslape"
                    })

            st_folium(m, width="100%", height=550, key="mapa_operativo_fijo")

            # SECCIÓN: DESCARGAS
            c_d1, c_d2 = st.columns(2)
            with c_d1:
                map_io = io.BytesIO()
                m.save(map_io, close_file=False)
                st.download_button("🗺️ Mapa HTML", data=map_io.getvalue(), file_name="mapa_amzl.html", use_container_width=True)
            with c_d2:
                if dict_reporte:
                    buf_r = io.BytesIO()
                    pd.DataFrame(dict_reporte).to_excel(buf_r, index=False)
                    st.download_button("📊 Informe Excel", data=buf_r.getvalue(), file_name="analisis.xlsx", use_container_width=True)
            
            if modo_analisis and dict_reporte:
                st.table(pd.DataFrame(dict_reporte))

    # --- 4. LÓGICA DE REPRODUCCIÓN ---
    if st.session_state.reproduciendo:
        f_v = sorted(st.session_state.dict_datos[fecha_sel]['FEC'].dropna().unique())
        if st.session_state.fec_slider_idx < len(f_v) - 1:
            st.session_state.fec_slider_idx += 1
            time.sleep(1.0 / vel) 
            st.rerun()
        else:
            st.session_state.reproduciendo = False
            st.rerun()
