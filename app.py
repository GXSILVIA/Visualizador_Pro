import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os
import base64
from streamlit_folium import st_folium

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Visualizador Pro", layout="wide")

# Mantener los datos en memoria para que los filtros funcionen sin re-subir el Excel
if "df_datos" not in st.session_state:
    st.session_state.df_datos = None

# --- FUNCIONES DE APOYO ---
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
        gdf['geometry'] = gdf['geometry'].simplify(0.001)
        posibles = ['d_cp', 'CP', 'codigopostal']
        col_json = next((c for c in posibles if c in gdf.columns), gdf.columns[0])
        gdf[col_json] = gdf[col_json].astype(str).str.zfill(5)
        return gdf, col_json
    return None, None

# --- PANEL DE CONTROL ---
col_mapa, col_controles = st.columns([3.5, 1])

with col_controles:
    st.subheader("⚙️ Configuración")
    modo = st.radio("Capa activa", ["Coordenadas", "Código Postal (Polígonos)"])
    
    archivos = [f for f in os.listdir('mapas') if f.endswith(('.geojson', '.json'))] if os.path.exists('mapas') else []
    archivo_sel = st.selectbox("Estado", sorted(archivos))
    
    st.markdown("---")
    st.subheader("📊 Filtros de Rango")
    labels = ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R40+"]
    activos = []
    c1, c2 = st.columns(2)
    for i in range(6):
        target = c1 if i < 3 else c2
        if target.checkbox(labels[i], value=True, key=f"f_{i}"):
            activos.append(i)
    
    ver_nombres = st.toggle("🏷️ Mostrar nombres", value=False)
    archivo_excel = st.file_uploader("📂 Sube tu Excel", type=["xlsx"])
    
    if archivo_excel:
        if st.button("🚀 Cargar/Actualizar Datos"):
            df = pd.read_excel(archivo_excel)
            df.columns = df.columns.str.strip().str.upper()
            df = df.rename(columns={'CODIGO POSTAL': 'CP', 'VOLUMEN': 'VOL'})
            df['RANGO_ID'] = df['VOL'].apply(asignar_rango)
            st.session_state.df_datos = df
            st.success("Datos cargados")

# --- RENDERIZADO DEL MAPA ---
with col_mapa:
    if st.session_state.df_datos is not None:
        df_ver = st.session_state.df_datos[st.session_state.df_datos['RANGO_ID'].isin(activos)]
        
        m = folium.Map(location=[19.4, -99.1], zoom_start=6, tiles="CartoDB.Positron")
        COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

        if modo == "Código Postal (Polígonos)":
            gdf, col_cp = cargar_capa_estado(archivo_sel)
            if gdf is not None:
                df_ver['CP'] = df_ver['CP'].astype(str).str.zfill(5)
                merged = gdf.merge(df_ver, left_on=col_cp, right_on='CP')
                
                for _, fila in merged.iterrows():
                    # POLÍGONO
                    folium.GeoJson(
                        fila['geometry'],
                        style_function=lambda x, c=COLORS.get(fila['RANGO_ID'], "#888"): {
                            'fillColor': c, 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.7
                        }
                    ).add_to(m)
                    
                    # NOMBRES (Sin recuadro, solo texto con sombra para visibilidad)
                    if ver_nombres:
                        centro = fila['geometry'].centroid
                        folium.Marker(
                            [centro.y, centro.x],
                            icon=folium.features.DivIcon(html=f'''
                                <div style="font-size: 8pt; color: black; font-weight: bold; 
                                text-shadow: 1px 1px 2px white; text-align: center; width: 100px;">
                                    {fila.get("NOMBRE","")}
                                </div>''')
                        ).add_to(m)

        # Mostrar mapa
        st_folium(m, width=1000, height=600, key=f"mapa_{hash(str(activos)+str(ver_nombres))}")

        # Botón de Descarga Robusto
        html_mapa = m._repr_html_()
        b64 = base64.b64encode(html_mapa.encode()).decode()
        href = f'<a href="data:text/html;base64,{b64}" download="mapa.html" style="text-decoration:none;"><button style="width:100%; cursor:pointer; background-color:#FF4B4B; color:white; border:none; padding:10px; border-radius:5px;">💾 DESCARGAR MAPA HTML</button></a>'
        st.markdown(href, unsafe_allow_html=True)
    else:
        st.info("Sube un Excel y haz clic en 'Cargar Datos'")
