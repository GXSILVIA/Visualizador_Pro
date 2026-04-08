#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium
from datetime import datetime

# --- 1. CONFIGURACIÓN Y SEGURIDAD ---
st.set_page_config(page_title="Visualizador Pro AMZL", layout="wide")

if 'map_center' not in st.session_state:
    st.session_state.map_center = [19.4326, -99.1332]
if 'df_datos' not in st.session_state:
    st.session_state.df_datos = None

try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(
        config['credentials'], config['cookie']['name'],
        config['cookie']['key'], config['cookie']['expiry_days']
    )
    name, authentication_status, username = authenticator.login(location='main')
except Exception as e:
    st.error(f"Error en configuración: {e}"); st.stop()

if authentication_status:
    # --- 2. LÓGICA DE RANGOS DIFERENCIADA ---
    def obtener_rango_id(vol, modo):
        v = float(vol)
        if "Código Postal" in modo:
            if v == 0: return 0
            if v <= 100: return 1
            if v <= 200: return 2
            if v <= 300: return 3
            if v <= 400: return 4
            return 5
        else:
            if v == 0: return 0
            if v <= 15: return 1
            if v <= 20: return 2
            if v <= 30: return 3
            if v <= 40: return 4
            return 5

    @st.cache_data
    def cargar_capa_estado(archivo):
        ruta = f"mapas/{archivo}"
        if os.path.exists(ruta):
            gdf = gpd.read_file(ruta).to_crs("EPSG:4326")
            gdf['geometry'] = gdf['geometry'].simplify(0.002)
            posibles = ['d_cp', 'CP', 'CODIGOPOSTAL']
            col_encontrada = next((p for p in posibles if p in gdf.columns), gdf.columns[0])
            gdf[col_encontrada] = gdf[col_encontrada].astype(str).str.zfill(5)
            return gdf, col_encontrada
        return None, None

    # --- 3. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3.5, 1])

    with col_controles:
        st.title("📍 Panel de Control")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        
        modo = st.radio("Modo de Visualización", ["Coordenadas (Círculos)", "Código Postal (Polígonos)"])
        archivos = [f for f in os.listdir('mapas') if f.endswith(('.geojson', '.json'))] if os.path.exists('mapas') else []
        archivo_sel = st.selectbox("Seleccionar Mapa Base", sorted(archivos))
        
        st.markdown("---")
        st.subheader("📊 Filtros de Rango")
        
        if "Código Postal" in modo:
            labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"]
        else:
            labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
        
        # Filtros ordenados 3 y 3
        activos = []
        f1 = st.columns(3); f2 = st.columns(3)
        for i in range(6):
            target = f1[i] if i < 3 else f2[i-3]
            if target.checkbox(labels[i], value=True, key=f"f_{i}_{modo}"): activos.append(i)
        
        st.markdown("---")
        ver_nombres = st.toggle("🏷️ Mostrar Nombres Fijos", value=True)
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        btn_actualizar = st.button("🔄 Actualizar Mapa", use_container_width=True)

        if (archivo_excel and btn_actualizar) or (archivo_excel and st.session_state.get('last_fn') != archivo_excel.name):
            df_raw = pd.read_excel(archivo_excel)
            df_raw.columns = df_raw.columns.str.strip().str.upper()
            df_proc = df_raw.rename(columns={'VOLUMEN':'VOL', 'C.P.':'CP', 'CODIGO_POSTAL':'CP'})
            df_proc['VOL'] = pd.to_numeric(df_proc.get('VOL', 0), errors='coerce').fillna(0)
            df_proc['RANGO_ID'] = df_proc['VOL'].apply(lambda x: obtener_rango_id(x, modo))
            
            st.session_state.df_datos = df_proc
            st.session_state.last_fn = archivo_excel.name
            if 'LATITUD' in df_proc.columns and 'LONGITUD' in df_proc.columns:
                st.session_state.map_center = [df_proc['LATITUD'].dropna().mean(), df_proc['LONGITUD'].dropna().mean()]
            st.rerun()

    # --- 4. RENDERIZADO DEL MAPA ---
    with col_mapa:
        if st.session_state.df_datos is not None:
            df_ver = st.session_state.df_datos[st.session_state.df_datos['RANGO_ID'].isin(activos)].copy()
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            # Estilo de etiqueta limpia
            estilo_txt = 'font-size: 7pt; color: #222; text-align: center; width: 100px; line-height: 1; pointer-events: none;'

            if "Código Postal" in modo:
                gdf, col_geo = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                    merged = gdf.merge(df_ver, left_on=col_geo, right_on='CP')
                    for _, fila in merged.iterrows():
                        c = COLORS.get(fila['RANGO_ID'], "#888")
                        tooltip = f"{fila.get('NOMBRE','')} - Vol: {int(fila['VOL'])}"
                        
                        folium.GeoJson(fila['geometry'], tooltip=tooltip, style_function=lambda x, col=c: {
                            'fillColor': col, 'color': col, 'weight': 1.5, 'fillOpacity': 0.4
                        }).add_to(m)
                        
                        if ver_nombres and fila["VOL"] > 0:
                            cen = fila['geometry'].centroid
                            html = f'<div style="{estilo_txt}">{fila.get("NOMBRE","")}<br><b style="color: #d32f2f;">{int(fila["VOL"])}</b></div>'
                            folium.Marker([cen.y, cen.x], icon=folium.features.DivIcon(html=html)).add_to(m)
            else:
                df_gps = df_ver.dropna(subset=['LATITUD', 'LONGITUD'])
                for _, fila in df_gps.iterrows():
                    c = COLORS.get(fila['RANGO_ID'], "#888")
                    tooltip = f"{fila.get('NOMBRE', '')} - Vol: {int(fila['VOL'])}"
                    
                    folium.CircleMarker(
                        location=[fila['LATITUD'], fila['LONGITUD']], 
                        radius=7, color=c, fill=True, fill_color=c, fill_opacity=0.8,
                        tooltip=tooltip
                    ).add_to(m)
                    
                    if ver_nombres:
                        html = f'<div style="{estilo_txt}">{fila.get("NOMBRE","")}<br><b style="color: #d32f2f;">{int(fila["VOL"])}</b></div>'
                        folium.Marker([fila['LATITUD'], fila['LONGITUD']], icon=folium.features.DivIcon(html=html, icon_anchor=(50, 15))).add_to(m)

            st_folium(m, width="100%", height=700, returned_objects=[])
            
            # Botón de Descarga
            st.markdown("---")
            mapa_datos = m._repr_html_().encode('utf-8')
            st.download_button(label="💾 Descargar Mapa Actual (HTML)", data=mapa_datos, 
                               file_name=f"mapa_amzl_{datetime.now().strftime('%H%M%S')}.html", mime="text/html", use_container_width=True)

elif authentication_status is False:
    st.error('Usuario/Contraseña incorrectos')
elif authentication_status is None:
    st.warning('Por favor, ingrese sus credenciales')
