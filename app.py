#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap, Geocoder
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
if 'zona_seleccionada' not in st.session_state: st.session_state.zona_seleccionada = None

# Autenticación
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, auth_status, username = authenticator.login(location='main')
except: st.error("Error de configuración."); st.stop()

if auth_status:
    # --- 2. LÓGICA DE PROCESAMIENTO ---
    def normalizar_df(df, modo_ref):
        df.columns = df.columns.str.strip().str.upper()
        cols = df.columns
        mapa = {'LAT':['LAT','LATITUD'],'LON':['LON','LONGITUD'],'VOL':['VOL','VOLUMEN'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA'],'PER':['PERSONA','RESPONSABLE']}
        rename_dict = {}
        for destino, sinonimos in mapa.items():
            encontrado = next((c for c in cols if c in sinonimos), None)
            if encontrado: rename_dict[encontrado] = destino
        df = df.rename(columns=rename_dict)
        
        df['VOL'] = pd.to_numeric(df.get('VOL',0), errors='coerce').fillna(0)
        df['RAD'] = pd.to_numeric(df.get('RAD',750), errors='coerce').fillna(750)
        if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'Punto')
        if 'PER' not in df.columns: df['PER'] = "N/A"
        
        # Rangos R0-R5 diferenciados
        def asignar_rango(v):
            if v <= 0: return 0
            lim = [100, 200, 300, 400] if "Polígonos" in modo_ref else [15, 20, 30, 40]
            for i, l in enumerate(lim, 1):
                if v <= l: return i
            return 5
        df['RANGO_ID'] = df['VOL'].apply(asignar_rango)

        # Análisis de Conjunto
        df['COORD_KEY'] = df['LAT'].round(4).astype(str) + "," + df['LON'].round(4).astype(str)
        total_u = df['VOL'].sum()
        df['VOL_CONJUNTO'] = df.groupby('COORD_KEY')['VOL'].transform('sum')
        df['PORC_DEL_TOTAL'] = (df['VOL_CONJUNTO'] / (total_u if total_u > 0 else 1) * 100).round(1)
        df['PORC_INTERNO'] = (df['VOL'] / df['VOL_CONJUNTO'].replace(0,1) * 100).round(1)
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
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP", "Mapa de Calor (Análisis)"])
        
        archivo_excel = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            if "Calor" in modo or "Análisis" in modo:
                st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            else:
                p1 = xl.sheet_names[0]
                st.session_state.dict_datos = {p1: normalizar_df(xl.parse(p1), modo)}
            st.rerun()

        if st.session_state.dict_datos:
            periodos = list(st.session_state.dict_datos.keys())
            fecha_sel = st.select_slider("🕒 Historial:", options=periodos) if len(periodos) > 1 else periodos[0]
            df_act = st.session_state.dict_datos[fecha_sel]
            
            st.markdown("---")
            st.subheader("📊 Filtros de Rango")
            stats = df_act.groupby('RANGO_ID')['VOL'].agg(['count', 'sum'])
            lbls = ["⚪ R0", "🟡 R1", "🟠 R2", "🔴 R3", "🏮 R4", "🍷 R5"]
            activos = []
            f1, f2 = st.columns(2)
            for i in range(6):
                n, v = (int(stats.loc[i, 'count']), int(stats.loc[i, 'sum'])) if i in stats.index else (0,0)
                if (f1 if i < 3 else f2).checkbox(f"{lbls[i]} ({n} pts)", value=True, key=f"r_{i}_{fecha_sel}"): activos.append(i)
            
            ver_nombres = st.toggle("🏷️ Ver Nombres Fijos", value=True)
            archivo_sel = st.selectbox("Mapa Base (GeoJSON)", sorted([f for f in os.listdir('mapas') if f.endswith(('.json', '.geojson'))])) if "Polígonos" in modo else None

    # --- 4. RENDERIZADO DEL MAPA ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act[df_act['RANGO_ID'].isin(activos)].copy()
            m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles="CartoDB Voyager")
            COLORS = {0:"#FFFFFF", 1:"#FFFF00", 2:"#FF9900", 3:"#FF4444", 4:"#FF0000", 5:"#660000"}

            if "Calor" in modo:
                HeatMap([[f['LAT'], f['LON'], f['VOL']] for _, f in df_m.dropna(subset=['LAT', 'LON']).iterrows()], radius=50, blur=30).add_to(m)
            
            elif "Polígonos" in modo and archivo_sel:
                gdf, col_geo = cargar_capa_estado(archivo_sel)
                if gdf is not None:
                    df_m['CP'] = df_m.get('CP', '0').astype(str).str.zfill(5)
                    merged = gdf.merge(df_m, left_on=col_geo, right_on='CP')
                    for _, f in merged.iterrows():
                        c = COLORS.get(f['RANGO_ID'], "#888")
                        tooltip = f"<b>{f['PER']}</b><br>Vol: {int(f['VOL'])}<br>Reparto: {f['PORC_INTERNO']}%"
                        folium.GeoJson(f['geometry'], tooltip=tooltip, style_function=lambda x, col=c: {'fillColor':col, 'color':col, 'fillOpacity':0.4, 'weight':1.5}).add_to(m)
                        if ver_nombres:
                            folium.Marker([f['geometry'].centroid.y, f['geometry'].centroid.x], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; color:#000; font-weight:bold; text-align:center; width:100px; text-shadow: 2px 2px 3px #FFF;">{f["PER"]}</div>')).add_to(m)

            # Capa de Coordenadas (Círculos)
            if "Polígonos" not in modo:
                for _, f in df_m.dropna(subset=['LAT', 'LON']).iterrows():
                    c = COLORS.get(f['RANGO_ID'], "#888")
                    info = f"<b>{f['NOM']}</b><br>Vol. Conjunto: {int(f['VOL_CONJUNTO'])}<br>Clic para Análisis"
                    folium.Circle(location=[f['LAT'], f['LON']], radius=f['RAD'], color=c, fill=True, fill_color=c, fill_opacity=0.3, weight=1.5, tooltip=info, popup=f['NOM']).add_to(m)
                    if ver_nombres:
                        style = 'font-size:8pt; color:#000; font-weight:bold; text-align:center; width:100px; text-shadow: 2px 2px 3px #FFF;'
                        folium.Marker([f['LAT'], f['LON']], icon=folium.features.DivIcon(html=f'<div style="{style}">{f["PER"]}</div>', icon_anchor=(50, 0))).add_to(m)

            if not df_m.empty: m.fit_bounds([[df_m['LAT'].min(), df_m['LON'].min()], [df_m['LAT'].max(), df_m['LON'].max()]])
            
            # Captura de interacción
            map_output = st_folium(m, width="100%", height=550, key=f"mapa_{fecha_sel}_{modo}")
            
            if map_output['last_object_clicked']:
                lat_c, lon_c = map_output['last_object_clicked']['lat'], map_output['last_object_clicked']['lng']
                df_m['dist'] = ((df_m['LAT'] - lat_c)**2 + (df_m['LON'] - lon_c)**2)**0.5
                st.session_state.zona_seleccionada = df_m.nsmallest(1, 'dist')['NOM'].iloc

            # --- 5. INFORME EJECUTIVO ---
            st.markdown("---")
            st.markdown(f"### 📋 Informe Ejecutivo - {fecha_sel}")
            c1, c2, c3 = st.columns([1, 1.5, 1.5])
            u_total = df_m['VOL'].sum()
            c1.metric("Universo Total", f"{int(u_total):,}")
            
            if st.session_state.zona_seleccionada:
                zona = st.session_state.zona_seleccionada
                det = df_m[df_m['NOM'] == zona]
                c2.success(f"📍 Zona: **{zona}**")
                c2.write(f"Volumen Conjunto: **{int(det['VOL_CONJUNTO'].iloc)}** ({det['PORC_DEL_TOTAL'].iloc}% del total)")
                c3.write("**Reparto Interno:**")
                st.table(det[['PER', 'VOL', 'PORC_INTERNO']].rename(columns={'PORC_INTERNO': '% Reparto'}))
                if st.button("Limpiar Selección"): st.session_state.zona_seleccionada = None; st.rerun()
            else:
                c2.info("👆 Haz clic en un conjunto en el mapa para ver su análisis.")
                top_p = df_act.groupby('PER')['VOL'].sum().sort_values(ascending=False).head(3)
                c3.write("**Top 3 Responsables Globales:**")
                for p, v in top_p.items(): c3.caption(f"{p}: {int(v):,} ({(v/u_total*100 if u_total>0 else 0):.1f}%)")

            st.download_button("💾 Descargar Mapa HTML", data=m._repr_html_().encode('utf-8'), file_name=f"amzl_{fecha_sel}.html", mime="text/html")

elif auth_status is False: st.error('Credenciales incorrectas')
