#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa - Sistema Pro AMZL v7.9 (Interactive HTML Fix)

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
        
        st.subheader("📥 Plantillas")
        cols_b = {"Coordenadas":["ZONA","LATITUD","LONGITUD","RADIO","VOLUMEN"],"Polígonos CP":["ZONA","CP","VOLUMEN"],"Crecimiento":["ZONA","LATITUD","LONGITUD","RADIO","VOLUMEN"]}
        buf_p = io.BytesIO()
        pd.DataFrame(columns=cols_b[modo]).to_excel(buf_p, index=False)
        st.download_button(f"Base {modo}", data=buf_p.getvalue(), file_name=f"plantilla_{modo.lower().replace(' ','_')}.xlsx", use_container_width=True)

        xl_file = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if xl_file and st.button("🚀 PROCESAR"):
            if modo == "Crecimiento":
                xl = pd.ExcelFile(xl_file)
                st.session_state.dict_hojas = {s: normalizar(xl.parse(s), modo) for s in xl.sheet_names}
                st.session_state.analisis_cache = {}; st.session_state.historico_resumen = []
                for i, (nombre, df_h) in enumerate(st.session_state.dict_hojas.items()):
                    pts = df_h.to_dict('records')
                    res = []
                    for k, p1 in enumerate(pts):
                        tr = round(calcular_traslape_real(p1, [p for j, p in enumerate(pts) if k != j]), 1)
                        st_l, icon = ("Bajo", "🟢") if tr <= 25 else ("Medio", "🟡") if tr <= 50 else ("Alto", "🟠") if tr <= 75 else ("Crítico", "🔴")
                        res.append({"ST": f"{icon} {st_l}", "Zona": p1['NOM'], "Traslape": tr, "R_ID": p1['R_ID'], "LAT": p1['LAT'], "LON": p1['LON'], "RAD": p1['RAD'], "VOL": p1['VOL']})
                    st.session_state.analisis_cache[nombre] = res
                    st.session_state.historico_resumen.append({"Mes": nombre, "Zonas": len(df_h), "Prom": float(np.mean([r['Traslape'] for r in res])), "idx": i})
                st.session_state.idx_hoja = 0
            else:
                st.session_state.df_datos = normalizar(pd.read_excel(xl_file), modo)
            st.rerun()

        if modo == "Crecimiento" and st.session_state.dict_hojas:
            nh_list = list(st.session_state.dict_hojas.keys())
            c1, c2 = st.columns(2)
            if c1.button("⬅️ Anterior") and st.session_state.idx_hoja > 0: st.session_state.idx_hoja -= 1
            if c2.button("Siguiente ➡️") and st.session_state.idx_hoja < len(nh_list)-1: st.session_state.idx_hoja += 1

        st.write("---")
        labs = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
        cols_f = st.columns(3); acts = [i for i, l in enumerate(labs) if cols_f[i%3].checkbox(l, value=True, key=f"r{i}_{modo}")]
        ver_n = st.toggle("🏷️ Ver Nombres Fijos", key="persist_nombres")
        m_ana = st.toggle("🔍 Tabla de Análisis", key="persist_analisis")

    with col_m:
        hay_d = (modo == "Crecimiento" and st.session_state.dict_hojas) or (modo != "Crecimiento" and st.session_state.df_datos is not None)
        if not hay_d: st.info("👋 Por favor, procesa un archivo para visualizar.")
        else:
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            clrs = {0:"#FFF", 1:"#FF0", 2:"#FFA500", 3:"#F00", 4:"#FF4500", 5:"#800000"}
            rep = []

            if modo == "Crecimiento":
                nh_all = list(st.session_state.dict_hojas.keys())
                for i_fg, nom_fg in enumerate(nh_all):
                    # El mapa descargado tendrá todas las capas seleccionables
                    fg = folium.FeatureGroup(name=nom_fg, show=(i_fg == st.session_state.idx_hoja))
                    data_fg = [r for r in st.session_state.analisis_cache[nom_fg] if r['R_ID'] in acts]
                    for p in data_fg:
                        folium.Circle([p['LAT'], p['LON']], radius=p['RAD'], color=clrs[p['R_ID']], fill=True, fill_opacity=0.3, tooltip=f"{p['Zona']}: {p['Traslape']}%").add_to(fg)
                        if ver_n: folium.Marker([p['LAT'], p['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-shadow: 0 0 1px #FFF; width:100px;">{p["Zona"]}</div>')).add_to(fg)
                    fg.add_to(m)
                folium.LayerControl(position='topright', collapsed=False).add_to(m)
                df_curr = st.session_state.dict_hojas[nh_all[st.session_state.idx_hoja]]
                m.fit_bounds([[df_curr['LAT'].min(), df_curr['LON'].min()], [df_curr['LAT'].max(), df_curr['LON'].max()]])
            
            else: # Lógica para Coordenadas/Polígonos normal
                df_v = st.session_state.df_datos[st.session_state.df_datos['R_ID'].isin(acts)]
                pts = df_v.to_dict('records')
                for i, p1 in enumerate(pts):
                    tr = round(calcular_traslape_real(p1, [p for j, p in enumerate(pts) if i != j]), 1)
                    folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=clrs[p1['R_ID']], fill=True, fill_opacity=0.3).add_to(m)
                    if ver_n: folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-shadow: 0 0 1px #FFF; width:100px;">{p1["NOM"]}</div>')).add_to(m)
                    rep.append({"ST": "🟢 Sano" if tr <= 25 else "🟡 Medio", "ZONA": p1['NOM'], "% TRANSLAPE REAL": f"{tr}%"})
                if not df_v.empty: m.fit_bounds([[df_v['LAT'].min(), df_v['LON'].min()], [df_v['LAT'].max(), df_v['LON'].max()]])

            map_html = m.get_root().render()
            components.html(map_html, height=450)

            if m_ana and modo == "Crecimiento":
                st.write("---")
                df_h = pd.DataFrame(st.session_state.historico_resumen)
                chart = alt.layer(
                    alt.Chart(df_h).mark_bar().encode(x=alt.X('Mes:O', sort=alt.SortField('idx')), y='Zonas:Q', color=alt.value('#1f77b4')),
                    alt.Chart(df_h).mark_line(color='#ff7f0e', size=3).encode(x=alt.X('Mes:O', sort=alt.SortField('idx')), y='Prom:Q')
                ).resolve_scale(y='independent').properties(height=200)
                st.altair_chart(chart, use_container_width=True)

                hoja_act = nh_all[st.session_state.idx_hoja]
                tot_z = st.session_state.historico_resumen[st.session_state.idx_hoja]['Zonas']
                st.markdown(f"<h1 style='text-align: center; color: #ff4b4b;'>{hoja_act} ({tot_z} Zonas)</h1>", unsafe_allow_html=True)

                df_ex = pd.DataFrame(st.session_state.analisis_cache[hoja_act])
                p_act = st.session_state.historico_resumen[st.session_state.idx_hoja]['Prom']
                delta_h = ""
                if st.session_state.idx_hoja > 0:
                    dif = p_act - st.session_state.historico_resumen[st.session_state.idx_hoja-1]['Prom']
                    c_d, s_d = ("#dc3545", "▲") if dif > 0 else ("#28a745", "▼")
                    delta_h = f"<p style='color:{c_d}; font-size:14px; font-weight:bold; margin:0;'>{s_d} {abs(round(dif,1))}% vs mes ant.</p>"

                b, m_v, a, c = len(df_ex[df_ex['Traslape'] <= 25]), len(df_ex[(df_ex['Traslape'] > 25) & (df_ex['Traslape'] <= 50)]), len(df_ex[(df_ex['Traslape'] > 50) & (df_ex['Traslape'] <= 75)]), len(df_ex[df_ex['Traslape'] > 75])
                t_e = len(df_ex) if len(df_ex) > 0 else 1
                st.markdown(f"""
                <div style="display: flex; justify-content: space-around; background: #1e1e1e; padding: 15px; border-radius: 10px; border: 1px solid #444; text-align: center;">
                    <div><p style="color: #bbb; margin:0;">📊 Promedio</p><h2 style="margin:0;">{round(p_act,1)}%</h2>{delta_h}</div>
                    <div><p style="color: #28a745; font-weight: bold; margin:0;">🟢 Bajo (0-25%)</p><h2 style="margin:0; color: #28a745;">{round(b/t_e*100,1)}%</h2><p style="color:#28a745; margin:0;">{b} zonas</p></div>
                    <div><p style="color: #ffc107; font-weight: bold; margin:0;">🟡 Medio (26-50%)</p><h2 style="margin:0; color: #ffc107;">{round(m_v/t_e*100,1)}%</h2><p style="color:#ffc107; margin:0;">{m_v} zonas</p></div>
                    <div><p style="color: #fd7e14; font-weight: bold; margin:0;">🟠 Alto (51-75%)</p><h2 style="margin:0; color: #fd7e14;">{round(a/t_e*100,1)}%</h2><p style="color:#fd7e14; margin:0;">{a} zonas</p></div>
                    <div><p style="color: #dc3545; font-weight: bold; margin:0;">🔴 Crítico (>75%)</p><h2 style="margin:0; color: #dc3545;">{round(c/t_e*100,1)}%</h2><p style="color:#dc3545; margin:0;">{c} zonas</p></div>
                </div>
                """, unsafe_allow_html=True)
                df_t = df_ex[["ST", "Zona", "Traslape"]].copy()
                df_t["Traslape"] = df_t["Traslape"].astype(str) + "%"
                st.dataframe(df_t.rename(columns={"Zona":"ZONA", "Traslape":"% TRANSLAPE REAL"}), use_container_width=True, hide_index=True)
            elif m_ana and modo == "Coordenadas":
                st.subheader("📋 Análisis Capa Coordenadas")
                st.dataframe(pd.DataFrame(rep), use_container_width=True, hide_index=True)

            c1, c2 = st.columns(2)
            c1.download_button("🗺️ Mapa HTML Interactivo", data=map_html, file_name=f"mapa_interactivo_{modo.lower()}.html", use_container_width=True)
            if modo != "Polígonos CP":
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as wr:
                    if modo == "Crecimiento":
                        pd.DataFrame(st.session_state.historico_resumen).to_excel(wr, sheet_name='EJECUTIVO', index=False)
                        for ns in st.session_state.dict_hojas.keys():
                            df_tmp = pd.DataFrame(st.session_state.analisis_cache[ns])
                            df_tmp["% TRANSLAPE"] = df_tmp["Traslape"].astype(str) + "%"
                            df_tmp[["ST","Zona","% TRANSLAPE"]].to_excel(wr, sheet_name=ns[:25], index=False)
                    else: pd.DataFrame(rep).to_excel(wr, index=False)
                c2.download_button("📊 Informe Excel", data=buf.getvalue(), file_name=f"informe_{modo.lower()}.xlsx", use_container_width=True)
