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

# --- 1. SEGURIDAD ---
with open('config.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'], config['cookie']['name'],
    config['cookie']['key'], config['cookie']['expiry_days']
)

authenticator.login()

if st.session_state.get("authentication_status"):
    # Configuración de página (Debe ser lo primero)
    st.set_page_config(page_title="Visualizador Pro", layout="wide")
    name = st.session_state["name"]
    
    st.sidebar.write(f'Bienvenido **{name}**')
    authenticator.logout('Cerrar Sesión', 'sidebar')
    st.title("📍 Visualizador Pro")

    # --- 2. LÓGICA Y COLORES ---
    COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FFA500", 3:"#FF7777", 4:"#FF0000", 5:"#800000"}

    def asignar_rango(v):
        try:
            val = float(v)
            return 0 if val==0 else 1 if val<=15 else 2 if val<=20 else 3 if val<=30 else 4 if val<=40 else 5
        except: return 0

    def normalizar_columnas(df):
        df.columns = df.columns.str.strip().str.upper()
        mapeo = {'LATITUD': 'LAT', 'LONGITUD': 'LON', 'CODIGO POSTAL': 'CP', 'VOLUMEN': 'VOLUMEN', 'NOMBRE': 'NOMBRE', 'RADIO': 'RADIO'}
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

    # --- 3. PANEL DE CONTROL (FILTROS 3x3) ---
    col_mapa, col_controles = st.columns([3.5, 1])

    with col_controles:
        st.subheader("⚙️ Configuración")
        modo = st.radio("Método de Ubicación", ["Coordenadas (Puntos)", "Código Postal (Polígonos)"])
        
        archivos_geo = [f for f in os.listdir('mapas') if f.endswith(('.geojson', '.json'))] if os.path.exists('mapas') else []
        archivo_sel = st.selectbox("Estado a visualizar", sorted(archivos_geo))
        
        st.markdown("---")
        st.subheader("📊 Filtros de Rango")
        
        # Organización 3 y 3
        labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R40+"]
        f_checks = []
        c1, c2 = st.columns(2)
        for i in range(6):
            target_col = c1 if i < 3 else c2
            f_checks.append(target_col.checkbox(labels[i], value=True, key=f"f_{i}"))
        
        st.markdown("---")
        ver_etiquetas = st.toggle("🏷️ Mostrar Nombres fijos", value=False)
        archivo_excel = st.file_uploader("📂 Sube tu Excel", type=["xlsx"])

    # --- 4. MAPA Y PROCESAMIENTO ---
    with col_mapa:
        if archivo_excel:
            df = pd.read_excel(archivo_excel)
            df = normalizar_columnas(df)
            df['RANGO_ID'] = df['VOLUMEN'].apply(asignar_rango)
            
            activos = [i for i, v in enumerate(f_checks) if v]
            df_ver = df[df['RANGO_ID'].isin(activos)].copy()

            m = folium.Map(location=[19.4326, -99.1332], zoom_start=6, control_scale=True)

            if modo == "Coordenadas (Puntos)" and not df_ver.empty:
                m.location = [df_ver['LAT'].mean(), df_ver['LON'].mean()]
                for _, fila in df_ver.iterrows():
                    color = COLORS.get(fila['RANGO_ID'], "#888")
                    folium.Circle(
                        [fila['LAT'], fila['LON']], radius=float(fila.get('RADIO', 800)),
                        color="black", weight=1, fill=True, fill_color=color, fill_opacity=0.6,
                        tooltip=f"Vol: {fila['VOLUMEN']}"
                    ).add_to(m)
                    if ver_etiquetas:
                        folium.Marker([fila['LAT'], fila['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold;">{fila.get("NOMBRE","")}</div>')).add_to(m)

            elif modo == "Código Postal (Polígonos)":
                gdf_est, col_cp_json = cargar_capa_estado(archivo_sel)
                if gdf_est is not None:
                    df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                    merged = gdf_est.merge(df_ver, left_on=col_cp_json, right_on='CP')
                    
                    if not merged.empty:
                        m.location = [merged.geometry.centroid.y.mean(), merged.geometry.centroid.x.mean()]
                        for _, fila in merged.iterrows():
                            color = COLORS.get(fila['RANGO_ID'], "#888")
                            folium.GeoJson(
                                fila['geometry'],
                                style_function=lambda x, c=color: {'fillColor': c, 'color': 'black', 'weight': 1, 'fillOpacity': 0.6},
                                tooltip=f"CP: {fila['CP']} | Vol: {fila['VOLUMEN']}"
                            ).add_to(m)
                            if ver_etiquetas:
                                c = fila['geometry'].centroid
                                folium.Marker([c.y, c.x], icon=folium.features.DivIcon(html=f'<div style="font-size:7pt; text-align:center;">{fila.get("NOMBRE","")}</div>')).add_to(m)

            st_folium(m, width="100%", height=700, key="mapa_vpro")

            # --- BOTÓN DE DESCARGA REPARADO ---
            html_data = m._repr_html_()
            st.download_button(
                label="💾 Descargar Mapa HTML",
                data=html_data,
                file_name=f"Mapa_{archivo_sel.split('.')[0]}.html",
                mime="text/html"
            )
        else:
            st.info("👋 Sube un archivo Excel para comenzar.")

elif st.session_state.get("authentication_status") is False:
    st.error('Error de acceso')
