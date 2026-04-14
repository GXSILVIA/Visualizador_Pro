#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os, io, yaml, numpy as np, time
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium
from folium.plugins import HeatMap

# --- 1. CONFIGURACIÓN E INTELIGENCIA ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

def calcular_traslape_real(p1, otros_pts):
    if not otros_pts: return 0.0
    n = 2000 
    ang = np.random.uniform(0, 2*np.pi, n); rad = np.sqrt(np.random.uniform(0, 1, n)) * p1['RAD']
    m_grado = 111139
    p_lat = p1['LAT'] + ((rad * np.sin(ang)) / m_grado)
    p_lon = p1['LON'] + ((rad * np.cos(ang)) / (m_grado * np.cos(np.radians(p1['LAT']))))
    cubiertos = np.zeros(n, dtype=bool)
    for p2 in otros_pts:
        d2 = ((p_lat - p2['LAT'])**2 + ((p_lon - p2['LON']) * np.cos(np.radians(p1['LAT'])))**2) * (m_grado**2)
        cubiertos |= (d2 <= p2['RAD']**2)
        if cubiertos.all(): return 100.0
    return (np.sum(cubiertos) / n) * 100

def obtener_rango_id(v, modo_p):
    lim = [100, 200, 300, 400] if modo_p else [15, 20, 30, 40]
    return next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0

@st.cache_data
def cargar_geo(archivo):
    ruta = f"mapas/{archivo}"
    if os.path.exists(ruta):
        gdf = gpd.read_file(ruta).to_crs("EPSG:4326")
        gdf['geometry'] = gdf['geometry'].simplify(0.001)
        col = next((c for c in ['d_cp','CP','CODIGOPOSTAL','cp','id'] if c in gdf.columns), gdf.columns)
        return gdf, col
    return None, None

