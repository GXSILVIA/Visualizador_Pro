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

# --- 1. CONFIGURACIÓN Y SEGURIDAD ---
st.set_page_config(page_title="Visualizador Pro", layout="wide")

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
            
            # Buscador de columna de CP en el GeoJSON
            posibles = ['d_cp', 'CP', 'codigopostal', 'CODIGO_POSTAL']
            col_encontrada = next((p for p in posibles if p in gdf.columns), None)
            
            if col_encontrada is None:
                col_encontrada = gdf.columns[0]
            
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
        
        if "Código Postal" in modo:
            labels = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"]
        else:
            labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
        
        activos = []
        c1, c2 = st.columns(2)
        for i in range(6):
            target = c1 if i < 3 else c2
            if target.checkbox(labels[i], value=True, key=f"f_{i}_{modo}"): activos.append(i)
        
        ver_nombres = st.toggle("🏷️ Mostrar Nombres + Volumen", value=True)
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        
        btn_actualizar = st.button("🔄 Actualizar Mapa", use_container_width=True)

        if (archivo_excel and btn_actualizar) or (archivo_excel and st.session_state.get('last_fn') != archivo_excel.name):
            progreso = st.progress(0, text="🚀 Procesando archivo...")
            df_raw = pd.read_excel(archivo_excel)
            df_raw.columns = df_raw.columns.str.strip().str.upper()
            
            # Mapeo de columnas (Nombre, CP, Volumen, Radio, Lat, Lon)
            renom = {'NOMBRE':'NOMBRE', 'CP':'CP', 'VOLUMEN':'VOL', 'VOL':'VOL', 'LAT':'LATITUD', 'LON':'LONGITUD', 'RADIO':'RADIO'}
            df_proc = df_raw.rename(columns=renom)
            
            func_rango = rango_postal if "Código Postal" in modo else rango_coordenadas
            df_proc['VOL'] = pd.to_numeric(df_proc['VOL'], errors='coerce').fillna(0)
            df_proc['RANGO_ID'] = df_proc['VOL'].apply(func_rango)
            
            st.session_state.df_datos = df_proc
            st.session_state.last_fn = archivo_excel.name
            
            if 'LATITUD' in df_proc.columns:
                st.session_state.map_center = [df_proc['LATITUD'].dropna().mean(), df_proc['LONGITUD'].dropna().mean()]
            
            progreso.progress(100, text="✅ Proceso completado")
            st.rerun()
        elif archivo_excel is None:
            st.session_state.df_datos = None

    # --- 4. RENDERIZADO DEL MAPA ---
    with col_mapa:
        if st.session_state.df_datos is not None:
            df_ver = st.session_state.df_datos.copy()
            df_ver = df_ver[df_ver['RANGO_ID'].isin(activos)]
            
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if "Código Postal" in modo:
                gdf, col_geo = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    # Centrar en el estado seleccionado
                    m.location = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
                    df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                    merged = gdf.merge(df_ver, left_on=col_geo, right_on='CP')
                    
                    for _, fila in merged.iterrows():
                        c_p = COLORS.get(fila['RANGO_ID'], "#888")
                        folium.GeoJson(fila['geometry'], style_function=lambda x, c=c_p: {
                            'fillColor': c, 'color': '#444444', 'weight': 1.5, 'fillOpacity': 0.25, 'opacity': 0.7
                        }).add_to(m)
                        if ver_nombres:
                            cen = fila['geometry'].centroid
                            folium.Marker([cen.y, cen.x], icon=folium.features.DivIcon(html=f'<div style="font-size: 8pt; color: #333; font-weight: bold; text-shadow: 1px 1px 2px white; text-align: center; width: 120px;">{fila.get("NOMBRE","")}<br><span style="color: #d32f2f; font-size: 7pt;">({int(fila["VOL"])})</span></div>')).add_to(m)        
            else:
                for _, fila in df_ver.iterrows():
                    lat, lon = fila.get('LATITUD'), fila.get('LONGITUD')
                    if pd.notnull(lat) and pd.notnull(lon):
                        c_c = COLORS.get(fila['RANGO_ID'], "#888")
                        # TOMA EL RADIO DIRECTO DEL ARCHIVO EXCEL
                        radio_val = float(fila.get('RADIO', 500)) 
                        
                        folium.Circle(
                            location=[lat, lon], radius=radio_val, color=c_c, weight=2.5, 
                            fill=True, fill_color=c_c, fill_opacity=0.45
                        ).add_to(m)
                        
                        if ver_nombres:
                            folium.Marker([lat, lon], icon=folium.features.DivIcon(html=f'<div style="font-size: 8.5pt; color: black; font-weight: bold; text-shadow: 2px 2px 4px white; text-align: center; width: 120px;">{fila.get("NOMBRE","")}<br><span style="color: #d32f2f;">({int(fila["VOL"])})</span></div>')).add_to(m)

            st_folium(m, width=1100, height=650, key=f"vpro_{modo}_{hash(str(activos))}")

            # NOMENCLATURA DINÁMICA CON FECHA Y HORA
            nom_est = os.path.splitext(archivo_sel)[0] if archivo_sel else "estado"
            prefijo = "qq_" if "Código Postal" in modo else "zonas_"
            fecha_str = datetime.now().strftime("%Y%m%d_%H%M")
            fn_final = f"{prefijo}{nom_est}_{fecha_str}.html"

            b64 = base64.b64encode(m._repr_html_().encode()).decode()
            st.markdown(f'<a href="data:text/html;base64,{b64}" download="{fn_final}" style="text-decoration:none;"><button style="width:100%; cursor:pointer; background-color:#FF4B4B; color:white; border:none; padding:12px; border-radius:5px; font-weight:bold; margin-top:10px;">💾 DESCARGAR: {fn_final.upper()}</button></a>', unsafe_allow_html=True)
        else:
            st.info("👋 Por favor, carga un archivo Excel para visualizar los datos.")

elif st.session_state.get("authentication_status") is False:
    st.error('Usuario/Contraseña incorrectos')
