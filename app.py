#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap
import os
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium
from datetime import datetime

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

if 'dict_datos' not in st.session_state: st.session_state.dict_datos = {}
if 'map_center' not in st.session_state: st.session_state.map_center = [19.4326, -99.1332]

try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, auth_status, username = authenticator.login(location='main')
except: st.error("Error de configuración de seguridad."); st.stop()

if auth_status:
    # --- 2. LÓGICA DE PROCESAMIENTO ---
    def normalizar_df(df, modo_ref):
        df.columns = df.columns.str.strip().str.upper()
        cols = df.columns
        mapa = {
            'LAT': ['LAT', 'LATITUD'], 'LON': ['LON', 'LONGITUD'],
            'VOL': ['VOL', 'VOLUMEN'], 'RAD': ['RADIO', 'RAD'],
            'CP':  ['CP', 'C.P.'], 'NOM': ['NOMBRE', 'ZONA'],
            'PER': ['PERSONA', 'RESPONSABLE']
        }
        rename_dict = {}
        for destino, sinonimos in mapa.items():
            encontrado = next((c for c in cols if c in sinonimos), None)
            if encontrado: rename_dict[encontrado] = destino
        
        df = df.rename(columns=rename_dict)
        df['VOL'] = pd.to_numeric(df.get('VOL', 0), errors='coerce').fillna(0)
        df['RAD'] = pd.to_numeric(df.get('RAD', 750), errors='coerce').fillna(750)
        if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'Zona')
        if 'PER' not in df.columns: df['PER'] = "N/A"
        
        # --- DEFINICIÓN DE LÍMITES ---
        def asignar_rango(v):
            if v <= 0: return 0
            if "Polígonos" in modo_ref:
                lims = [100, 200, 300, 400]
            else:
                lims = [15, 20, 30, 40]
            for i, l in enumerate(lims, 1):
                if v <= l: return i
            return 5

        df['RANGO_ID'] = df['VOL'].apply(asignar_rango)
        total_z = df.groupby('NOM')['VOL'].transform('sum')
        df['PORC_ZONA'] = (df['VOL'] / total_z * 100).round(1).fillna(0)
        return df

    @st.cache_data
    def cargar_capa_estado(archivo):
        ruta = f"mapas/{archivo}"
        if os.path.exists(ruta):
            import geopandas as gpd
            gdf = gpd.read_file(ruta).to_crs("EPSG:4326")
            gdf['geometry'] = gdf['geometry'].simplify(0.002)
            col_geo = next((p for p in ['d_cp', 'CP', 'CODIGOPOSTAL'] if p in gdf.columns), gdf.columns[0])
            return gdf, col_geo
        return None, None

    # --- 3. PANEL DE CONTROL ---
    col_mapa, col_controles = st.columns([3, 1.3])
    with col_controles:
        st.title("🛡️ Panel AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP", "Mapa de Calor (Análisis)"])
        
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar Datos"):
            xl = pd.ExcelFile(archivo_excel)
            st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            st.rerun()

        if st.session_state.dict_datos:
            periodos = list(st.session_state.dict_datos.keys())
            fecha_sel = st.select_slider("🕒 Historial:", options=periodos) if len(periodos) > 1 else periodos[0]
            df_act = st.session_state.dict_datos[fecha_sel]
            
            st.markdown("---")
            st.subheader("📊 Filtros de Rango")
            
            # --- DEFINICIÓN DE ETIQUETAS CON CANTIDADES QUE ABARCAN ---
            if "Polígonos" in modo:
                rangos_txt = ["0", "1-100", "101-200", "201-300", "301-400", "401+"]
            else:
                rangos_txt = ["0", "1-15", "16-20", "21-30", "31-40", "41+"]
            
            stats = df_act.groupby('RANGO_ID')['VOL'].agg(['count', 'sum'])
            iconos = ["⚪", "🟡", "🟠", "🔴", "🏮", "🍷"]
            nombres = ["R0", "R1", "R2", "R3", "R4", "R5"]
            
            activos = []
            f1, f2 = st.columns(2)
            for i in range(6):
                col_ui = f1 if i < 3 else f2
                n = int(stats.loc[i, 'count']) if i in stats.index else 0
                v = int(stats.loc[i, 'sum']) if i in stats.index else 0
                # Etiqueta Final: Icono + Nombre + Rango Numérico + Estadísticas
                label = f"{iconos[i]} {nombres[i]} ({rangos_txt[i]}) \n [{n} pts | Vol: {v}]"
                if col_ui.checkbox(label, value=True, key=f"r_{i}_{modo}"):
                    activos.append(i)
            
            ver_nombres = st.toggle("🏷️ Ver Nombres Fijos", value=True)
            if "Polígonos" in modo:
                archivos = sorted([f for f in os.listdir('mapas') if f.endswith(('.json', '.geojson'))])
                archivo_sel = st.selectbox("Mapa Base", archivos)

    # --- 4. RENDERIZADO ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act[df_act['RANGO_ID'].isin(activos)].copy()
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if "Calor" in modo:
                df_h = df_m.dropna(subset=['LAT', 'LON'])
                # Mapa de calor como CONJUNTO (Radio y Blur altos)
                HeatMap([[f['LAT'], f['LON'], f['VOL']] for _, f in df_h.iterrows()], 
                        radius=50, blur=30, min_opacity=0.4).add_to(m)
            else:
                for _, f in df_m.dropna(subset=['LAT', 'LON']).iterrows():
                    c = COLORS.get(f['RANGO_ID'], "#888")
                    folium.Circle(location=[f['LAT'], f['LON']], radius=f['RAD'], color=c, fill=True, fill_color=c, fill_opacity=0.3, weight=1.5,
                                  tooltip=f"<b>{f['PER']}</b><br>Vol: {int(f['VOL'])}<br>Reparto: {f['PORC_ZONA']}%").add_to(m)
                    if ver_nombres:
                        # NOMBRES EN NEGRO con sombra blanca para legibilidad total
                        style = f'''<div style="font-size:8pt; color:#000; font-weight:bold; text-align:center; 
                                   width:100px; text-shadow: 2px 2px 3px #FFF, -2px -2px 3px #FFF;">{f["PER"]}</div>'''
                        folium.Marker([f['LAT'], f['LON']], icon=folium.features.DivIcon(html=style, icon_anchor=(50, 0))).add_to(m)

            if not df_m.empty: m.fit_bounds([[df_m['LAT'].min(), df_m['LON'].min()], [df_m['LAT'].max(), df_m['LON'].max()]])
            st_folium(m, width="100%", height=550)

            # --- INFORME EJECUTIVO ---
            st.markdown("---")
            st.markdown(f"### 📊 Informe Ejecutivo AMZL - {fecha_sel}")
            c1, c2, c3 = st.columns([1, 1.5, 1.5])
            u_total = df_m['VOL'].sum()
            c1.metric("Universo Total", f"{int(u_total):,}")
            top_p = df_m.groupby('PER')['VOL'].sum().sort_values(ascending=False).head(5)
            c2.write("**🔥 Impacto por Responsable:**")
            for p, v in top_p.items():
                c2.caption(f"{p}: {int(v):,} ({(v/u_total*100 if u_total>0 else 0):.1f}%)")
            enc = df_m[df_m.duplicated('NOM', keep=False)]
            c3.write(f"**🤝 Saturación:** {enc['NOM'].nunique()} zonas")
            z_sel = c3.selectbox("Analizar Reparto:", ["-"] + sorted(enc['NOM'].unique().tolist()))
            if z_sel != "-": st.table(enc[enc['NOM'] == z_sel][['PER', 'VOL', 'PORC_ZONA']])

            st.download_button("💾 Descargar Mapa", data=m._repr_html_().encode('utf-8'), file_name=f"reporte_{fecha_sel}.html", mime="text/html")

elif auth_status is False: st.error('Credenciales incorrectas')
