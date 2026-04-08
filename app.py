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
    # --- 2. PROCESAMIENTO INTELIGENTE ---
    def normalizar_df(df, modo_ref):
        df.columns = df.columns.str.strip().str.upper()
        cols = df.columns
        mapa_cols = {
            'LAT': [c for c in cols if c in ['LAT', 'LATITUD']],
            'LON': [c for c in cols if c in ['LON', 'LONGITUD']],
            'VOL': [c for c in cols if c in ['VOL', 'VOLUMEN']],
            'RAD': [c for c in cols if c in ['RADIO', 'RAD', 'SIZE']],
            'CP':  [c for c in cols if c in ['CP', 'C.P.', 'CODIGO POSTAL']],
            'NOM': [c for c in cols if c in ['NOMBRE', 'ZONA', 'AREA']]
        }
        df = df.rename(columns={v: k for k, v in mapa_cols.items() if v})
        df['VOL'] = pd.to_numeric(df.get('VOL', 0), errors='coerce').fillna(0)
        df['RAD'] = pd.to_numeric(df.get('RAD', 8), errors='coerce').fillna(8)
        if 'NOM' not in df.columns: df['NOM'] = df['CP'] if 'CP' in df.columns else "Punto"
        
        # Rangos dinámicos
        lim = [100, 200, 300, 400] if "Polígonos" in modo_ref else [15, 20, 30, 40]
        df['RANGO_ID'] = df['VOL'].apply(lambda v: next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0)
        
        # Cálculo de Reparto (Funciona aunque no haya encimados)
        total_universo = df['VOL'].sum()
        total_por_nombre = df.groupby('NOM')['VOL'].transform('sum')
        df['PORC_ZONA'] = (df['VOL'] / total_por_nombre * 100).round(1).fillna(0)
        df['PESO_UNIVERSO'] = (df['VOL'] / total_universo * 100).round(1).fillna(0)
        
        return df

    # --- 3. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3, 1.3])

    with col_controles:
        st.title("🛡️ Sistema Pro AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Modo Principal", ["Coordenadas", "Polígonos CP", "Análisis Ejecutivo (Calor)"])
        
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar Datos"):
            xl = pd.ExcelFile(archivo_excel)
            st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            st.rerun()

        if st.session_state.dict_datos:
            periodos = list(st.session_state.dict_datos.keys())
            fecha_sel = st.select_slider("🕒 Historial:", options=periodos) if len(periodos) > 1 else periodos[0]
            df_act = st.session_state.dict_datos[fecha_sel]
            
            st.markdown("---")
            if "Análisis" in modo:
                st.subheader("📋 Resumen Ejecutivo")
                st.metric("Universo Total", f"{int(df_act['VOL'].sum()):,}")
                
                # Filtro dinámico: muestra nombres únicos o todos
                zona_sel = st.selectbox("Seleccionar Zona/Punto para detalle:", ["Todas"] + sorted(df_act['NOM'].unique().tolist()))
                
                if zona_sel != "Todas":
                    det = df_act[df_act['NOM'] == zona_sel]
                    st.info(f"Análisis de {zona_sel}:")
                    for _, r in det.iterrows():
                        st.write(f"🔹 Vol: **{int(r['VOL'])}** ({r['PESO_UNIVERSO']}% del total)")
                        if r['PORC_ZONA'] < 100:
                            st.caption(f"⚠️ Reparto en esta zona: {r['PORC_ZONA']}%")
            else:
                f1, f2 = st.columns(2)
                activos = [i for i in range(6) if (f1 if i<3 else f2).checkbox(f"R{i}", value=True)]
                ver_nombres = st.toggle("🏷️ Ver Nombres", value=True)
                archivo_sel = st.selectbox("Mapa Base", sorted([f for f in os.listdir('mapas') if f.endswith(('.json', '.geojson'))])) if "Polígonos" in modo else None

    # --- 4. RENDERIZADO ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act.copy()
            # Aplicar filtro de zona si está seleccionado
            if "Análisis" in modo and zona_sel != "Todas":
                df_m = df_m[df_m['NOM'] == zona_sel]
            elif "Análisis" not in modo:
                df_m = df_m[df_m['RANGO_ID'].isin(activos)]

            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            Geocoder().add_to(m)
            
            fg_calor = folium.FeatureGroup(name="🔥 Calor", show=("Análisis" in modo))
            fg_datos = folium.FeatureGroup(name="📍 Datos", show=("Análisis" not in modo))

            if 'LAT' in df_m.columns:
                df_h = df_m.dropna(subset=['LAT', 'LON'])
                if not df_h.empty:
                    HeatMap([[f['LAT'], f['LON'], f['VOL']] for _, f in df_h.iterrows()], radius=25).add_to(fg_calor)
                    # Auto-zoom inteligente
                    m.fit_bounds([[df_h['LAT'].min(), df_h['LON'].min()], [df_h['LAT'].max(), df_h['LON'].max()]])

                    if "Polígonos" not in modo:
                        for _, f in df_h.iterrows():
                            c = {0:"#FFF", 1:"#FF0", 2:"#F90", 3:"#F44", 4:"#F00", 5:"#600"}.get(f['RANGO_ID'], "#888")
                            tip = f"{f['NOM']} | Vol: {int(f['VOL'])} | {f['PESO_UNIVERSO']}% del total"
                            folium.CircleMarker([f['LAT'], f['LON']], radius=f['RAD'], color=c, fill=True, fill_color=c, fill_opacity=0.7, tooltip=tip).add_to(fg_datos)
                            if "Análisis" not in modo and ver_nombres:
                                folium.Marker([f['LAT'], f['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:7pt;text-align:center;width:100px;">{f["NOM"]}</div>', icon_anchor=(50,15))).add_to(fg_datos)

            fg_calor.add_to(m); fg_datos.add_to(m); folium.LayerControl().add_to(m)
            st_folium(m, width="100%", height=700)
            st.download_button("💾 Descargar HTML", data=m._repr_html_().encode('utf-8'), file_name=f"mapa_pro.html", mime="text/html", use_container_width=True)

elif auth_status is False: st.error('Credenciales incorrectas')
