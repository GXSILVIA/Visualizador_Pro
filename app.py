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

def haversine_np(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi, dlam = np.radians(lat2 - lat1), np.radians(lon2 - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlam/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

def calcular_traslape_real(p1, otros_pts):
    if not otros_pts: return 0.0
    n = 1500
    ang = np.random.uniform(0, 2*np.pi, n); rad = np.sqrt(np.random.uniform(0, 1, n)) * p1['RAD']
    m_grado = 111139
    p_lat = p1['LAT'] + ((rad * np.sin(ang)) / m_grado)
    p_lon = p1['LON'] + ((rad * np.cos(ang)) / (m_grado * np.cos(np.radians(p1['LAT']))))
    cubiertos = np.zeros(n, dtype=bool)
    for p2 in otros_pts:
        d2 = ((p_lat - p2['LAT'])**2 + ((p_lon - p2['LON']) * np.cos(np.radians(p1['LAT'])))**2) * (m_grado**2)
        cubiertos |= (d2 <= p2['RAD']**2)
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
        col_cp = next((c for c in ['d_cp','CP','CODIGOPOSTAL','cp'] if c in gdf.columns), gdf.columns[0])
        col_edo = next((c for c in ['NOM_ENT','ESTADO','ENTIDAD'] if c in gdf.columns), None)
        return gdf, col_cp, col_edo
    return None, None, None

def normalizar(df, modo):
    df.columns = df.columns.str.strip().str.upper()
    mapa = {'LAT':['LATITUD','LAT'],'LON':['LONGITUD','LON'],'VOL':['VOLUMEN','VOL'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA','CLIENTE']}
    df = df.rename(columns={c: k for k, v in mapa.items() for c in df.columns if c in v})
    for c in ['LAT','LON','VOL','RAD']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    if 'RAD' not in df.columns or (df['RAD'] == 0).all(): df['RAD'] = 750
    if 'CP' in df.columns: df['CP'] = df['CP'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
    if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'ZONA')
    return df

# --- 2. SEGURIDAD ---
with open('config.yaml') as f: config = yaml.load(f, SafeLoader)
auth = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
name, status, user = auth.login(location='main')

if status:
    if 'dict_datos' not in st.session_state: st.session_state.dict_datos = {}
    col_m, col_p = st.columns([3, 1.3])
    
    with col_p:
        st.title("🛡️ Panel AMZL")
        auth.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP", "Mapa de Calor (Análisis Pro)"])
        
        st.subheader("📥 Plantillas")
        if modo == "Mapa de Calor (Análisis Pro)":
            c1, c2 = st.columns(2); b1, b2 = io.BytesIO(), io.BytesIO()
            pd.DataFrame(columns=["NOMBRE","LATITUD","LONGITUD","RADIO"]).to_excel(b1, index=False)
            pd.DataFrame(columns=["NOMBRE","LATITUD","LONGITUD","VOLUMEN"]).to_excel(b2, index=False)
            c1.download_button("📥 Hubs", data=b1.getvalue(), file_name="zonas_hub.xlsx", use_container_width=True)
            c2.download_button("📥 Compras", data=b2.getvalue(), file_name="compras_reales.xlsx", use_container_width=True)
        else:
            cols_b = ["ZONA", "LATITUD", "LONGITUD", "RADIO", "VOLUMEN"] if modo == "Coordenadas" else ["ZONA", "CP", "VOLUMEN"]
            b_gen = io.BytesIO(); pd.DataFrame(columns=cols_b).to_excel(b_gen, index=False)
            st.download_button(f"📥 Base {modo}", data=b_gen.getvalue(), file_name=f"plantilla_{modo.lower()}.xlsx", use_container_width=True)

        if modo == "Mapa de Calor (Análisis Pro)":
            f_h = st.file_uploader("Zonas Hub", type="xlsx")
            f_c = st.file_uploader("Compras Reales", type="xlsx")
            if f_h and f_c and st.button("🔥 Ejecutar Cruce Pro"):
                dh, dc = pd.read_excel(f_h), pd.read_excel(f_c)
                dist = haversine_np(dc['LATITUD'].values[:, None], dc['LONGITUD'].values[:, None], dh['LATITUD'].values, dh['LONGITUD'].values)
                cob = dist <= dh['RADIO'].values
                dc['TRASLAPES'] = np.sum(cob, axis=1)
                dh['SATURACION'] = np.sum(cob, axis=0)
                st.session_state.pro_hubs, st.session_state.pro_compras = dh, dc
        else:
            xl = st.file_uploader("📂 Datos Masivos", type=["xlsx"])
            if xl and st.button("🔄 Procesar"):
                st.session_state.dict_datos = {p: normalizar(pd.ExcelFile(xl).parse(p), modo) for p in pd.ExcelFile(xl).sheet_names}

        if st.session_state.dict_datos and modo != "Mapa de Calor (Análisis Pro)":
            pest = list(st.session_state.dict_datos.keys())
            sel_p = st.select_slider("🕒 Pestaña:", options=pest) if len(pest)>1 else pest[0]
            df_act = st.session_state.dict_datos[sel_p].copy()
            
            df_act['R_ID'] = df_act['VOL'].apply(lambda x: obtener_rango_id(x, modo == "Polígonos CP"))
            labs = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if modo == "Polígonos CP" else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
            
            acts = []
            cols_check = st.columns(2)
            for i, l in enumerate(labs):
                if cols_check[i%2].checkbox(l, value=True, key=f"c{i}"): acts.append(i)
            
            ver_n, m_ana = st.toggle("🏷️ Ver Nombres", value=True), st.toggle("🔍 Análisis", value=False)

            if modo == "Polígonos CP":
                archs = sorted([f for f in os.listdir('mapas') if f.endswith('.geojson')])
                geo_sel = st.selectbox("🗺️ GeoJSON / Estado", archs)
                gdf, col_cp_g, col_edo = cargar_geo(geo_sel)

    # --- 3. MAPA ---
    with col_m:
        m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
        clrs = {0:"#FFF", 1:"#FFFF00", 2:"#FFA500", 3:"#FF0000", 4:"#FF4500", 5:"#800000"}
        rep = []

        if modo == "Mapa de Calor (Análisis Pro)" and 'pro_compras' in st.session_state:
            dc, dh = st.session_state.pro_compras, st.session_state.pro_hubs
            HeatMap(dc[['LATITUD','LONGITUD','VOLUMEN']].values.tolist(), radius=15, blur=10).add_to(m)
            for _, r in dh.iterrows():
                folium.Circle([r.LATITUD, r.LONGITUD], radius=r.RADIO, color='blue', fill=True, fill_opacity=0.1).add_to(m)
            for _, r in dc[dc['TRASLAPES'] == 0].iterrows():
                folium.CircleMarker([r.LATITUD, r.LONGITUD], radius=2, color='black', tooltip="ZONA MUERTA").add_to(m)
            m.fit_bounds([[dc.LATITUD.min(), dc.LONGITUD.min()], [dc.LATITUD.max(), dc.LONGITUD.max()]])
        
        elif st.session_state.dict_datos:
            df_v = df_act[df_act['R_ID'].isin(acts)]
            
            if modo == "Polígonos CP" and gdf is not None:
                b = gdf.total_bounds
                m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
                vd, nd = df_v.set_index('CP')['VOL'].to_dict(), df_v.set_index('CP')['NOM'].to_dict()
                for _, r in gdf.iterrows():
                    cp = str(r[col_cp_g]).zfill(5)
                    if cp in vd:
                        folium.GeoJson(r['geometry'], style_function=lambda x, v=vd[cp]: {'fillColor':clrs[obtener_rango_id(v,True)], 'color':'#000', 'weight':1, 'fillOpacity':0.4}, tooltip=f"CP: {cp} | Vol: {int(vd[cp])}").add_to(m)
                        if ver_n:
                            c = r['geometry'].centroid
                            folium.Marker([c.y, c.x], icon=folium.features.DivIcon(html=f'<div style="font-size:7pt; font-weight:bold; color:black;">{nd[cp]}</div>')).add_to(m)

            elif modo == "Coordenadas":
                pts = df_v[df_v['LAT'] != 0].to_dict('records')
                if pts:
                    m.fit_bounds([[df_v.LAT.min(), df_v.LON.min()], [df_v.LAT.max(), df_v.LON.max()]])
                    for i, p1 in enumerate(pts):
                        otros = [p for j, p in enumerate(pts) if i != j]
                        tr = calcular_traslape_real(p1, otros)
                        folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=clrs[p1['R_ID']], fill=True, fill_opacity=0.3, tooltip=f"{p1['NOM']}").add_to(m)
                        if ver_n: folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; text-shadow: 0 0 3px white;">{p1["NOM"]}</div>')).add_to(m)
                        rep.append({"Zona": p1['NOM'], "% Traslape": f"{round(tr,1)}%", "Estatus": "🔴" if tr > 50 else "🟡" if tr > 15 else "🟢"})

        st_folium(m, width="100%", height=600, key=f"mapa_{modo}")

        # --- RESULTADOS ---
        if modo == "Mapa de Calor (Análisis Pro)" and 'pro_compras' in st.session_state:
            dc, dh = st.session_state.pro_compras, st.session_state.pro_hubs
            c1, c2, c3 = st.columns(3)
            vt = dc['VOLUMEN'].sum()
            c1.metric("💀 % Vol. Zonas Muertas", f"{(dc[dc['TRASLAPES']==0]['VOLUMEN'].sum()/vt)*100:.1f}%")
            c2.metric("🏮 % Alta Densidad", f"{(dc[dc['TRASLAPES']>2]['VOLUMEN'].sum()/vt)*100:.1f}%")
            c3.metric("🏆 Hub Saturado", dh.loc[dh['SATURACION'].idxmax()]['NOMBRE'])
            
            cd1, cd2 = st.columns(2)
            buf = io.BytesIO(); dc.to_excel(buf, index=False)
            cd1.download_button("📊 Descargar Excel Resultados", data=buf.getvalue(), file_name="analisis_pro.xlsx", use_container_width=True)
            cd2.download_button("🗺️ Guardar Mapa HTML", data=m._repr_html_().encode(), file_name="mapa_pro.html", use_container_width=True)

        elif rep and m_ana:
            st.table(pd.DataFrame(rep))
