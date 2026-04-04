import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os
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
    st.set_page_config(page_title="Visualizador Pro", layout="wide")
    st.sidebar.write(f'Bienvenido **{st.session_state["name"]}**')
    authenticator.logout('Cerrar Sesión', 'sidebar')
    st.title("📍 Visualizador Pro")

    # --- 2. COLORES NEÓN (BRILLO POR CONTRASTE) ---
    COLORS = {
        0: "#FFFFFF", 1: "#FFFF00", 2: "#FFCC00", 
        3: "#FF5555", 4: "#FF0000", 5: "#770000"
    }

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
            gdf = gdf.loc[:, ~gdf.columns.duplicated()].copy()
            posibles = ['d_cp', 'CP', 'codigopostal', 'CODIGO_POSTAL']
            col_json = next((c for c in posibles if c in gdf.columns), gdf.columns)
            gdf[col_json] = gdf[col_json].astype(str).str.zfill(5)
            return gdf, col_json
        return None, None

    # --- 3. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3.5, 1])

    with col_controles:
        st.subheader("⚙️ Configuración")
        modo = st.radio("Capa activa", ["Coordenadas (Puntos)", "Código Postal (Polígonos)"])
        
        archivos = [f for f in os.listdir('mapas') if f.endswith(('.geojson', '.json'))] if os.path.exists('mapas') else []
        archivo_sel = st.selectbox("Estado", sorted(archivos))
        
        st.markdown("---")
        st.subheader("📊 Filtros de Rango")
        labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R40+"]
        f_checks = []
        c1, c2 = st.columns(2)
        for i in range(6):
            target = c1 if i < 3 else c2
            f_checks.append(target.checkbox(labels[i], value=True, key=f"range_{i}"))
        
        st.markdown("---")
        ver_nombres = st.toggle("🏷️ Mostrar etiquetas fijas", value=False)
        archivo_excel = st.file_uploader("📂 Selecciona tu Excel", type=["xlsx"])
        
        btn_procesar = st.button("🚀 Procesar Datos", use_container_width=True)

    # --- 4. MAPA ---
    with col_mapa:
        if archivo_excel and btn_procesar:
            # Spinner discreto para no oscurecer toda la pantalla
            with st.spinner("Procesando información geográfica..."):
                df = pd.read_excel(archivo_excel)
                df = normalizar_columnas(df)
                df['RANGO_ID'] = df['VOLUMEN'].apply(asignar_rango)
                
                activos = [i for i, v in enumerate(f_checks) if v]
                df_filtrado = df[df['RANGO_ID'].isin(activos)].copy()

                # MAPA OSCURO PARA QUE BRILLEN LOS COLORES NEÓN
                m = folium.Map(location=[19.4326, -99.1332], zoom_start=6, tiles="CartoDB.DarkMatter")

                if modo == "Coordenadas (Puntos)" and not df_filtrado.empty:
                    m.location = [df_filtrado['LAT'].mean(), df_filtrado['LON'].mean()]
                    for _, fila in df_filtrado.iterrows():
                        color_marker = COLORS.get(fila['RANGO_ID'], "#888")
                        folium.Circle(
                            [fila['LAT'], fila['LON']], radius=float(fila.get('RADIO', 800)),
                            color="#FFF", weight=0.5, fill=True, fill_color=color_marker, fill_opacity=0.9,
                            tooltip=f"<b>{fila.get('NOMBRE','')}</b><br>Vol: {fila['VOLUMEN']}"
                        ).add_to(m)
                        if ver_nombres:
                            # ETIQUETAS EN NEGRO CON FONDO BLANCO
                            folium.Marker(
                                [fila['LAT'], fila['LON']], 
                                icon=folium.features.DivIcon(html=f'''
                                    <div style="font-size:8pt; font-weight:bold; color:black; 
                                    background-color:white; border:1px solid black; padding:2px; 
                                    border-radius:3px; width:120px; text-align:center;">
                                        {fila.get("NOMBRE","")}
                                    </div>''')
                            ).add_to(m)

                elif modo == "Código Postal (Polígonos)":
                    gdf_est, col_cp_json = cargar_capa_estado(archivo_sel)
                    if gdf_est is not None:
                        df_filtrado['CP'] = df_filtrado['CP'].astype(str).str.zfill(5)
                        merged = gdf_est.merge(df_filtrado, left_on=col_cp_json, right_on='CP')
                        if not merged.empty:
                            m.location = [merged.geometry.centroid.y.mean(), merged.geometry.centroid.x.mean()]
                            for _, fila in merged.iterrows():
                                color_poly = COLORS.get(fila['RANGO_ID'], "#888")
                                folium.GeoJson(
                                    fila['geometry'],
                                    style_function=lambda x, c=color_poly: {'fillColor': c, 'color': 'white', 'weight': 0.5, 'fillOpacity': 0.85},
                                    tooltip=f"<b>CP: {fila['CP']}</b><br>Vol: {fila['VOLUMEN']}"
                                ).add_to(m)
                                if ver_nombres:
                                    centro = fila['geometry'].centroid
                                    # ETIQUETAS EN NEGRO CON SOMBRA BLANCA PARA MAPA OSCURO
                                    folium.Marker(
                                        [centro.y, centro.x], 
                                        icon=folium.features.DivIcon(html=f'''
                                            <div style="font-size:7pt; font-weight:bold; color:black; 
                                            background-color:rgba(255,255,255,0.8); padding:1px; 
                                            border-radius:2px; text-align:center; width:80px;">
                                                {fila.get("NOMBRE","")}
                                            </div>''')
                                    ).add_to(m)

            # MOSTRAR MAPA
            # La key dinámica asegura que se limpie el mapa anterior al cambiar filtros
            st_folium(m, width="100%", height=700, key=f"map_{hash(tuple(f_checks))}_{ver_nombres}_{modo}")

            # BOTÓN DE DESCARGA SIEMPRE DISPONIBLE TRAS PROCESAR
            st.download_button(
                label="💾 Descargar Mapa Actual (HTML)",
                data=m._repr_html_(),
                file_name=f"Mapa_{archivo_sel.replace('.geojson','')}.html",
                mime="text/html",
                use_container_width=True
            )
        else:
            st.info("👋 Selecciona tu archivo Excel y presiona 'Procesar' para visualizar.")

elif st.session_state.get("authentication_status") is False:
    st.error('Acceso denegado')
