import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os
import io
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium

# --- 1. CONFIGURACIÓN DE SEGURIDAD (YAML) ---
with open('config.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
    config['preauthorized']
)

# Renderizar Login
name, authentication_status, username = authenticator.login(location='main')

if authentication_status:
    st.set_page_config(page_title="Visualizador Pro", layout="wide")
    
    # Barra lateral
    st.sidebar.write(f'Bienvenido **{name}**')
    authenticator.logout('Cerrar Sesión', 'sidebar')

    st.title("📍 Visualizador Pro")

    # Colores y lógica de rangos
    COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FFA500", 3:"#FF7777", 4:"#FF0000", 5:"#800000"}

    def asignar_rango(v):
        try:
            val = float(v)
            return 0 if val==0 else 1 if val<=15 else 2 if val<=20 else 3 if val<=30 else 4 if val<=40 else 5
        except: return 0

    def normalizar_columnas(df):
        df.columns = df.columns.str.strip().str.upper()
        mapeo = {
            'LATITUD': 'LAT', 'LAT': 'LAT', 'LONGITUD': 'LON', 'LON': 'LON', 'LNG': 'LON',
            'CODIGO POSTAL': 'CP', 'CODIGO_POSTAL': 'CP', 'CP': 'CP', 
            'VOLUMEN': 'VOLUMEN', 'NOMBRE': 'NOMBRE', 'RADIO': 'RADIO'
        }
        return df.rename(columns=mapeo)

    @st.cache_data
    def cargar_capa_estado(nombre_archivo):
        ruta = f"mapas/{nombre_archivo}"
        if os.path.exists(ruta):
            gdf = gpd.read_file(ruta)
            posibles_cols = ['d_cp', 'CP', 'codigopostal', 'CODIGO_POSTAL']
            col_json = next((c for c in posibles_cols if c in gdf.columns), gdf.columns[0])
            gdf[col_json] = gdf[col_json].astype(str).str.zfill(5)
            return gdf, col_json
        return None, None

    # --- 2. INTERFAZ DE CONTROL ---
    col_mapa, col_controles = st.columns([3.5, 1])

    with col_controles:
        st.subheader("⚙️ Configuración")
        modo = st.radio("Método de Ubicación", ["Coordenadas (Puntos)", "Código Postal (Polígonos)"])
        
        if os.path.exists('mapas'):
            archivos_geo = [f for f in os.listdir('mapas') if f.endswith(('.geojson', '.json'))]
        else:
            archivos_geo = []
            
        archivo_sel = st.selectbox("Estado a visualizar", sorted(archivos_geo) if archivos_geo else ["Carpeta mapas/ vacía"])
        
        st.markdown("---")
        st.subheader("📊 Filtros de Rango")
        labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R40+"]
        f_checks = [st.checkbox(l, value=True, key=f"f_{i}") for i, l in enumerate(labels)]
        
        st.info("🖱️ Pasa el mouse por el mapa para ver el Volumen.")
        archivo_excel = st.file_uploader("📂 Sube tu Excel", type=["xlsx"])

    # --- 3. MAPA Y PROCESAMIENTO ---
    with col_mapa:
        if archivo_excel:
            df = pd.read_excel(archivo_excel)
            df = normalizar_columnas(df)
            df['RANGO_ID'] = df['VOLUMEN'].apply(asignar_rango)
            
            activos = [i for i, v in enumerate(f_checks) if v]
            df_ver = df[df['RANGO_ID'].isin(activos)].copy()

            m = folium.Map(location=[19.4326, -99.1332], zoom_start=6, control_scale=True)

            if modo == "Coordenadas (Puntos)":
                if 'LAT' in df_ver.columns and 'LON' in df_ver.columns:
                    m.location = [df_ver['LAT'].mean(), df_ver['LON'].mean()]
                    m.zoom_start = 11
                    for _, fila in df_ver.iterrows():
                        color = COLORS.get(fila['RANGO_ID'], "#888")
                        tooltip_html = f"<b>{fila.get('NOMBRE','')}</b><br><span style='color:red;'>Vol: {fila.get('VOLUMEN', 0)}</span>"
                        folium.Circle(
                            [fila['LAT'], fila['LON']], radius=float(fila.get('RADIO', 800)),
                            color="black", weight=1, fill=True, fill_color=color, fill_opacity=0.6,
                            tooltip=folium.Tooltip(tooltip_html)
                        ).add_to(m)
                else:
                    st.warning("⚠️ Excel sin columnas LAT/LON")

            elif modo == "Código Postal (Polígonos)":
                with st.spinner(f"Cargando {archivo_sel}..."):
                    gdf_est, col_cp_json = cargar_capa_estado(archivo_sel)
                if gdf_est is not None and 'CP' in df_ver.columns:
                    df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                    merged = gdf_est.merge(df_ver, left_on=col_cp_json, right_on='CP')
                    
                    if not merged.empty:
                        m.location = [merged.geometry.centroid.y.mean(), merged.geometry.centroid.x.mean()]
                        m.zoom_start = 9
                        for _, fila in merged.iterrows():
                            color = COLORS.get(fila['RANGO_ID'], "#888")
                            tooltip_html = f"<b>CP: {fila['CP']}</b><br>Nombre: {fila.get('NOMBRE','')}<br><span style='color:red;'>Vol: {fila.get('VOLUMEN', 0)}</span>"
                            folium.GeoJson(
                                fila['geometry'],
                                style_function=lambda x, c=color: {'fillColor': c, 'color': 'black', 'weight': 1, 'fillOpacity': 0.6},
                                tooltip=folium.Tooltip(tooltip_html)
                            ).add_to(m)
                    else:
                        st.warning(f"No hay datos para {archivo_sel} en el Excel.")

            st_folium(m, width="100%", height=700, key="mapa_final")

            # Botón de Descarga
            map_html = io.BytesIO()
            m.save(map_html, close_file=False)
            st.download_button(label="💾 Descargar Mapa HTML", data=map_html.getvalue(), file_name=f"Visualizador_{archivo_sel}.html", mime="text/html")
        else:
            st.info("👋 Por favor sube un archivo Excel para comenzar.")

elif authentication_status is False:
    st.error('Usuario o contraseña incorrectos')
elif authentication_status is None:
    st.warning('Por favor, introduce tu usuario y contraseña')
    st.info('Soporte: gxsilvia@outlook.com')
