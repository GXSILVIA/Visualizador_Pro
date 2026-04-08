#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap, Geocoder # Buscador añadido
import geopandas as gpd
import os
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium
from datetime import datetime

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Visualizador Pro AMZL", layout="wide")

if 'map_center' not in st.session_state: st.session_state.map_center = [19.4326, -99.1332]
if 'df_datos' not in st.session_state: st.session_state.df_datos = None

try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, authentication_status, username = authenticator.login(location='main')
except: st.stop()

if authentication_status:
    # --- 2. LÓGICA DE RANGOS ---
    def obtener_rango_id(vol, modo_ref):
        v = float(vol)
        limites = [100, 200, 300, 400] if "Polígonos" in modo_ref else [15, 20, 30, 40]
        if v == 0: return 0
        for i, l in enumerate(limites, 1):
            if v <= l: return i
        return 5

    @st.cache_data
    def cargar_capa_estado(archivo):
        ruta = f"mapas/{archivo}"
        if os.path.exists(ruta):
            gdf = gpd.read_file(ruta).to_crs("EPSG:4326")
            gdf['geometry'] = gdf['geometry'].simplify(0.002)
            pos = ['d_cp', 'CP', 'CODIGOPOSTAL']
            col = next((p for p in pos if p in gdf.columns), gdf.columns[0])
            gdf[col] = gdf[col].astype(str).str.zfill(5)
            return gdf, col
        return None, None

    # --- 3. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3, 1.2])

    with col_controles:
        st.title("📍 Control y Análisis")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Modo Principal", ["Coordenadas", "Polígonos CP", "Mapa de Calor"])
        
        if "Calor" not in modo:
            archivo_sel = st.selectbox("Mapa Base", sorted([f for f in os.listdir('mapas') if f.endswith(('.json', '.geojson'))])) if "Polígonos" in modo else None
            st.markdown("---")
            st.subheader("📊 Filtros de Rango")
            labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
            activos = []
            f1, f2 = st.columns(3), st.columns(3)
            for i in range(6):
                if (f1[i] if i<3 else f2[i-3]).checkbox(labels[i], value=True, key=f"f_{i}_{modo}"): activos.append(i)
            ver_nombres = st.toggle("🏷️ Mostrar Nombres Fijos", value=True)
        else:
            activos, ver_nombres = list(range(6)), False

        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if (archivo_excel and st.button("🔄 Procesar Análisis")):
            df = pd.read_excel(archivo_excel)
            df.columns = df.columns.str.strip().str.upper()
            df = df.rename(columns={'VOLUMEN':'VOL', 'C.P.':'CP', 'CODIGO_POSTAL':'CP', 'NOMBRE':'ZONA', 'PERSONA':'PERSONA'})
            if 'ZONA' not in df.columns: df['ZONA'] = df['CP'].astype(str).str.zfill(5)
            df['VOL'] = pd.to_numeric(df['VOL'], errors='coerce').fillna(0)
            df['RANGO_ID'] = df['VOL'].apply(lambda x: obtener_rango_id(x, modo))
            total_z = df.groupby('ZONA')['VOL'].transform('sum')
            df['PORC_ZONA'] = (df['VOL'] / total_z * 100).round(1).fillna(0)
            st.session_state.df_datos = df
            if 'LATITUD' in df.columns: st.session_state.map_center = [df['LATITUD'].mean(), df['LONGITUD'].mean()]
            st.rerun()

        if st.session_state.df_datos is not None:
            df = st.session_state.df_datos
            if "Calor" in modo:
                st.markdown("---")
                st.subheader("📋 Resumen Ejecutivo")
                u_vol = df['VOL'].sum()
                st.metric("Universo Total Volumen", f"{int(u_vol):,}")
                encimados = df[df.duplicated('ZONA', keep=False)]
                st.write(f"Zonas con saturación: **{encimados['ZONA'].nunique()}**")
                zona_sel = st.selectbox("Analizar Reparto en Zona:", sorted(encimados['ZONA'].unique()))
                if zona_sel:
                    det = encimados[encimados['ZONA'] == zona_sel]
                    st.info(f"Volumen Total Zona: {int(det['VOL'].sum())}")
                    for _, f in det.iterrows(): st.write(f"👤 {f['PERSONA']}: **{f['PORC_ZONA']}%**")
            else:
                st.dataframe(df[['ZONA', 'PERSONA', 'VOL', 'PORC_ZONA']].sort_values(by=['ZONA', 'VOL'], ascending=[True, False]), height=200)

    # --- 4. RENDERIZADO DEL MAPA ---
    with col_mapa:
        if st.session_state.df_datos is not None:
            df_m = st.session_state.df_datos[st.session_state.df_datos['RANGO_ID'].isin(activos)]
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            
            # Buscador de direcciones (Geocoder)
            Geocoder(collapsed=True, position='topleft', add_marker=True).add_to(m)
            
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}
            estilo_txt = 'font-size:7pt; color:#222; text-align:center; width:100px; pointer-events:none;'

            fg_calor = folium.FeatureGroup(name="🔥 Mapa de Calor", show=(modo=="Mapa de Calor"))
            fg_puntos = folium.FeatureGroup(name="📍 Capa de Datos", show=(modo!="Mapa de Calor"))

            # HeatMap
            df_h = df_m.dropna(subset=['LATITUD', 'LONGITUD'])
            HeatMap([[f['LATITUD'], f['LONGITUD'], f['VOL']] for _, f in df_h.iterrows()], radius=25, blur=15).add_to(fg_calor)

            # Capas visuales
            if "Polígonos" in modo:
                gdf, col_geo = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    merged = gdf.merge(df_m, left_on=col_geo, right_on='CP')
                    for _, f in merged.iterrows():
                        c = COLORS.get(f['RANGO_ID'], "#888")
                        folium.GeoJson(f['geometry'], tooltip=f"{f['ZONA']}: {f['PORC_ZONA']}%", 
                                       style_function=lambda x, col=c: {'fillColor':col, 'color':col, 'weight':1.5, 'fillOpacity':0.4}).add_to(fg_puntos)
                        if ver_nombres:
                            folium.Marker([f['geometry'].centroid.y, f['geometry'].centroid.x], 
                                          icon=folium.features.DivIcon(html=f'<div style="{estilo_txt}">{f["PERSONA"]}<br><b>{f["PORC_ZONA"]}%</b></div>')).add_to(fg_puntos)
            else:
                for _, f in df_m.dropna(subset=['LATITUD', 'LONGITUD']).iterrows():
                    c = COLORS.get(f['RANGO_ID'], "#888")
                    folium.CircleMarker([f['LATITUD'], f['LONGITUD']], radius=7, color=c, fill=True, fill_color=c, fill_opacity=0.8, 
                                        tooltip=f"{f['PERSONA']}: {f['PORC_ZONA']}%").add_to(fg_puntos)
                    if ver_nombres:
                        folium.Marker([f['LATITUD'], f['LONGITUD']], icon=folium.features.DivIcon(html=f'<div style="{estilo_txt}">{f["PERSONA"]}<br><b>{f["PORC_ZONA"]}%</b></div>', icon_anchor=(50,15))).add_to(fg_puntos)

            fg_calor.add_to(m); fg_puntos.add_to(m)
            folium.LayerControl(position='topright', collapsed=False).add_to(m)

            st_folium(m, width="100%", height=700)
            st.download_button("💾 Descargar Mapa Profesional (HTML)", data=m._repr_html_().encode('utf-8'), file_name=f"analisis_amzl_{datetime.now().strftime('%H%M')}.html", mime="text/html", use_container_width=True)

elif authentication_status is False: st.error('Usuario/Contraseña incorrectos')
elif authentication_status is None: st.warning('Por favor, ingrese sus credenciales')
