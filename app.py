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
st.set_page_config(page_title="Kaizen Amazon Hub", layout="wide")

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
    authenticator.login(location='main')
except Exception as e:
    st.error(f"Error en config.yaml: {e}"); st.stop()

if st.session_state.get("authentication_status"):
    
    # --- 2. FUNCIONES DE RANGO ---
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
        st.title("📦 Panel")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        
        modo = st.radio("Modo de Visualización", ["Coordenadas (Vecino Repartidor)", "Código Postal (Quesadillas con Queso)"])
        archivos = [f for f in os.listdir('mapas') if f.endswith(('.geojson', '.json'))] if os.path.exists('mapas') else []
        archivo_sel = st.selectbox("Seleccionar Estado", sorted(archivos))
        
        st.markdown("---")
        st.subheader("📊 Filtros de Saturación")
        
        if modo == "Código Postal (Quesadillas con Queso)":
            labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"]
        else:
            labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R40+"]
        
        activos = []
        c1, c2 = st.columns(2)
        for i in range(6):
            target = c1 if i < 3 else c2
            if target.checkbox(labels[i], value=True, key=f"f_{i}_{modo}"):
                activos.append(i)
        
        ver_nombres = st.toggle("🏷️ Mostrar Nombres + Volumen", value=True)
        archivo_excel = st.file_uploader("📂 Cargar Excel ", type=["xlsx"])
        
        btn_actualizar = st.button("🔄 Actualizar Mapa", use_container_width=True)

        # SECCIÓN CORREGIDA CON BARRA DE PROGRESO
        if (archivo_excel and btn_actualizar) or (archivo_excel and st.session_state.get('last_fn') != archivo_excel.name):
            progreso = st.progress(0, text="🚀 Iniciando procesamiento Kaizen...")
            
            df_raw = pd.read_excel(archivo_excel)
            progreso.progress(30, text="📖 Leyendo registros y limpiando columnas...")
            
            df_raw.columns = df_raw.columns.str.strip().str.upper()
            renom = {'LAT':'LATITUD', 'LON':'LONGITUD', 'VOLUMEN':'VOL', 'CODIGO POSTAL':'CP'}
            df_proc = df_raw.rename(columns=renom)
            
            progreso.progress(60, text="🧹 Calculando rangos de saturación...")
            func_rango = rango_postal if modo == "Código Postal (Quesadillas con Queso)" else rango_coordenadas
            if 'VOL' not in df_proc.columns: df_proc['VOL'] = 0
            df_proc['RANGO_ID'] = df_proc['VOL'].apply(func_rango)
            
            st.session_state.df_datos = df_proc
            st.session_state.last_fn = archivo_excel.name
            
            if 'LATITUD' in df_proc.columns and not df_proc['LATITUD'].dropna().empty:
                st.session_state.map_center = [df_proc['LATITUD'].mean(), df_proc['LONGITUD'].mean()]
            
            progreso.progress(100, text="✅ ¡Mapa optimizado correctamente!")
            st.rerun()
        
        elif archivo_excel is None:
            st.session_state.df_datos = None
            st.info("👋 Sube un archivo para identificar zonas saturadas.")

    # --- 4. RENDERIZADO DEL MAPA ---
    with col_mapa:
        if st.session_state.df_datos is not None:
            df_ver = st.session_state.df_datos.copy()
            func_rango = rango_postal if modo == "Código Postal (Quesadillas con Queso)" else rango_coordenadas
            df_ver['RANGO_ID'] = df_ver['VOL'].apply(func_rango)
            df_ver = df_ver[df_ver['RANGO_ID'].isin(activos)]
            
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if modo == "Código Postal (Quesadillas con Queso)":
                gdf, col_cp = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    # Auto-centrado en el estado
                    centro_estado = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
                    m.location = centro_estado 
                    
                    df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                    merged = gdf.merge(df_ver, left_on=col_cp, right_on='CP')
                    
                    for _, fila in merged.iterrows():
                        color_p = COLORS.get(fila['RANGO_ID'], "#888")
                        folium.GeoJson(
                            fila['geometry'],
                            style_function=lambda x, c=color_p: {
                                'fillColor': c, 
                                'color': '#444444', # EFECTO MATE
                                'weight': 1.5, 
                                'fillOpacity': 0.20,
                                'opacity': 0.7
                            }
                        ).add_to(m)
                        
                        if ver_nombres:
                            cen = fila['geometry'].centroid
                            folium.Marker([cen.y, cen.x], icon=folium.features.DivIcon(html=f'<div style="font-size: 8pt; color: #333; font-weight: bold; text-shadow: 1px 1px 2px white; text-align: center; width: 120px;">{fila.get("NOMBRE","")}<br><span style="color: #d32f2f; font-size: 7pt;">({fila["VOL"]})</span></div>')).add_to(m)        
                            
            else: # MODO COORDENADAS
                for _, fila in df_ver.iterrows():
                    lat, lon = fila.get('LATITUD'), fila.get('LONGITUD')
                    if pd.notnull(lat) and pd.notnull(lon):
                        color_c = COLORS.get(fila['RANGO_ID'], "#888")
                        folium.Circle(location=[lat, lon], radius=fila.get('RADIO', 150), color=color_c, weight=2, fill=True, fill_color=color_c, fill_opacity=0.4).add_to(m)
                        if ver_nombres:
                            folium.Marker([lat, lon], icon=folium.features.DivIcon(html=f'<div style="font-size: 8pt; color: black; font-weight: bold; text-shadow: 2px 2px 4px white; text-align: center; width: 100px;">{fila.get("NOMBRE","")}<br><span style="color: #d32f2f;">({fila["VOL"]})</span></div>')).add_to(m)


                       # --- SECCIÓN DE RENDERIZADO FINAL (Muestra el mapa) ---
            st_folium(m, width=1100, height=650, key=f"map_{modo}_{hash(str(activos))}")

            # --- SECCIÓN DE DESCARGA (Funciona para ambos modos) ---
            # 1. Convertimos el mapa actual a HTML
            mapa_html = m._repr_html_()
            # 2. Lo codificamos para que el navegador lo entienda como descarga
            b64 = base64.b64encode(mapa_html.encode()).decode()
            
            # 3. Creamos el botón rojo de descarga
            st.markdown(f'''
                <a href="data:text/html;base64,{b64}" download="_{modo}.html" style="text-decoration:none;">
                    <button style="width:100%; cursor:pointer; background-color:#FF4B4B; color:white; 
                    border:none; padding:12px; border-radius:5px; font-weight:bold; margin-top:10px;">
                        💾 DESCARGAR MAPA ACTUAL ({modo.upper()})
                    </button>
                </a>
            ''', unsafe_allow_html=True)
