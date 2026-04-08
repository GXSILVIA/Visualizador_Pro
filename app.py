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

# --- 1. CONFIGURACIÓN Y SEGURIDAD ---
st.set_page_config(page_title="Visualizador Pro", layout="wide")

if 'map_center' not in st.session_state:
    st.session_state.map_center = [19.4326, -99.1332]
if 'df_datos' not in st.session_state:
    st.session_state.df_datos = None

# Carga de Autenticación
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    
    authenticator = stauth.Authenticate(
        config['credentials'], 
        config['cookie']['name'],
        config['cookie']['key'], 
        config['cookie']['expiry_days']
    )
    # Captura los 3 valores necesarios en la versión 0.3.x
    name, authentication_status, username = authenticator.login(location='main')
except Exception as e:
    st.error(f"Error en config.yaml: {e}")
    st.stop()

if authentication_status:
    # --- 2. FUNCIONES DE APOYO ---
    def rango_postal(v):
        try:
            val = float(v)
            return 0 if val==0 else 1 if val<=100 else 2 if val<=200 else 3 if val<=300 else 4 if val<=400 else 5
        except: return 0

    def rango_coordenadas(v):
        try:
            val = float(v)
            return 0 if val==0 else 1 if val<=15 else 2 if val<=20 else 3 if val<=30 else 4 if val<=40 else 5
        except: return 0

    @st.cache_data
    def cargar_capa_estado(archivo):
        ruta = f"mapas/{archivo}"
        if os.path.exists(ruta):
            gdf = gpd.read_file(ruta).to_crs("EPSG:4326")
            gdf = gdf.loc[:, ~gdf.columns.duplicated()].copy()
            gdf['geometry'] = gdf['geometry'].simplify(0.0008)
            posibles = ['d_cp', 'CP', 'CODIGOPOSTAL', 'CODIGO_POSTAL']
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
        archivo_sel = st.selectbox("Seleccionar Estado", sorted(archivos))
        
        st.markdown("---")
        st.subheader("📊 Filtros de Rango")
        labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Código Postal" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
        
        activos = []
        c1, c2 = st.columns(2)
        for i in range(6):
            target = c1 if i < 3 else c2
            if target.checkbox(labels[i], value=True, key=f"f_{i}_{modo}"): activos.append(i)
        
        ver_nombres = st.toggle("🏷️ Mostrar Nombres + Volumen", value=True)
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        btn_actualizar = st.button("🔄 Actualizar Mapa", use_container_width=True)

        if (archivo_excel and btn_actualizar) or (archivo_excel and st.session_state.get('last_fn') != archivo_excel.name):
            df_raw = pd.read_excel(archivo_excel)
            if len(df_raw) > 2000:
                st.error("❌ Límite de 2000 filas excedido."); st.stop()
            
            df_raw.columns = df_raw.columns.str.strip().str.upper()
            df_proc = df_raw.rename(columns={'VOLUMEN':'VOL', 'RADIO':'RADIO'})
            
            func_rango = rango_postal if "Código Postal" in modo else rango_coordenadas
            df_proc['VOL'] = pd.to_numeric(df_proc.get('VOL', 0), errors='coerce').fillna(0)
            df_proc['RANGO_ID'] = df_proc['VOL'].apply(func_rango)
            
            st.session_state.df_datos = df_proc
            st.session_state.last_fn = archivo_excel.name
            if 'LATITUD' in df_proc.columns and 'LONGITUD' in df_proc.columns:
                st.session_state.map_center = [df_proc['LATITUD'].mean(), df_proc['LONGITUD'].mean()]
            st.rerun()

    # --- 4. RENDERIZADO DEL MAPA ---
    with col_mapa:
        if st.session_state.df_datos is not None:
            df_ver = st.session_state.df_datos[st.session_state.df_datos['RANGO_ID'].isin(activos)].copy()
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if "Código Postal" in modo:
                gdf, col_geo = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                    merged = gdf.merge(df_ver, left_on=col_geo, right_on='CP')
                    for _, fila in merged.iterrows():
                        c_p = COLORS.get(fila['RANGO_ID'], "#888")
                        folium.GeoJson(fila['geometry'], style_function=lambda x, c=c_p: {'fillColor': c, 'color': '#444', 'weight': 1.5, 'fillOpacity': 0.3}).add_to(m)
                        if ver_nombres:
                            cen = fila['geometry'].centroid
                            texto_html = f'<div style="font-size: 8pt; font-weight: bold; text-align: center; width: 120px;">{fila.get("NOMBRE","")}<br><span style="color: #d32f2f;">({int(fila["VOL"])})</span></div>'
                            folium.Marker([cen.y, cen.x], icon=folium.features.DivIcon(html=texto_html)).add_to(m)
            else:
                for _, fila in df_ver.iterrows():
                    c_c = COLORS.get(fila['RANGO_ID'], "#888")
                    folium.CircleMarker([fila['LATITUD'], fila['LONGITUD']], radius=8, color="#333", fill=True, fill_color=c_c, fill_opacity=0.8).add_to(m)

            st_folium(m, width="100%", height=700, returned_objects=[])

elif authentication_status is False:
    st.error('Usuario/Contraseña incorrectos')
elif authentication_status is None:
    st.warning('Por favor, ingrese sus credenciales')
