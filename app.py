import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os
import base64
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium
from datetime import datetime

# --- 1. CONFIGURACIÓN KAIZEN ---
st.set_page_config(page_title="Kaizen Amazon Hub - Proyecto Vecino Repartidor", layout="wide")

if 'df_datos' not in st.session_state:
    st.session_state.df_datos = None
if 'map_center' not in st.session_state:
    st.session_state.map_center = [19.4326, -99.1332]

# Seguridad (config.yaml)
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    authenticator.login(location='main')
except Exception as e:
    st.error(f"Error en configuración de acceso: {e}"); st.stop()

if st.session_state.get("authentication_status"):
    
    # --- 2. LÓGICA DE NEGOCIO (MÉTRICAS) ---
    def obtener_rango_id(vol, modo_actual):
        try:
            v = float(vol)
            if v == 0: return 0
            if "Quesadillas" in modo_actual:
                return 1 if v<=15 else 2 if v<=20 else 3 if v<=30 else 4 if v<=40 else 5
            return 1 if v<=100 else 2 if v<=200 else 3 if v<=300 else 4 if v<=400 else 5
        except: return 0

    # --- 3. DASHBOARD DE MÉTRICAS (Basado en tu imagen) ---
    st.title("📦 Kaizen: Optimización Amazon Hub")
    m1, m2, m3 = st.columns(3)
    
    with m1:
        st.metric(label="Tiempo de Decisión", value="< 2 min", delta="-18 min (Mejora 90%)")
    with m2:
        st.metric(label="Precisión de Ubicación", value="100%", delta="Coordenadas GPS")
    with m3:
        st.metric(label="Traslape de Zonas", value="Eliminado", delta="Filtros de Rango")

    st.markdown("---")

    # --- 4. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3.5, 1])

    with col_controles:
        st.subheader("⚙️ Configuración del Mapa")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        
        modo = st.radio("Capa Activa", ["Coordenadas (Vecino Repartidor)", "Código Postal (Quesadillas con Queso)"])
        archivos = [f for f in os.listdir('mapas') if f.endswith(('.geojson', '.json'))] if os.path.exists('mapas') else []
        archivo_sel = st.selectbox("Estado/Zona", sorted(archivos))
        
        st.markdown("---")
        st.write("**🔍 Filtros de Saturación**")
        if "Quesadillas" in modo:
            labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R40+"]
        else:
            labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"]
        
        activos = []
        c1, c2 = st.columns(2)
        for i in range(6):
            target = c1 if i < 3 else c2
            if target.checkbox(labels[i], value=True, key=f"f_{i}_{modo}"): activos.append(i)
        
        ver_nombres = st.toggle("🏷️ Ver Etiquetas Detalladas", value=True)
        archivo_excel = st.file_uploader("📂 Cargar Excel de Amazon Hub", type=["xlsx"])
        
        if archivo_excel:
            if st.session_state.get('last_fn') != archivo_excel.name:
                df_raw = pd.read_excel(archivo_excel)
                df_raw.columns = df_raw.columns.str.strip().str.upper()
                st.session_state.df_datos = df_raw.rename(columns={'LAT':'LATITUD','LON':'LONGITUD','VOLUMEN':'VOL','CODIGO POSTAL':'CP'})
                st.session_state.last_fn = archivo_excel.name
                if 'LATITUD' in st.session_state.df_datos.columns:
                    st.session_state.map_center = [st.session_state.df_datos['LATITUD'].mean(), st.session_state.df_datos['LONGITUD'].mean()]
                st.rerun()
        else:
            st.session_state.df_datos = None

    # --- 5. RENDERIZADO DEL MAPA ---
    with col_mapa:
        if st.session_state.df_datos is not None:
            df_plot = st.session_state.df_datos.copy()
            df_plot['RANGO_ID'] = df_plot['VOL'].apply(lambda x: obtener_rango_id(x, modo))
            df_plot = df_plot[df_plot['RANGO_ID'].isin(activos)]
            
            # Mapa nítido con calles visibles
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if "Quesadillas" in modo:
                @st.cache_data
                def load_geo(f):
                    gdf = gpd.read_file(f"mapas/{f}")
                    gdf['geometry'] = gdf['geometry'].simplify(0.0008)
                    return gdf, next((c for c in ['d_cp','CP','codigopostal'] if c in gdf.columns), gdf.columns)

                gdf_est, col_cp = load_geo(archivo_sel)
                df_plot['CP'] = df_plot['CP'].astype(str).str.zfill(5)
                merged = gdf_est.merge(df_plot, left_on=col_cp, right_on='CP')
                
                for _, fila in merged.iterrows():
                    c_p = COLORS.get(fila['RANGO_ID'], "#888")
                    folium.GeoJson(fila['geometry'], style_function=lambda x, c=c_p: {
                        'fillColor': c, 'color': c, 'weight': 3, 'fillOpacity': 0.25
                    }).add_to(m)
                    if ver_nombres:
                        cen = fila['geometry'].centroid
                        folium.Marker([cen.y, cen.x], icon=folium.features.DivIcon(html=f'<div style="font-size: 8pt; color: black; font-weight: bold; text-shadow: 2px 2px 4px white; text-align: center; width: 120px;">{fila.get("NOMBRE","")}<br><span style="color: #d32f2f;">({fila["VOL"]})</span></div>')).add_to(m)

            else: # MODO COORDENADAS
                for _, fila in df_plot.iterrows():
                    lat, lon = fila.get('LATITUD'), fila.get('LONGITUD')
                    if pd.notnull(lat) and pd.notnull(lon):
                        c_c = COLORS.get(fila['RANGO_ID'], "#888")
                        folium.Circle(location=[lat, lon], radius=fila.get('RADIO', 150), color=c_c, weight=2, fill=True, fill_color=c_c, fill_opacity=0.4).add_to(m)
                        if ver_nombres:
                            folium.Marker([lat, lon], icon=folium.features.DivIcon(html=f'<div style="font-size: 8pt; color: black; font-weight: bold; text-shadow: 2px 2px 4px white; text-align: center; width: 100px;">{fila.get("NOMBRE","")}<br><span style="color: #d32f2f;">({fila["VOL"]})</span></div>')).add_to(m)

            st_folium(m, width=1100, height=650, key=f"map_{modo}_{hash(str(activos))}")
            
            # Descarga Directa
            b64 = base64.b64encode(m._repr_html_().encode()).decode()
            st.markdown(f'<a href="data:text/html;base64,{b64}" download="Kaizen_Amazon_Hub.html" style="text-decoration:none;"><button style="width:100%; cursor:pointer; background-color:#FF4B4B; color:white; border:none; padding:12px; border-radius:5px; font-weight:bold;">💾 DESCARGAR MAPA HTML</button></a>', unsafe_allow_html=True)
        else:
            st.info("👋 Sube el archivo Excel para visualizar la mejora de impacto del Kaizen.")
