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

# Inicializar estados de persistencia
if 'map_center' not in st.session_state:
    st.session_state.map_center = [19.4326, -99.1332]
if 'df_datos' not in st.session_state:
    st.session_state.df_datos = None
if 'last_file_name' not in st.session_state:
    st.session_state.last_file_name = None

# Carga de seguridad (config.yaml)
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(
        config['credentials'], config['cookie']['name'],
        config['cookie']['key'], config['cookie']['expiry_days']
    )
    authenticator.login(location='main')
except Exception as e:
    st.error(f"Error al cargar config.yaml: {e}"); st.stop()

if st.session_state.get("authentication_status"):
    
    # --- 2. FUNCIONES ---
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
        activos = [i for i, label in enumerate(labels) if st.checkbox(label, value=True, key=f"f_{i}")]
        
        ver_nombres = st.toggle("🏷️ Mostrar Nombres + Volumen", value=True)
        
        # MANEJO DEL ARCHIVO EXCEL
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        
        # SI SE QUITA EL ARCHIVO: Borramos los datos de la sesión
        if archivo_excel is None:
            st.session_state.df_datos = None
            st.session_state.last_file_name = None

        # BOTÓN DE ACTUALIZAR (Solo procesa si hay archivo)
        btn_actualizar = st.button("🔄 Actualizar Mapa", use_container_width=True)

        if (archivo_excel and btn_actualizar) or (archivo_excel and st.session_state.last_file_name != archivo_excel.name):
            df_raw = pd.read_excel(archivo_excel)
            df_raw.columns = df_raw.columns.str.strip().str.upper()
            renom = {'LAT':'LATITUD', 'LON':'LONGITUD', 'LNG':'LONGITUD', 'VOLUMEN':'VOL', 'CODIGO POSTAL':'CP'}
            df_proc = df_raw.rename(columns=renom)
            if 'VOL' not in df_proc.columns: df_proc['VOL'] = 0
            df_proc['RANGO_ID'] = df_proc['VOL'].apply(asignar_rango)
            
            st.session_state.df_datos = df_proc
            st.session_state.last_file_name = archivo_excel.name
            if 'LATITUD' in df_proc.columns and not df_proc['LATITUD'].dropna().empty:
                st.session_state.map_center = [df_proc['LATITUD'].mean(), df_proc['LONGITUD'].mean()]
            st.rerun()

    # --- 4. RENDERIZADO ---
    with col_mapa:
        # SOLO DIBUJAR SI HAY DATOS CARGADOS Y EL ARCHIVO SIGUE PRESENTE
        if st.session_state.df_datos is not None and archivo_excel is not None:
            df_ver = st.session_state.df_datos[st.session_state.df_datos['RANGO_ID'].isin(activos)]
            
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if modo == "Código Postal (Polígonos)":
                gdf, col_cp = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                    merged = gdf.merge(df_ver, left_on=col_cp, right_on='CP')
                    for _, fila in merged.iterrows():
                        color_p = COLORS.get(fila['RANGO_ID'], "#888")
                        folium.GeoJson(fila['geometry'], style_function=lambda x, c=color_p: {'fillColor': c, 'color': 'black', 'weight': 1, 'fillOpacity': 0.6}).add_to(m)
                        if ver_nombres:
                            c = fila['geometry'].centroid
                            folium.Marker([c.y, c.x], icon=folium.features.DivIcon(html=f'<div style="font-size: 8pt; color: black; font-weight: bold; text-shadow: 2px 2px 4px white; text-align: center; width: 120px;">{fila.get("NOMBRE","")}<br><span style="font-size: 7pt; color: #d32f2f;">({fila["VOL"]})</span></div>')).add_to(m)

            else: # MODO COORDENADAS
                for _, fila in df_ver.iterrows():
                    lat, lon = fila.get('LATITUD'), fila.get('LONGITUD')
                    if pd.notnull(lat) and pd.notnull(lon):
                        color_c = COLORS.get(fila['RANGO_ID'], "#888")
                        folium.Circle(location=[lat, lon], radius=fila.get('RADIO', 100), color=color_c, fill=True, fill_color=color_c, fill_opacity=0.5).add_to(m)
                        if ver_nombres:
                            folium.Marker([lat, lon], icon=folium.features.DivIcon(html=f'<div style="font-size: 8pt; color: black; font-weight: bold; text-shadow: 2px 2px 4px white; text-align: center; width: 100px;">{fila.get("NOMBRE","")}<br><span style="font-size: 7pt; color: #d32f2f;">({fila["VOL"]})</span></div>')).add_to(m)

            # Usamos una key única que incluya el nombre del archivo para forzar limpieza al cambiar
            st_folium(m, width=1100, height=650, key=f"vpro_{st.session_state.last_file_name}_{hash(str(activos))}")

            # Botón de Descarga
            b64 = base64.b64encode(m._repr_html_().encode()).decode()
            st.markdown(f'<a href="data:text/html;base64,{b64}" download="mapa_final.html" style="text-decoration:none;"><button style="width:100%; cursor:pointer; background-color:#FF4B4B; color:white; border:none; padding:12px; border-radius:5px; font-weight:bold;">💾 DESCARGAR MAPA HTML</button></a>', unsafe_allow_html=True)
        else:
            # Si no hay archivo o se eliminó, mostramos un mapa vacío o el mensaje
            st.info("👋 Sube un archivo Excel para generar el mapa.")

elif st.session_state.get("authentication_status") is False:
    st.error('Usuario/Contraseña incorrectos')
