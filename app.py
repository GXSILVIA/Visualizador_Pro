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

# --- 1. CONFIGURACIÓN Y SEGURIDAD ---
st.set_page_config(page_title="Visualizador Pro", layout="wide")

# Inicializar estados
if 'map_center' not in st.session_state:
    st.session_state.map_center = [19.4326, -99.1332]
if 'df_datos' not in st.session_state:
    st.session_state.df_datos = None

# Carga de seguridad desde tu config.yaml actual
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(
        config['credentials'], config['cookie']['name'],
        config['cookie']['key'], config['cookie']['expiry_days']
    )
    authenticator.login(location='main')
except Exception as e:
    st.error(f"Error al cargar config.yaml: {e}")
    st.stop()

if st.session_state.get("authentication_status"):
    
    # --- 2. FUNCIONES DE APOYO ---
    def asignar_rango(v):
        try:
            val = float(v)
            return 0 if val==0 else 1 if val<=15 else 2 if val<=20 else 3 if val<=30 else 4 if val<=40 else 5
        except: return 0

    @st.cache_data
    def cargar_capa_estado(archivo):
        ruta = f"mapas/{archivo}"
        if os.path.exists(ruta):
            gdf = gpd.read_file(ruta)
            gdf = gdf.loc[:, ~gdf.columns.duplicated()].copy()
            gdf['geometry'] = gdf['geometry'].simplify(0.0008)
            posibles = ['d_cp', 'CP', 'codigopostal']
            col_json = next((c for c in posibles if c in gdf.columns), gdf.columns[0])
            gdf[col_json] = gdf[col_json].astype(str).str.zfill(5)
            return gdf, col_json
        return None, None

    # --- 3. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3.5, 1])

    with col_controles:
        st.title("📍 Panel Pro")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        
        modo = st.radio("Modo de Visualización", ["Coordenadas (Círculos)", "Código Postal (Polígonos)"])
        
        archivos = [f for f in os.listdir('mapas') if f.endswith(('.geojson', '.json'))] if os.path.exists('mapas') else []
        archivo_sel = st.selectbox("Seleccionar Estado", sorted(archivos))
        
        st.markdown("---")
        st.subheader("📊 Filtros de Rango")
        labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R40+"]
        activos = []
        c1, c2 = st.columns(2)
        for i in range(6):
            target = c1 if i < 3 else c2
            if target.checkbox(labels[i], value=True, key=f"f_{i}"):
                activos.append(i)
        
        ver_nombres = st.toggle("🏷️ Mostrar Nombres + Volumen", value=True)
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        
        if archivo_excel:
            if st.session_state.get('last_file') != archivo_excel.name:
                df_raw = pd.read_excel(archivo_excel)
                df_raw.columns = df_raw.columns.str.strip().str.upper()
                
                # Normalización robusta para Coordenadas y Polígonos
                renom = {
                    'LAT':'LATITUD', 'LON':'LONGITUD', 'LNG':'LONGITUD', 
                    'VOLUMEN':'VOL', 'VOL':'VOL', 'CODIGO POSTAL':'CP', 'CP':'CP'
                }
                df_proc = df_raw.rename(columns=renom)
                if 'VOL' not in df_proc.columns: df_proc['VOL'] = 0
                df_proc['RANGO_ID'] = df_proc['VOL'].apply(asignar_rango)
                
                st.session_state.df_datos = df_proc
                st.session_state.last_file = archivo_excel.name
                
                # Auto-centrado si hay coordenadas
                if 'LATITUD' in df_proc.columns and not df_proc['LATITUD'].dropna().empty:
                    st.session_state.map_center = [df_proc['LATITUD'].mean(), df_proc['LONGITUD'].mean()]
                st.rerun()

    # --- 4. MAPA ---
    with col_mapa:
        if st.session_state.df_datos is not None:
            df_ver = st.session_state.df_datos[st.session_state.df_datos['RANGO_ID'].isin(activos)]
            
            # MAPA VIBRANTE (Calles visibles: OpenStreetMap)
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="openstreetmap")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            # --- CAPA POLÍGONOS ---
            if modo == "Código Postal (Polígonos)":
                gdf, col_cp = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                    merged = gdf.merge(df_ver, left_on=col_cp, right_on='CP')
                    
                    for _, fila in merged.iterrows():
                        color_p = COLORS.get(fila['RANGO_ID'], "#888")
                        folium.GeoJson(
                            fila['geometry'],
                            style_function=lambda x, c=color_p: {
                                'fillColor': c, 'color': 'black', 'weight': 1, 'fillOpacity': 0.6
                            },
                            tooltip=f"CP: {fila['CP']} | Vol: {fila['VOL']}"
                        ).add_to(m)
                        
                        if ver_nombres:
                            centro = fila['geometry'].centroid
                            folium.Marker(
                                [centro.y, centro.x],
                                icon=folium.features.DivIcon(html=f'''
                                    <div style="font-size: 8pt; color: black; font-weight: bold; 
                                    text-shadow: 2px 2px 4px white; text-align: center; width: 120px;">
                                        {fila.get("NOMBRE","")}<br><span style="font-size: 7pt; color: #d32f2f;">({fila['VOL']})</span>
                                    </div>''')
                            ).add_to(m)

            # --- CAPA COORDENADAS ---
            else:
                for _, fila in df_ver.iterrows():
                    lat, lon = fila.get('LATITUD'), fila.get('LONGITUD')
                    if pd.notnull(lat) and pd.notnull(lon):
                        color_c = COLORS.get(fila['RANGO_ID'], "#888")
                        radio = fila.get('RADIO', 100) # Usa columna RADIO o 100 por defecto
                        
                        folium.Circle(
                            location=[lat, lon], radius=radio, color=color_c,
                            fill=True, fill_color=color_c, fill_opacity=0.5,
                            tooltip=f"Nombre: {fila.get('NOMBRE','')} | Vol: {fila['VOL']}"
                        ).add_to(m)
                        
                        if ver_nombres:
                            folium.Marker(
                                [lat, lon],
                                icon=folium.features.DivIcon(html=f'''
                                    <div style="font-size: 8pt; color: black; font-weight: bold; 
                                    text-shadow: 2px 2px 4px white; text-align: center; width: 100px;">
                                        {fila.get("NOMBRE","")}<br><span style="font-size: 7pt; color: #d32f2f;">({fila['VOL']})</span>
                                    </div>''')
                            ).add_to(m)

            # RENDERIZADO
            st_folium(m, width=1100, height=650, key=f"map_{hash(str(activos)+modo+str(ver_nombres))}")

            # DESCARGA (Base64 para asegurar que funcione con mapas pesados)
            html_mapa = m._repr_html_()
            b64 = base64.b64encode(html_mapa.encode()).decode()
            href = f'<a href="data:text/html;base64,{b64}" download="mapa_final.html" style="text-decoration:none;"><button style="width:100%; cursor:pointer; background-color:#FF4B4B; color:white; border:none; padding:12px; border-radius:5px; font-weight:bold;">💾 DESCARGAR MAPA HTML</button></a>'
            st.markdown(href, unsafe_allow_html=True)
        else:
            st.info("👋 Sube tu archivo Excel para comenzar.")

elif st.session_state.get("authentication_status") is False:
    st.error('Usuario/Contraseña incorrectos')
elif st.session_state.get("authentication_status") is None:
    st.warning('Por favor, ingresa tus credenciales')
