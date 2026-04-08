#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap
import geopandas as gpd
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

# Autenticación
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, auth_status, username = authenticator.login(location='main')
except: st.stop()

if auth_status:
    # --- 2. PROCESAMIENTO CON RANGOS COMPLETOS ---
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
        df['RAD'] = pd.to_numeric(df.get('RAD', 8), errors='coerce').fillna(8)
        if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'Zona General')
        if 'PER' not in df.columns: df['PER'] = "N/A"
        
        # --- LÓGICA DE RANGOS DIFERENCIADA Y COMPLETA ---
        if "Polígonos" in modo_ref:
            # Rangos Polígonos (Escala 100-400)
            limites = [100, 200, 300, 400]
        else:
            # Rangos Coordenadas/Calor (Escala 15-40)
            limites = [15, 20, 30, 40]
            
        def asignar_rango(v):
            if v <= 0: return 0
            if v <= limites[0]: return 1
            if v <= limites[1]: return 2
            if v <= limites[2]: return 3
            if v <= limites[3]: return 4
            return 5

        df['RANGO_ID'] = df['VOL'].apply(asignar_rango)
        
        # Reparto por Zona
        total_z = df.groupby('NOM')['VOL'].transform('sum')
        df['PORC_ZONA'] = (df['VOL'] / total_z * 100).round(1).fillna(0)
        return df

    @st.cache_data
    def cargar_capa_estado(archivo):
        ruta = f"mapas/{archivo}"
        if os.path.exists(ruta):
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
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP", "Análisis Ejecutivo (Calor)"])
        
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            if "Análisis" in modo:
                st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            else:
                p1 = xl.sheet_names[0] # Solo primera pestaña para visualización
                st.session_state.dict_datos = {p1: normalizar_df(xl.parse(p1), modo)}
            st.rerun()

        if st.session_state.dict_datos:
            periodos = list(st.session_state.dict_datos.keys())
            fecha_sel = st.select_slider("🕒 Periodo:", options=periodos) if len(periodos) > 1 else periodos[0]
            df_act = st.session_state.dict_datos[fecha_sel]
            
            st.markdown("---")
            st.subheader("📊 Filtros de Rango")
            stats = df_act.groupby('RANGO_ID')['VOL'].agg(['count', 'sum'])
            
            # Definición de etiquetas dinámicas para los filtros
            if "Polígonos" in modo:
                lbls = ["⚪ R0 (0)", "🟡 R1 (1-100)", "🟠 R2 (101-200)", "🔴 R3 (201-300)", "🏮 R4 (301-400)", "🍷 R5 (401+)"]
            else:
                lbls = ["⚪ R0 (0)", "🟡 R1 (1-15)", "🟠 R2 (16-20)", "🔴 R3 (21-30)", "🏮 R4 (31-40)", "🍷 R5 (41+)"]
            
            activos = []
            f1, f2 = st.columns(2)
            for i in range(6):
                c = f1 if i < 3 else f2
                n = int(stats.loc[i, 'count']) if i in stats.index else 0
                v = int(stats.loc[i, 'sum']) if i in stats.index else 0
                if c.checkbox(f"{lbls[i]} \n[{n} pts | Vol: {v}]", value=True, key=f"r_{i}"):
                    activos.append(i)
            
            st.markdown("---")
            ver_nombres = st.toggle("🏷️ Nombres Fijos", value=True)
            if "Polígonos" in modo:
                archivos = sorted([f for f in os.listdir('mapas') if f.endswith(('.json', '.geojson'))])
                archivo_sel = st.selectbox("Mapa Base", archivos)

    # --- 4. RENDERIZADO ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act[df_act['RANGO_ID'].isin(activos)].copy()
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if "Análisis" in modo:
                HeatMap([[f['LAT'], f['LON'], f['VOL']] for _, f in df_m.dropna(subset=['LAT', 'LON']).iterrows()], radius=25).add_to(m)
                # Tooltips para calor
                for _, f in df_m.dropna(subset=['LAT', 'LON']).iterrows():
                    info = f"<b>{f['PER']}</b><br>Zona: {f['NOM']}<br>Vol: {int(f['VOL'])}<br>Reparto: {f['PORC_ZONA']}%"
                    folium.CircleMarker([f['LAT'], f['LON']], radius=5, color='transparent', fill=False, tooltip=folium.Tooltip(info)).add_to(m)
            
            elif "Polígonos" in modo:
                gdf, col_geo = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    df_m['CP'] = df_m['CP'].astype(str).str.zfill(5)
                    merged = gdf.merge(df_m, left_on=col_geo, right_on='CP')
                    for _, f in merged.iterrows():
                        c = COLORS.get(f['RANGO_ID'], "#888")
                        info = f"<b>{f['PER']}</b><br>CP: {f['CP']}<br>Vol: {int(f['VOL'])}<br>Reparto: {f['PORC_ZONA']}%"
                        folium.GeoJson(f['geometry'], tooltip=folium.Tooltip(info),
                                       style_function=lambda x, col=c: {'fillColor':col, 'color':col, 'fillOpacity':0.4, 'weight':1.5}).add_to(m)
                        if ver_nombres:
                            folium.Marker([f['geometry'].centroid.y, f['geometry'].centroid.x], 
                                          icon=folium.features.DivIcon(html=f'<div style="font-size:7pt;text-align:center;width:80px;">{f["PER"]}</div>')).add_to(m)
            else:
                for _, f in df_m.dropna(subset=['LAT', 'LON']).iterrows():
                    c = COLORS.get(f['RANGO_ID'], "#888")
                    info = f"<b>{f['PER']}</b><br>Vol: {int(f['VOL'])}<br>Radio: {f['RAD']}<br>Reparto: {f['PORC_ZONA']}%"
                    folium.CircleMarker([f['LAT'], f['LON']], radius=f['RAD'], color=c, fill=True, fill_color=c, fill_opacity=0.7, tooltip=folium.Tooltip(info)).add_to(m)
                    if ver_nombres:
                        folium.Marker([f['LAT'], f['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:7pt;text-align:center;width:80px;">{f["PER"]}</div>', icon_anchor=(40,10))).add_to(m)

            if not df_m.empty: m.fit_bounds([[df_m['LAT'].min(), df_m['LON'].min()], [df_m['LAT'].max(), df_m['LON'].max()]])
            st_folium(m, width="100%", height=550)
            
            # --- INFORME EJECUTIVO ---
            st.markdown("---")
            st.markdown("### 📊 Informe Ejecutivo de Mancha de Calor")
            c1, c2, c3 = st.columns([1, 1.5, 1.5])
            
            u_total = df_m['VOL'].sum()
            c1.metric("Universo Total", f"{int(u_total):,}")
            
            top_p = df_m.groupby('PER')['VOL'].sum().sort_values(ascending=False).head(5)
            c2.write("**🔥 Impacto por Responsable (Universo):**")
            for p, v in top_p.items():
                c2.caption(f"{p}: {int(v):,} unidades ({(v/u_total*100):.1f}%)")
            
            enc = df_m[df_m.duplicated('NOM', keep=False)]
            c3.write(f"**🤝 Saturación en Zonas Encimadas:** {enc['NOM'].nunique()} áreas")
            z_sel = c3.selectbox("Analizar Reparto por Punto:", ["-"] + sorted(enc['NOM'].unique().tolist()))
            if z_sel != "-":
                det = enc[enc['NOM'] == z_sel][['PER', 'VOL', 'PORC_ZONA']].sort_values('VOL', ascending=False)
                st.table(det)

            st.download_button(f"💾 Descargar Reporte {fecha_sel}", data=m._repr_html_().encode('utf-8'), file_name=f"amzl_{fecha_sel}.html", mime="text/html")
