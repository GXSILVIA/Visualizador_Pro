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

# Inicializar estados de sesión para que el mapa persista
if "mapa_objeto" not in st.session_state:
    st.session_state.mapa_objeto = None
if "nombre_mapa" not in st.session_state:
    st.session_state.nombre_mapa = ""

with open('config.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'], config['cookie']['name'],
    config['cookie']['key'], config['cookie']['expiry_days']
)

authenticator.login()

if st.session_state.get("authentication_status"):
    st.sidebar.write(f'Bienvenido **{st.session_state["name"]}**')
    authenticator.logout('Cerrar Sesión', 'sidebar')
    st.title("📍 Visualizador Pro")

    # COLORES MÁXIMO BRILLO
    COLORS = {
        0: "#FFFFFF", 1: "#FFFF00", 2: "#FF9900", 
        3: "#FF4444", 4: "#FF0000", 5: "#660000"
    }

    def asignar_rango(v):
        try:
            val = float(v)
            return 0 if val==0 else 1 if val<=15 else 2 if val<=20 else 3 if val<=30 else 4 if val<=40 else 5
        except: return 0

    def normalizar_columnas(df):
        df.columns = df.columns.str.strip().str.upper()
        mapeo = {'LATITUD': 'LAT', 'LONGITUD': 'LON', 'CODIGO POSTAL': 'CP', 'CP': 'CP', 'VOLUMEN': 'VOLUMEN', 'NOMBRE': 'NOMBRE', 'RADIO': 'RADIO'}
        return df.rename(columns=mapeo)

    @st.cache_data(ttl=3600)
    def cargar_capa_estado(nombre_archivo):
        ruta = f"mapas/{nombre_archivo}"
        if os.path.exists(ruta):
            gdf = gpd.read_file(ruta)
            # Limpieza de duplicados y optimización para archivos pesados
            gdf = gdf.loc[:, ~gdf.columns.duplicated()].copy()
            # Simplificar geometría (reduce peso de 300MB para que el navegador no colapse)
            gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.001, preserve_topology=True)
            
            posibles = ['d_cp', 'CP', 'codigopostal', 'CODIGO_POSTAL']
            col_json = next((c for c in posibles if c in gdf.columns), gdf.columns[0])
            gdf[col_json] = gdf[col_json].astype(str).str.zfill(5)
            return gdf, col_json
        return None, None

    # --- 2. PANEL DE CONTROL ---
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
            f_checks.append(target.checkbox(labels[i], value=True, key=f"v_range_{i}"))
        
        ver_nombres = st.toggle("🏷️ Mostrar nombres", value=False)
        archivo_excel = st.file_uploader("📂 Sube tu Excel", type=["xlsx"])
        btn_procesar = st.button("🚀 Procesar Datos", use_container_width=True)

    # --- 3. LÓGICA DE PROCESAMIENTO Y RENDERIZADO ---
    with col_mapa:
        # Si se pulsa el botón, generamos el mapa y lo guardamos en la sesión
        if archivo_excel and btn_procesar:
            with st.spinner(f"Generando mapa de {archivo_sel}..."):
                df = pd.read_excel(archivo_excel)
                df = normalizar_columnas(df)
                df['RANGO_ID'] = df['VOLUMEN'].apply(asignar_rango)
                activos = [i for i, v in enumerate(f_checks) if v]
                df_ver = df[df['RANGO_ID'].isin(activos)].copy()

                # Crear mapa base
                m = folium.Map(location=[19.4326, -99.1332], zoom_start=6, tiles="CartoDB.Positron")

                if modo == "Código Postal (Polígonos)":
                    gdf_est, col_cp_json = cargar_capa_estado(archivo_sel)
                    if gdf_est is not None:
                        df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                        merged = gdf_est.merge(df_ver, left_on=col_cp_json, right_on='CP')
                        
                        if not merged.empty:
                            # Centrar mapa
                            m.location = [merged.geometry.centroid.y.mean(), merged.geometry.centroid.x.mean()]
                            for _, fila in merged.iterrows():
                                color_poly = COLORS.get(fila['RANGO_ID'], "#888")
                                folium.GeoJson(
                                    fila['geometry'],
                                    style_function=lambda x, c=color_poly: {
                                        'fillColor': c, 'color': 'black', 'weight': 1, 'fillOpacity': 0.8
                                    },
                                    tooltip=f"CP: {fila['CP']} | Vol: {fila['VOLUMEN']}"
                                ).add_to(m)
                                
                                if ver_nombres:
                                    centro = fila['geometry'].centroid
                                    folium.Marker([centro.y, centro.x], 
                                        icon=folium.features.DivIcon(html=f'''
                                            <div style="font-size:7pt; font-weight:900; color:black; 
                                            background-color:rgba(255,255,255,0.8); border:0.5px solid grey; 
                                            text-align:center; width:80px; border-radius:2px;">
                                                {fila.get("NOMBRE","")}
                                            </div>''')
                                    ).add_to(m)

                # Guardar el mapa generado en el estado de sesión
                st.session_state.mapa_objeto = m
                st.session_state.nombre_mapa = archivo_sel

        # MOSTRAR EL MAPA SI EXISTE EN SESIÓN (Esto evita que se borre)
        if st.session_state.mapa_objeto is not None:
            st_folium(
                st.session_state.mapa_objeto, 
                width=1100, # Ancho fijo para estabilidad
                height=700, 
                key=f"mapa_fijo_{st.session_state.nombre_mapa}"
            )
            
            # Botón de descarga siempre disponible si hay un mapa
            st.download_button(
                label="💾 Descargar Mapa Actual (HTML)", 
                data=st.session_state.mapa_objeto._repr_html_(), 
                file_name=f"Mapa_{st.session_state.nombre_mapa}.html", 
                mime="text/html", 
                use_container_width=True
            )
        else:
            st.info("👋 Sube tu Excel y presiona 'Procesar Datos' para visualizar.")

elif st.session_state.get("authentication_status") is False:
    st.error('Usuario o contraseña incorrectos')
elif st.session_state.get("authentication_status") is None:
    st.warning('Por favor, ingresa tus credenciales')
