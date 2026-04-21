#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa - Sistema Pro AMZL v7.3 Integral

import streamlit as st
import pandas as pd
import folium
import geopandas as gpd
import os, io, yaml, numpy as np
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
import streamlit.components.v1 as components
import xlsxwriter 
import altair as alt

# --- 1. CONFIGURACIÓN Y CÁLCULOS (PRECISIÓN 10,000) ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

@st.cache_data
def area_interseccion(r1, r2, d):
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return float(np.pi * min(r1, r2)**2)
    p1 = r1**2 * np.arccos(np.clip((d**2 + r1**2 - r2**2) / (2 * d * r1), -1, 1))
    p2 = r2**2 * np.arccos(np.clip((d**2 + r2**2 - r1**2) / (2 * d * r2), -1, 1))
    p3 = 0.5 * np.sqrt(max(0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return float(p1 + p2 - p3)

def calcular_traslape_real(p1, otros_pts):
    if not otros_pts: return 0.0
    n = 10000 
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
    return float((np.sum(cubiertos) / n) * 100)

def obtener_rango_id(v, modo_p):
    lim = [100, 200, 300, 400] if modo_p else [15, 20, 30, 40]
    return int(next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0)

def normalizar(df, modo):
    df.columns = df.columns.str.strip().str.upper()
    mapa = {'LAT':['LATITUD','LAT'],'LON':['LONGITUD','LON'],'VOL':['VOLUMEN','VOL'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA']}
    df = df.rename(columns={c: k for k, v in mapa.items() for c in df.columns if c in v})
    for c in ['LAT','LON','VOL','RAD']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(float)
    if 'RAD' not in df.columns or (df['RAD'] == 0).all(): df['RAD'] = 750.0
    if 'CP' in df.columns: df['CP'] = df['CP'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
    if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'ZONA')
    df['R_ID'] = df['VOL'].apply(lambda x: obtener_rango_id(x, "Polígonos" in modo))
    return df

# --- 2. SEGURIDAD Y ESTADOS ---
with open('config.yaml') as f: config = yaml.load(f, SafeLoader)
auth = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
auth.login(location='main')

if st.session_state.get("authentication_status"):
    if 'idx_hoja' not in st.session_state: st.session_state.idx_hoja = 0
    if 'dict_hojas' not in st.session_state: st.session_state.dict_hojas = None
    if 'df_datos' not in st.session_state: st.session_state.df_datos = None
    if 'analisis_cache' not in st.session_state: st.session_state.analisis_cache = {}
    if 'historico_resumen' not in st.session_state: st.session_state.historico_resumen = []

    col_m, col_p = st.columns([3, 1.3])
    
    with col_p:
        st.title("🛡️ Panel Pro")
        auth.logout('Cerrar Sesión', 'sidebar')
        modo = st.radio("Capa", ["Coordenadas", "Polígonos CP", "Crecimiento"])
        
        # --- SUBSECCIÓN DE PLANTILLAS (RESTAURADA) ---
        st.subheader("📥 Plantillas Base")
        cols_plantilla = {
            "Coordenadas": ["ZONA", "LATITUD", "LONGITUD", "RADIO", "VOLUMEN"],
            "Polígonos CP": ["ZONA", "CP", "VOLUMEN"],
            "Crecimiento": ["ZONA", "LATITUD", "LONGITUD", "RADIO", "VOLUMEN"]
        }
        buf_p = io.BytesIO()
        with pd.ExcelWriter(buf_p, engine='xlsxwriter') as writer_p:
            pd.DataFrame(columns=cols_plantilla[modo]).to_excel(writer_p, index=False, sheet_name='Plantilla')
        st.download_button(f"Bajar Base {modo}", data=buf_p.getvalue(), file_name=f"base_{modo.lower().replace(' ', '_')}.xlsx", use_container_width=True)

        # Lógica GeoJSON para Polígonos
        gdf, col_cp_g, bounds_geo = None, None, None
        if modo == "Polígonos CP":
            archs = sorted([f for f in os.listdir('mapas') if f.endswith('.geojson')]) if os.path.exists('mapas') else []
            if archs:
                edo_sel = st.selectbox("📍 Estado:", [f.replace('.geojson','').replace('_',' ') for f in archs])
                gdf = gpd.read_file(f"mapas/{archs[[f.replace('.geojson','').replace('_',' ') for f in archs].index(edo_sel)]}").to_crs("EPSG:4326")
                col_cp_g = next((c for c in ['d_cp','CP','CODIGOPOSTAL'] if c in gdf.columns), gdf.columns[0])
                b = gdf.total_bounds
                bounds_geo = [[float(b[1]), float(b[0])], [float(b[3]), float(b[2])]]

        xl_file = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if xl_file and st.button("🚀 PROCESAR ARCHIVO"):
            if modo == "Crecimiento":
                xl = pd.ExcelFile(xl_file)
                st.session_state.dict_hojas = {s: normalizar(xl.parse(s), modo) for s in xl.sheet_names}
                st.session_state.analisis_cache = {}; st.session_state.historico_resumen = []
                with st.spinner("Procesando histórico (10,000 pts)..."):
                    for i, (nombre, df_h) in enumerate(st.session_state.dict_hojas.items()):
                        pts = df_h.to_dict('records')
                        res = []
                        for k, p1 in enumerate(pts):
                            otros = [p for j, p in enumerate(pts) if k != j]
                            tr = round(calcular_traslape_real(p1, otros), 1)
                            st_v = "🟢 Sano" if 30 <= p1['VOL'] <= 50 else "🟡 Medio" if 21 <= p1['VOL'] <= 29 else "🟠 Bajo" if 15 <= p1['VOL'] <= 20 else "🔴 Crítico" if p1['VOL'] >= 51 else "⚪ Fuera de Rango"
                            res.append({"Mes": nombre, "ST": st_v, "Zona": p1['NOM'], "Traslape": tr, "R_ID": p1['R_ID'], "LAT": p1['LAT'], "LON": p1['LON'], "RAD": p1['RAD'], "VOL": p1['VOL']})
                        prom = float(np.mean([r['Traslape'] for r in res]))
                        nuevas = len(set(df_h['NOM']) - set(st.session_state.dict_hojas[list(st.session_state.dict_hojas.keys())[i-1]]['NOM'])) if i > 0 else 0
                        st.session_state.analisis_cache[nombre] = res
                        st.session_state.historico_resumen.append({"Mes": nombre, "Zonas": len(df_h), "Nuevas": nuevas, "Prom": prom, "idx": i})
                st.session_state.idx_hoja = 0
            else:
                st.session_state.df_datos = normalizar(pd.read_excel(xl_file), modo)
            st.rerun()

        if modo == "Crecimiento" and st.session_state.dict_hojas:
            nh = list(st.session_state.dict_hojas.keys())
            c1, c2 = st.columns(2)
            if c1.button("⬅️ Anterior") and st.session_state.idx_hoja > 0: st.session_state.idx_hoja -= 1
            if c2.button("Siguiente ➡️") and st.session_state.idx_hoja < len(nh)-1: st.session_state.idx_hoja += 1

        st.write("---")
        labs = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
        cols_f = st.columns(3); acts = [i for i, l in enumerate(labs) if cols_f[i%3].checkbox(l, value=True, key=f"r{i}_{modo}")]
        ver_n = st.toggle("🏷️ Ver Nombres Fijos", key="persist_nombres")
        m_ana = st.toggle("🔍 Tabla de Análisis", key="persist_analisis")
        if m_ana: f_estatus = st.multiselect("ST:", ["🟢 Sano", "🟡 Medio", "🟠 Bajo", "🔴 Crítico", "⚪ Fuera de Rango"], default=["🟢 Sano", "🟡 Medio", "🟠 Bajo", "🔴 Crítico"])

    with col_m:
        hay_datos = (modo == "Crecimiento" and st.session_state.dict_hojas) or (modo != "Crecimiento" and st.session_state.df_datos is not None)
        if not hay_datos: st.info("👋 Bienvenida. Por favor, descarga la plantilla y sube tu archivo.")
        else:
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            clrs = {0:"#FFF", 1:"#FF0", 2:"#FFA500", 3:"#F00", 4:"#FF4500", 5:"#800000"}
            rep = []

            if modo == "Crecimiento":
                nh_all = list(st.session_state.dict_hojas.keys())
                for i_fg, nom_fg in enumerate(nh_all):
                    fg = folium.FeatureGroup(name=nom_fg, show=(i_fg == st.session_state.idx_hoja))
                    data_fg = [r for r in st.session_state.analisis_cache[nom_fg] if r['R_ID'] in acts]
                    for p in data_fg:
                        folium.Circle([p['LAT'], p['LON']], radius=p['RAD'], color=clrs[p['R_ID']], fill=True, fill_opacity=0.3, tooltip=f"{p['Zona']}: {p['Traslape']}%").add_to(fg)
                        if ver_n: folium.Marker([p['LAT'], p['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-shadow: 0 0 1px #FFF; width:100px;">{p["Zona"]}</div>')).add_to(fg)
                    fg.add_to(m)
                folium.LayerControl(collapsed=False).add_to(m)
                df_curr = st.session_state.dict_hojas[nh_all[st.session_state.idx_hoja]]
                m.fit_bounds([[df_curr['LAT'].min(), df_curr['LON'].min()], [df_curr['LAT'].max(), df_curr['LON'].max()]])
            
            elif modo == "Polígonos CP" and gdf is not None:
                df_v_pol = st.session_state.df_datos[st.session_state.df_datos['R_ID'].isin(acts)].set_index('CP')
                m.fit_bounds(bounds_geo)
                for _, r in gdf.iterrows():
                    cp = str(r[col_cp_g]).zfill(5)
                    if cp in df_v_pol.index:
                        vol, nom = df_v_pol.loc[cp, 'VOL'], df_v_pol.loc[cp, 'NOM']
                        folium.GeoJson(r['geometry'], style_function=lambda x, v=vol: {'fillColor':clrs[obtener_rango_id(v,True)], 'color':'#000', 'weight':1, 'fillOpacity':0.4}).add_to(m)
                        if ver_n:
                            c = r['geometry'].centroid
                            folium.Marker([float(c.y), float(c.x)], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-align:center; width:80px;">{nom}</div>')).add_to(m)
            
            else: # Coordenadas
                df_v = st.session_state.df_datos[st.session_state.df_datos['R_ID'].isin(acts)]
                pts = df_v.to_dict('records')
                for i, p1 in enumerate(pts):
                    tr = round(calcular_traslape_real(p1, [p for j, p in enumerate(pts) if i != j]), 1)
                    folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=clrs[p1['R_ID']], fill=True, fill_opacity=0.3, tooltip=f"{p1['NOM']}: {tr}%").add_to(m)
                    if ver_n: folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-shadow: 0 0 1px #FFF; width:100px;">{p1["NOM"]}</div>')).add_to(m)
                    rep.append({"ST": "🟢 Sano" if 30 <= p1['VOL'] <= 50 else "🟡 Medio", "Zona": p1['NOM'], "Paquetes": int(p1['VOL']), "Traslape Real": f"{tr}%"})
                if not df_v.empty: m.fit_bounds([[df_v['LAT'].min(), df_v['LON'].min()], [df_v['LAT'].max(), df_v['LON'].max()]])

            components.html(m.get_root().render(), height=450)

            if m_ana:
                if modo == "Crecimiento":
                    df_h = pd.DataFrame(st.session_state.historico_resumen)
                    chart = alt.layer(
                        alt.Chart(df_h).mark_bar().encode(x=alt.X('Mes:O', sort=alt.SortField('idx')), y='Zonas:Q', color=alt.condition(alt.datum.Prom >= 80, alt.value('#dc3545'), alt.value('#1f77b4'))),
                        alt.Chart(df_h).mark_line(color='#ff7f0e', size=3).encode(x=alt.X('Mes:O', sort=alt.SortField('idx')), y='Prom:Q')
                    ).resolve_scale(y='independent').properties(height=250)
                    st.altair_chart(chart, use_container_width=True)
                    st.markdown(f"<h1 style='text-align: center; color: #ff4b4b;'>{nh_all[st.session_state.idx_hoja]}</h1>", unsafe_allow_html=True)
                    
                    df_ex = pd.DataFrame(st.session_state.analisis_cache[nh_all[st.session_state.idx_hoja]])
                    df_ex = df_ex[df_ex['ST'].isin(f_estatus)]
                    b, m_v, c, tot = len(df_ex[df_ex['Traslape'] <= 30]), len(df_ex[(df_ex['Traslape'] > 30) & (df_ex['Traslape'] < 80)]), len(df_ex[df_ex['Traslape'] >= 80]), len(df_ex)
                    
                    st.markdown(f"""
                    <div style="display: flex; justify-content: space-around; background: #1e1e1e; padding: 15px; border-radius: 10px; border: 1px solid #444;">
                        <div style="text-align: center;"><p style="color: #bbb; margin:0;">📊 Promedio</p><h2 style="margin:0;">{round(df_ex['Traslape'].mean(), 1) if tot else 0}%</h2></div>
                        <div style="text-align: center;"><p style="color: #28a745; font-weight: bold; margin:0;">🟢 Bajo</p><h2 style="margin:0; color: #28a745;">{b} ({round(b/tot*100,1) if tot else 0}%)</h2></div>
                        <div style="text-align: center;"><p style="color: #ffc107; font-weight: bold; margin:0;">🟡 Medio</p><h2 style="margin:0; color: #ffc107;">{m_v} ({round(m_v/tot*100,1) if tot else 0}%)</h2></div>
                        <div style="text-align: center;"><p style="color: #dc3545; font-weight: bold; margin:0;">🔴 Crítico</p><h2 style="margin:0; color: #dc3545;">{c} ({round(c/tot*100,1) if tot else 0}%)</h2></div>
                    </div>
                    """, unsafe_allow_html=True)
                    st.dataframe(df_ex[["ST", "Zona", "Traslape"]].rename(columns={"Traslape":"% Traslape Real"}), use_container_width=True, hide_index=True)
                elif modo == "Coordenadas":
                    st.dataframe(pd.DataFrame(rep), use_container_width=True, hide_index=True)

            # --- EXPORTACIÓN ---
            c_d1, c_d2 = st.columns(2)
            c_d1.download_button("🗺️ Exportar Mapa HTML", data=m.get_root().render(), file_name=f"mapa_{modo.lower()}.html", use_container_width=True)
            if modo != "Polígonos CP":
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                    if modo == "Crecimiento":
                        df_h.to_excel(writer, sheet_name='EJECUTIVO', index=False)
                        for ns in st.session_state.dict_hojas.keys():
                            pd.DataFrame(st.session_state.analisis_cache[ns])[["Zona", "Traslape"]].to_excel(writer, sheet_name=ns[:25], index=False)
                    else: pd.DataFrame(rep).to_excel(writer, index=False, sheet_name='Analisis')
                c_d2.download_button("📊 Exportar Informe Excel", data=buf.getvalue(), file_name=f"informe_{modo.lower()}.xlsx", use_container_width=True)