def normalizar(df, modo):
    df.columns = df.columns.str.strip().str.upper()
    mapa = {'LAT':['LATITUD','LAT'],'LON':['LONGITUD','LON'],'VOL':['VOLUMEN','VOL'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA','CLIENTE'],'FEC':['FECHA','DATE']}
    df = df.rename(columns={c: k for k, v in mapa.items() for c in df.columns if c in v})
    for c in ['LAT','LON','VOL','RAD']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    if 'RAD' not in df.columns or (df['RAD'] == 0).all(): df['RAD'] = 750
    if 'FEC' in df.columns: df['FEC'] = pd.to_datetime(df['FEC'], errors='coerce')
    if 'CP' in df.columns: df['CP'] = df['CP'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
    if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'ZONA')
    return df

# --- 2. SEGURIDAD ---
try:
    with open('config.yaml') as f: config = yaml.load(f, SafeLoader)
    auth = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, status, user = auth.login(location='main')
except: st.error("Error en config.yaml"); st.stop()

if status:
    if 'dict_datos' not in st.session_state: st.session_state.dict_datos = {}
    col_m, col_p = st.columns([3, 1.3])
    
    with col_p:
        st.title("🛡️ Panel AMZL")
        auth.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa", ["Coordenadas", "Polígonos CP", "Mapa de Calor"])
        gdf, col_cp_g, bounds = None, None, None
        
        if modo == "Polígonos CP":
            archs = sorted([f for f in os.listdir('mapas') if f.endswith('.geojson')])
            edo_sel = st.selectbox("📍 Estado:", [f.replace('.geojson','').replace('_',' ') for f in archs])
            if edo_sel:
                archivo_real = archs[[f.replace('.geojson','').replace('_',' ') for f in archs].index(edo_sel)]
                gdf, col_cp_g = cargar_geo(archivo_real)
                if gdf is not None: 
                    b = gdf.total_bounds; bounds = [[b[1], b[0]], [b[3], b[2]]]

        st.subheader("📥 Plantillas")
        cols_base = {"Coordenadas": ["ZONA", "LATITUD", "LONGITUD", "RADIO", "VOLUMEN"],
                     "Polígonos CP": ["ZONA", "CP", "VOLUMEN"],
                     "Mapa de Calor": ["CLIENTE", "LATITUD", "LONGITUD", "FECHA"]}
        buf_p = io.BytesIO()
        pd.DataFrame(columns=cols_base[modo]).to_excel(buf_p, index=False)
        st.download_button(f"Base {modo}", data=buf_p.getvalue(), file_name=f"base_{modo.lower().replace(' ','_')}.xlsx", use_container_width=True)

        xl_file = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if xl_file and st.button("🔄 Procesar"):
            st.session_state.dict_datos = {p: normalizar(pd.ExcelFile(xl_file).parse(p), modo) for p in pd.ExcelFile(xl_file).sheet_names}
            st.rerun()

        if st.session_state.dict_datos:
            pestanas = list(st.session_state.dict_datos.keys())
            sel = st.select_slider("🕒 Pestaña:", options=pestanas) if len(pestanas) > 1 else pestanas[0]
            df_act = st.session_state.dict_datos[sel].copy()
            
            if modo == "Mapa de Calor":
                st.write("---")
                st.info("💡 Capacidad fija: **35 entregas/día**")
                if 'FEC' in df_act.columns:
                    dias = sorted(df_act['FEC'].dt.day_name().unique())
                    dia_sel = st.multiselect("Filtrar días de la semana:", dias, default=dias)
                    df_act = df_act[df_act['FEC'].dt.day_name().isin(dia_sel)]
            else:
                st.write("---")
                df_act['R_ID'] = df_act['VOL'].apply(lambda x: obtener_rango_id(x, modo == "Polígonos CP"))
                labs = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if modo == "Polígonos CP" else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
                cols = st.columns(3)
                acts = [i for i, l in enumerate(labs) if cols[i%3].checkbox(l, value=True, key=f"r{i}{sel}")]
                ver_n = st.toggle("🏷️ Ver Nombres Fijos", value=True)
                m_ana = st.toggle("🔍 Tabla de Análisis", value=False)

    with col_m:
        if st.session_state.dict_datos:
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            rep = []

            if modo == "Mapa de Calor":
                data_h = df_act[['LAT', 'LON']].dropna()
                data_h = data_h[(data_h['LAT'] != 0)]
                if not data_h.empty:
                    HeatMap(data_h.values.tolist(), radius=15, blur=15, min_opacity=0.4).add_to(m)
                    m.fit_bounds([[data_h.LAT.min(), data_h.LON.min()], [data_h.LAT.max(), data_h.LON.max()]])
            else:
                df_v = df_act[df_act['R_ID'].isin(acts)].copy()
                clrs = {0:"#FFF", 1:"#FF0", 2:"#FFA500", 3:"#F00", 4:"#FF4500", 5:"#800000"}

                if modo == "Polígonos CP" and gdf is not None:
                    if bounds: m.fit_bounds(bounds)
                    v_dict, n_dict = df_v.set_index('CP')['VOL'].to_dict(), df_v.set_index('CP')['NOM'].to_dict()
                    for _, r in gdf.iterrows():
                        cp = str(r[col_cp_g]).zfill(5)
                        if cp in v_dict:
                            folium.GeoJson(r['geometry'], style_function=lambda x, v=v_dict[cp]: {'fillColor':clrs[obtener_rango_id(v,True)], 'color':'#000', 'weight':1, 'fillOpacity':0.4},
                                           tooltip=f"<b>{n_dict[cp]}</b><br>Vol: {int(v_dict[cp])}").add_to(m)
                            if ver_n:
                                c = r['geometry'].centroid
                                folium.Marker([c.y, c.x], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-align:center; width:80px;">{n_dict[cp]}</div>')).add_to(m)

                if 'LAT' in df_v.columns and 'LON' in df_v.columns:
                    df_c = df_v[(df_v['LAT'] != 0)]
                    if not df_c.empty:
                        if modo != "Polígonos CP": m.fit_bounds([[df_c.LAT.min(), df_c.LON.min()], [df_c.LAT.max(), df_c.LON.max()]])
                        pts = df_c.to_dict('records')
                        for i, p1 in enumerate(pts):
                            otros = [p for j, p in enumerate(pts) if i != j]
                            detalles = [f"{p2['NOM']} ({round((area_interseccion(p1['RAD'],p2['RAD'],np.sqrt((p1['LAT']-p2['LAT'])**2 + ((p1['LON']-p2['LON'])*np.cos(np.radians(p1['LAT'])))**2)*111139)/(np.pi*p1['RAD']**2))*100,1)}%)" 
                                        for p2 in otros if np.sqrt((p1['LAT']-p2['LAT'])**2 + ((p1['LON']-p2['LON'])*np.cos(np.radians(p1['LAT'])))**2)*111139 < (p1['RAD']+p2['RAD'])]
                            tr = calcular_traslape_real(p1, otros)
                            folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=clrs[p1['R_ID']], fill=True, fill_opacity=0.35, tooltip=f"<b>{p1['NOM']}</b><br>Vol: {int(p1['VOL'])}").add_to(m)
                            if ver_n: folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:9pt; font-weight:bold; color:#000; text-shadow: 0 0 3px #FFF; width:150px;">{p1["NOM"]}</div>')).add_to(m)
                            rep.append({"Estatus": "🔴" if tr > 50 else "🟡" if tr > 15 else "🟢", "Zona": p1['NOM'], "% Traslape Real": f"{round(tr, 1)}%", "Traslapado con": ", ".join(detalles) if detalles else "No traslapado"})

            st_folium(m, width="100%", height=550, key="mapa_fijo")
            
            st.write("---")
            if modo == "Mapa de Calor":
                c1, c2, c3 = st.columns(3)
                total_p = len(df_act)
                # Cálculo basado en 35 entregas
                repas = int(np.ceil(total_p / 35))
                c1.metric("📊 Demanda Total General", f"{total_p:,}")
                c2.metric("🚚 Repartidores Sugeridos (35/día)", f"{repas}")
                c3.metric("📅 Días Analizados", f"{len(df_act['FEC'].dt.date.unique()) if 'FEC' in df_act.columns else 1}")
                if 'FEC' in df_act.columns: st.bar_chart(df_act.groupby(df_act['FEC'].dt.date).size())
            else:
                c1, c2 = st.columns(2)
                with c1: st.download_button("🗺️ Mapa HTML", data=io.BytesIO(m._repr_html_().encode()).getvalue(), file_name="mapa.html", use_container_width=True)
                with c2:
                    if rep:
                        buf = io.BytesIO(); pd.DataFrame(rep).to_excel(buf, index=False)
                        st.download_button("📊 Informe", data=buf.getvalue(), file_name="analisis.xlsx", use_container_width=True)
                if m_ana and rep: st.table(pd.DataFrame(rep))
