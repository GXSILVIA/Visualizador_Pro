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

    # --- 2. COLORES NEÓN (BRILLO MÁXIMO) ---
    COLORS = {
        0: "#FFFFFF", 1: "#FFFF00", 2: "#FFCC00", 
        3: "#FF3333", 4: "#FF0000", 5: "#660000"
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

    @st.cache_data
    def cargar_capa_estado(nombre_archivo):
        ruta = f"mapas/{nombre_archivo}"
        if os.path.exists(ruta):
            gdf = gpd.read_file(ruta)
            posibles = ['d_cp', 'CP', 'codigopostal']
            col_json = next((c for c in posibles if c in gdf.columns), gdf.columns)
            col_data = gdf[col_json]
            if isinstance(col_data, pd.DataFrame): col_data = col_data.iloc[:, 0]
            gdf[col_json] = col_data.astype(str).str.zfill(5)
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
            # El on_change=None asegura que Streamlit detecte el cambio de estado inmediatamente
            f_checks.append(target.checkbox(labels[i], value=True, key=f"range_check_{i}"))
        
        st.markdown("---")
        ver_nombres = st.toggle("🏷️ Mostrar etiquetas fijas", value=False)
        archivo_excel = st.file_uploader("📂 Sube tu Excel", type=["xlsx"])

    # --- 4. LÓGICA DEL MAPA ---
    with col_mapa:
        if archivo_excel:
            df = pd.read_excel(archivo_excel)
            df = normalizar_columnas(df)
            df['RANGO_ID'] = df['VOLUMEN'].apply(asignar_rango)
            
            # --- FILTRADO REAL DE DATOS ---
            activos = [i for i, v in enumerate(f_checks) if v]
            df_filtrado = df[df['RANGO_ID'].isin(activos)].copy()

            # Mapa base limpio para que brillen los colores
            m = folium.Map(location=[19.4326, -99.1332], zoom_start=6, tiles="cartodbpositron")

            if modo == "Coordenadas (Puntos)" and not df_filtrado.empty:
                m.location = [df_filtrado['LAT'].mean(), df_filtrado['LON'].mean()]
                for _, fila in df_filtrado.iterrows():
                    color_marker = COLORS.get(fila['RANGO_ID'], "#888")
                    folium.Circle(
                        [fila['LAT'], fila['LON']], radius=float(fila.get('RADIO', 800)),
                        color="#444", weight=1, fill=True, fill_color=color_marker, fill_opacity=0.85,
                        tooltip=f"<b>{fila.get('NOMBRE','')}</b><br>Vol: {fila['VOLUMEN']}"
                    ).add_to(m)
                    
                    if ver_nombres:
                        folium.Marker(
                            [fila['LAT'], fila['LON']], 
                            icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:black; background-color:white; border:1px solid black; padding:1px; width:120px;">{fila.get("NOMBRE","")}</div>')
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
                                style_function=lambda x, c=color_poly: {'fillColor': c, 'color': 'black', 'weight': 1, 'fillOpacity': 0.85},
                                tooltip=f"<b>CP: {fila['CP']}</b><br>Vol: {fila['VOLUMEN']}"
                            ).add_to(m)
                            
                            if ver_nombres:
                                centro = fila['geometry'].centroid
                                folium.Marker(
                                    [centro.y, centro.x], 
                                    icon=folium.features.DivIcon(html=f'<div style="font-size:7pt; font-weight:bold; text-align:center; text-shadow: 1px 1px 1px white;">{fila.get("NOMBRE","")}</div>')
                                ).add_to(m)

            # USAR UNA KEY DINÁMICA BASADA EN LOS FILTROS PARA FORZAR EL REFREZCO
            # Esto soluciona que el mapa no cambie al desmarcar rangos
            key_mapa = f"mapa_{hash(tuple(f_checks))}_{modo}"
            st_folium(m, width="100%", height=700, key=key_mapa)

            # DESCARGA DEL MAPA ACTUAL (RESPETA FILTROS)
            map_html = m._repr_html_()
            st.download_button(
                label="💾 Descargar Mapa Actual (HTML)",
                data=map_html,
                file_name=f"Visualizador_{archivo_sel.replace('.geojson','')}.html",
                mime="text/html"
            )
        else:
            st.info("Sube tu archivo Excel para comenzar.")

elif st.session_state.get("authentication_status") is False:
    st.error('Acceso denegado')
