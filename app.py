#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap, Geocoder
import geopandas as gpd
import os
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium
from datetime import datetime

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

if 'map_center' not in st.session_state: st.session_state.map_center = [19.4326, -99.1332]
if 'dict_datos' not in st.session_state: st.session_state.dict_datos = {}

try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, auth_status, username = authenticator.login(location='main')
except: st.stop()

if auth_status:
    # --- 2. PROCESAMIENTO INTELIGENTE (SIN ERRORES DE DICCIONARIO) ---
    def normalizar_df(df, modo_ref):
        df.columns = df.columns.str.strip().str.upper()
        cols = df.columns
        
        mapa = {
            'LAT': ['LAT', 'LATITUD', 'LATITUDES'],
            'LON': ['LON', 'LONGITUD', 'LGT', 'LONGITUDES'],
            'VOL': ['VOL', 'VOLUMEN', 'CANTIDAD', 'PESO'],
            'RAD': ['RADIO', 'RAD', 'SIZE'],
            'CP':  ['CP', 'C.P.', 'CODIGO POSTAL', 'CODIGO_POSTAL'],
            'NOM': ['NOMBRE', 'ZONA', 'AREA', 'UBICACION']
        }
        
        rename_dict = {}
        for destino, sinonimos in mapa.items():
            encontrado = next((c for c in cols if c in sinonimos), None)
            if encontrado:
                rename_dict[encontrado] = destino
        
        df = df.rename(columns=rename_dict)
        df['VOL'] = pd.to_numeric(df.get('VOL', 0), errors='coerce').fillna(0)
        df['RAD'] = pd.to_numeric(df.get('RAD', 8), errors='coerce').fillna(8)
        if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'Punto')
        
        lim = [100, 200, 300, 400] if "Polígonos" in modo_ref else [15, 20, 30, 40]
        df['RANGO_ID'] = df['VOL'].apply(lambda v: next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0)
        
        total_u = df['VOL'].sum()
        df['PESO_U'] = (df['VOL'] / total_u * 100).round(1).fillna(0) if total_u > 0 else 0
        df['PORC_Z'] = (df['VOL'] / df.groupby('NOM')['VOL'].transform('sum') * 100).round(1).fillna(0)
        return df

    # --- 3. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3, 1.3])

    with col_controles:
        st.title("🛡️ Sistema Pro AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Modo Principal", ["Coordenadas", "Polígonos CP", "Análisis Ejecutivo (Calor)"])
        
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            if "Análisis" in modo:
                st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            else:
                p_unica = xl.sheet_names[0]
                st.session_state.dict_datos = {p_unica: normalizar_df(xl.parse(p_unica), modo)}
            st.rerun()

        if st.session_state.dict_datos:
            periodos = list(st.session_state.dict_datos.keys())
            fecha_sel = st.select_slider("🕒 Historial:", options=periodos) if len(periodos) > 1 else periodos[0]
            df_act = st.session_state.dict_datos[fecha_sel]
            
            st.markdown("---")
            if "Análisis" in modo:
                st.subheader(f"📋 Resumen: {fecha_sel}")
                st.metric("Volumen Total", f"{int(df_act['VOL'].sum()):,}")
                zona_sel = st.selectbox("Filtro de Zona:", ["Todas"] + sorted(df_act['NOM'].unique().tolist()))
            else:
                f1, f2 = st.columns(2)
                activos = [i for i in range(6) if (f1 if i<3 else f2).checkbox(f"R{i}", value=True)]
                ver_nombres = st.toggle("🏷️ Ver Nombres", value=True)
                archivo_sel = st.selectbox("Mapa Base", sorted([f for f in os.listdir('mapas') if f.endswith(('.json', '.geojson'))])) if "Polígonos" in modo else None

    # --- 4. RENDERIZADO ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act.copy()
            if "Análisis" in modo and zona_sel != "Todas": df_m = df_m[df_m['NOM'] == zona_sel]
            elif "Análisis" not in modo: df_m = df_m[df_m['RANGO_ID'].isin(activos)]

            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            Geocoder().add_to(m)
            
            # Título dinámico dentro del mapa
            titulo_mapa = f'<h3 align="center" style="font-size:16px"><b>Reporte AMZL: {fecha_sel}</b></h3>'
            m.get_root().html.add_child(folium.Element(titulo_mapa))

            fg_calor = folium.FeatureGroup(name="🔥 Calor", show=("Análisis" in modo))
            fg_datos = folium.FeatureGroup(name="📍 Datos", show=("Análisis" not in modo))

            if 'LAT' in df_m.columns:
                df_h = df_m.dropna(subset=['LAT', 'LON'])
                if not df_h.empty:
                    HeatMap([[f['LAT'], f['LON'], f['VOL']] for _, f in df_h.iterrows()], radius=25).add_to(fg_calor)
                    m.fit_bounds([[df_h['LAT'].min(), df_h['LON'].min()], [df_h['LAT'].max(), df_h['LON'].max()]])

                    if "Polígonos" not in modo:
                        for _, f in df_h.iterrows():
                            c = {0:"#FFF", 1:"#FF0", 2:"#F90", 3:"#F44", 4:"#F00", 5:"#600"}.get(f['RANGO_ID'], "#888")
                            folium.CircleMarker([f['LAT'], f['LON']], radius=f['RAD'], color=c, fill=True, fill_color=c, fill_opacity=0.7, tooltip=f"{f['NOM']}: {int(f['VOL'])}").add_to(fg_datos)
                            if "Análisis" not in modo and ver_nombres:
                                folium.Marker([f['LAT'], f['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:7pt;text-align:center;width:100px;">{f["NOM"]}</div>', icon_anchor=(50,15))).add_to(fg_datos)

            fg_calor.add_to(m); fg_datos.add_to(m); folium.LayerControl().add_to(m)
            st_folium(m, width="100%", height=700)
            st.download_button(f"💾 Descargar {fecha_sel}", data=m._repr_html_().encode('utf-8'), file_name=f"analisis_{fecha_sel}.html", mime="text/html", use_container_width=True)

elif auth_status is False: st.error('Credenciales incorrectas')
