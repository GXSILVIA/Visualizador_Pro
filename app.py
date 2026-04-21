#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa - Sistema Pro Integral Unificado

import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os, io, yaml, numpy as np
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
import streamlit.components.v1 as components
import xlsxwriter 

# --- 1. CONFIGURACIÓN Y CÁLCULOS ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

@st.cache_data
def area_interseccion(r1, r2, d):
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return np.pi * min(r1, r2)**2
    p1 = r1**2 * np.arccos(np.clip((d**2 + r1**2 - r2**2) / (2 * d * r1), -1, 1))
    p2 = r2**2 * np.arccos(np.clip((d**2 + r2**2 - r1**2) / (2 * d * r2), -1, 1))
    p3 = 0.5 * np.sqrt(max(0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return p1 + p2 - p3

@st.cache_data
def calcular_traslape_real(p1, otros_pts):
    if not otros_pts: return 0.0
    n = 5000 
    ang = np.random.uniform(0, 2*np.pi, n)
    rad = np.sqrt(np.random.uniform(0, 1, n)) * p1['RAD']
    m_grado = 111139
    cos_lat = np.cos(np.radians(p1['LAT']))
    p_lat = p1['LAT'] + ((rad * np.sin(ang)) / m_grado)
    p_lon = p1['LON'] + ((rad * np.cos(ang)) / (m_grado * cos_lat))
    cubiertos = np.zeros(n, dtype=bool)
    for p2 in otros_pts:
        d2 = ((p_lat - p2['LAT'])**2 + ((p_lon - p2['LON']) * cos_lat)**2) * (m_grado**2)
        cubiertos |= (d2 <= p2['RAD']**2)
        if np.all(cubiertos): break 
    return (np.sum(cubiertos) / n) * 100

def obtener_rango_id(v, modo_p):
    lim = [100, 200, 300, 400] if modo_p else [15, 20, 30, 40]
    return next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0

def normalizar(df, modo):
    df.columns = df.columns.str.strip().str.upper()
    mapa = {'LAT':['LATITUD','LAT'],'LON':['LONGITUD','LON'],'VOL':['VOLUMEN','VOL'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA']}
    df = df.rename(columns={c: k for k, v in mapa.items() for c in df.columns if c in v})
    for c in ['LAT','LON','VOL','RAD']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    if 'RAD' not in df.columns or (df['RAD'] == 0).all(): df['RAD'] = 750
    if 'CP' in df.columns: df['CP'] = df['CP'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
    if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'ZONA')
    df['R_ID'] = df['VOL'].apply(lambda x: obtener_rango_id(x, "Polígonos" in modo))
    return df

# --- 2. SEGURIDAD Y ESTADOS ---
with open('config.yaml') as f: config = yaml.load(f, SafeLoader)
auth = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
auth.login(location='main')

if st.session_state.get("authentication_status"):
    if 'df_datos' not in st.session_state: st.session_state.df_datos = None
    if 'dict_hojas' not in st.session_state: st.session_state.dict_hojas = None
    if 'idx_hoja' not in st.session_state: st.session_state.idx_hoja = 0

    col_m, col_p = st.columns([3, 1.3])
   
    with col_p:
        st.title("🛡️ Panel Pro")
        auth.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa", ["Coordenadas", "Polígonos CP", "Crecimiento"])
        
        gdf, col_cp_g, bounds_geo = None, None, None
        if modo == "Polígonos CP":
            archs = sorted([f for f in os.listdir('mapas') if f.endswith('.geojson')]) if os.path.exists('mapas') else []
            if archs:
                edo_sel = st.selectbox("📍 Estado:", [f.replace('.geojson','').replace('_',' ') for f in archs])
                gdf = gpd.read_file(f"mapas/{archs[[f.replace('.geojson','').replace('_',' ') for f in archs].index(edo_sel)]}").to_crs("EPSG:4326")
                col_cp_g = next((c for c in ['d_cp','CP','CODIGOPOSTAL'] if c in gdf.columns), gdf.columns[0])
                b = gdf.total_bounds
                bounds_geo = [[b[1], b[0]], [b[3], b[2]]]

        xl_file = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if xl_file:
            if modo == "Crecimiento" and st.button("🚀 Procesar Multi-Pestaña"):
                xl = pd.ExcelFile(xl_file)
                st.session_state.dict_hojas = {s: normalizar(xl.parse(s), modo) for s in xl.sheet_names}
                st.session_state.idx_hoja = 0
                st.rerun()
            elif modo != "Crecimiento" and st.button("🔄 Procesar"):
                st.session_state.df_datos = normalizar(pd.read_excel(xl_file), modo)
                st.rerun()

        if modo == "Crecimiento" and st.session_state.dict_hojas:
            nombres_h = list(st.session_state.dict_hojas.keys())
            st.info(f"Pestaña Actual: **{nombres_h[st.session_state.idx_hoja]}**")
            c1, c2 = st.columns(2)
            if c1.button("⬅️ Anterior") and st.session_state.idx_hoja > 0:
                st.session_state.idx_hoja -= 1
                st.rerun()
            if c2.button("Siguiente ➡️") and st.session_state.idx_hoja < len(nombres_h)-1:
                st.session_state.idx_hoja += 1
                st.rerun()

        st.write("---")
        labs = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
        cols_f = st.columns(3); acts = [i for i, l in enumerate(labs) if cols_f[i%3].checkbox(l, value=True, key=f"r{i}_{modo}")]
        ver_n = st.toggle("🏷️ Ver Nombres Fijos", value=True)
        m_ana = st.toggle("🔍 Tabla de Análisis", value=False)
        if m_ana:
            f_estatus = st.multiselect("ST:", ["🟢 Sano", "🟡 Medio", "🟠 Bajo", "🔴 Crítico", "⚪ Fuera de Rango"], default=["🟢 Sano", "🟡 Medio", "🟠 Bajo", "🔴 Crítico"])

    with col_m:
        hay_datos = (modo == "Crecimiento" and st.session_state.dict_hojas) or (modo != "Crecimiento" and st.session_state.df_datos is not None)
        if not hay_datos:
            st.info("👋 Bienvenida. Por favor, carga tu archivo Excel y presiona procesar.")
        else:
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            clrs = {0:"#FFF", 1:"#FF0", 2:"#FFA500", 3:"#F00", 4:"#FF4500", 5:"#800000"}
            rep = []

            if modo == "Crecimiento" and st.session_state.dict_hojas:
                nh = list(st.session_state.dict_hojas.keys())
                for idx, nom in enumerate(nh):
                    fg = folium.FeatureGroup(name=nom, show=(idx == st.session_state.idx_hoja))
                    df_h = st.session_state.dict_hojas[nom]
                    df_h_v = df_h[df_h['R_ID'].isin(acts)]
                    pts = df_h_v.to_dict('records')
                    for i, p1 in enumerate(pts):
                        otros = [p for j, p in enumerate(pts) if i != j]
                        tr = round(calcular_traslape_real(p1, otros), 1)
                        folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=clrs[p1['R_ID']], fill=True, fill_opacity=0.3, tooltip=f"{p1['NOM']}: {tr}%").add_to(fg)
                        if ver_n: folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-shadow: 0 0 1px #FFF; width:100px;">{p1["NOM"]}</div>')).add_to(fg)
                        if idx == st.session_state.idx_hoja:
                            salud = "🟢 Sano" if 30 <= p1['VOL'] <= 50 else "🟡 Medio" if 21 <= p1['VOL'] <= 29 else "🟠 Bajo" if 15 <= p1['VOL'] <= 20 else "🔴 Crítico" if p1['VOL'] >= 51 else "⚪ Fuera de Rango"
                            rep.append({"ST": salud, "Zona": p1['NOM'], "% Traslape Real": f"{tr}%"})
                    fg.add_to(m)
                folium.LayerControl(collapsed=False).add_to(m)
                df_visual = st.session_state.dict_hojas[nh[st.session_state.idx_hoja]]
                if not df_visual.empty: m.fit_bounds([[df_visual['LAT'].min(), df_visual['LON'].min()], [df_visual['LAT'].max(), df_visual['LON'].max()]])

            elif st.session_state.df_datos is not None:
                df_visual = st.session_state.df_datos[st.session_state.df_datos['R_ID'].isin(acts)]
                if modo == "Polígonos CP" and gdf is not None:
                    m.fit_bounds(bounds_geo)
                    df_v_cp = df_visual.set_index('CP')
                    for _, r in gdf.iterrows():
                        cp = str(r[col_cp_g]).zfill(5)
                        if cp in df_v_cp.index:
                            vol, nom = df_v_cp.loc[cp, 'VOL'], df_v_cp.loc[cp, 'NOM']
                            folium.GeoJson(r['geometry'], style_function=lambda x, v=vol: {'fillColor':clrs[obtener_rango_id(v,True)], 'color':'#000', 'weight':1, 'fillOpacity':0.4}).add_to(m)
                            if ver_n:
                                c = r['geometry'].centroid
                                folium.Marker([c.y, c.x], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-align:center; width:80px;">{nom}</div>')).add_to(m)
                elif 'LAT' in df_visual.columns:
                    pts = df_visual.to_dict('records')
                    for i, p1 in enumerate(pts):
                        otros = [p for j, p in enumerate(pts) if i != j]
                        dist_calc = [np.sqrt((p1['LAT']-p2['LAT'])**2 + ((p1['LON']-p2['LON'])*np.cos(np.radians(p1['LAT'])))**2)*111139 for p2 in otros]
                        ints = [{"nom": otros[j]['NOM'], "porc": round((area_interseccion(p1['RAD'], otros[j]['RAD'], dist_calc[j]) / (np.pi * p1['RAD']**2))*100, 1)} for j in range(len(otros)) if dist_calc[j] < (p1['RAD']+otros[j]['RAD'])]
                        tr = round(calcular_traslape_real(p1, otros), 1)
                        salud = "🟢 Sano" if 30 <= p1['VOL'] <= 50 else "🟡 Medio" if 21 <= p1['VOL'] <= 29 else "🟠 Bajo" if 15 <= p1['VOL'] <= 20 else "🔴 Crítico" if p1['VOL'] >= 51 else "⚪ Fuera de Rango"
                        folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=clrs[p1['R_ID']], fill=True, fill_opacity=0.3, tooltip=f"{p1['NOM']}: {tr}%").add_to(m)
                        if ver_n: folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-shadow: 0 0 1px #FFF; width:100px;">{p1["NOM"]}</div>')).add_to(m)
                        pq_p = round(sum([(p1['VOL'] * (n['porc'] / 100)) / 2 for n in ints]), 1)
                        rep.append({"ST": salud, "Zona": p1['NOM'], "Paquetes Actual": int(p1['VOL']), "Pq Perdidos": pq_p, "Potencial Ideal": round(p1['VOL']+pq_p,1), "% Traslape Real": f"{tr}%", "Detalle": ", ".join([f"{n['nom']}({n['porc']}%)" for n in ints if n['porc']>0]) or "Sano"})
                    if not df_visual.empty: m.fit_bounds([[df_visual['LAT'].min(), df_visual['LON'].min()], [df_visual['LAT'].max(), df_visual['LON'].max()]])

            components.html(m.get_root().render(), height=550)

            if m_ana and rep:
                st.write("---")
                df_rep_f = pd.DataFrame(rep)
                df_rep_f = df_rep_f[df_rep_f['ST'].isin(f_estatus)]
                if modo == "Crecimiento":
                    nh = list(st.session_state.dict_hojas.keys())
                    if st.session_state.idx_hoja > 0:
                        df_prev = st.session_state.dict_hojas[nh[st.session_state.idx_hoja-1]]
                        st.metric("Zonas Nuevas", len(set(df_visual['NOM']) - set(df_prev['NOM'])))
                    st.subheader("📊 Informe Ejecutivo de Crecimiento")
                    st.dataframe(df_rep_f[["ST", "Zona", "% Traslape Real"]], use_container_width=True, hide_index=True)
                elif modo == "Coordenadas":
                    st.subheader("📋 Análisis de Paquetes y Traslapes")
                    st.dataframe(df_rep_f, use_container_width=True, hide_index=True)

            c_d1, c_d2 = st.columns(2)
            c_d1.download_button("🗺️ Exportar Mapa HTML", data=m.get_root().render(), file_name=f"mapa_{modo}.html", use_container_width=True)
            if modo != "Polígonos CP":
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                    if modo == "Crecimiento":
                        res_hist = []
                        for i, n in enumerate(list(st.session_state.dict_hojas.keys())):
                            df_h = st.session_state.dict_hojas[n]
                            pts_h = df_h.to_dict('records')
                            trs = [calcular_traslape_real(p, [x for j, x in enumerate(pts_h) if k != j]) for k, p in enumerate(pts_h)]
                            nuevas = len(set(df_h['NOM']) - set(st.session_state.dict_hojas[list(st.session_state.dict_hojas.keys())[i-1]]['NOM'])) if i > 0 else 0
                            res_hist.append({"Pestaña": n, "Total Zonas": len(df_h), "Zonas Nuevas": nuevas, "% Traslape Promedio": f"{round(np.mean(trs),2)}%"})
                            pd.DataFrame({"Zona": [p['NOM'] for p in pts_h], "% Traslape": [f"{round(t,2)}%" for t in trs]}).to_excel(writer, sheet_name=f"Detalle_{n[:20]}", index=False)
                        pd.DataFrame(res_hist).to_excel(writer, sheet_name='INFORME_EJECUTIVO', index=False)
                    else: pd.DataFrame(rep).to_excel(writer, index=False, sheet_name='Analisis')
                c_d2.download_button("📊 Exportar Informe Excel", data=buf.getvalue(), file_name=f"informe_{modo}.xlsx", use_container_width=True)

