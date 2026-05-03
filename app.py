#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa - Sistema Pro AMZL v8.5 Final Verified

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

# --- 1. CONFIGURACIÓN Y CÁLCULOS ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

@st.cache_data
def area_interseccion(r1, r2, d):
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return float(np.pi * min(r1, r2)**2)
    p1, p2 = r1**2, r2**2
    phi1 = np.arccos(np.clip((d**2 + r1**2 - r2**2) / (2 * d * r1), -1, 1))
    phi2 = np.arccos(np.clip((d**2 + r2**2 - r1**2) / (2 * d * r2), -1, 1))
    a = 0.5 * np.sqrt(max(0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return float(p1 * phi1 + p2 * phi2 - a)

def calcular_traslape_real(p1, otros_pts):
    if not otros_pts: return 0.0
    n = 10000 # Precisión 10k
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
    return float((np.sum(cubiertos) / n) * 100)

def obtener_rango_id(v, modo_p):
    lim = [100, 200, 300, 400] if modo_p else [15, 20, 30, 40]
    return int(next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0)

def normalizar(df, modo):
    df.columns = df.columns.str.strip().str.upper()
    mapa = {'LAT':['LATITUD','LAT'],'LON':['LONGITUD','LON'],'VOL':['VOLUMEN','VOL'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.','CODIGOPOSTAL'],'NOM':['NOMBRE','ZONA']}
    df = df.rename(columns={c: k for k, v in mapa.items() for c in df.columns if c in v})
    for c in ['LAT','LON','VOL','RAD']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(float)
    if 'CP' in df.columns: 
        df['CP'] = df['CP'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
    if 'RAD' not in df.columns or (df['RAD'] == 0).all(): df['RAD'] = 750.0
    if 'NOM' not in df.columns: df['NOM'] = df.get('CP', 'ZONA')
    df['R_ID'] = df['VOL'].apply(lambda x: obtener_rango_id(x, "Polígonos" in modo))
    return df

# --- 2. SEGURIDAD ---
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
        
        # --- PLANTILLAS ---
        st.subheader("📥 Plantillas")
        c_b = {"Coordenadas":["ZONA","LATITUD","LONGITUD","RADIO","VOLUMEN"], "Polígonos CP":["ZONA","CP","VOLUMEN"], "Crecimiento":["ZONA","LATITUD","LONGITUD","RADIO","VOLUMEN"]}
        buf_p = io.BytesIO()
        pd.DataFrame(columns=c_b[modo]).to_excel(buf_p, index=False); st.download_button(f"Base {modo}", data=buf_p.getvalue(), file_name=f"plantilla_{modo.lower().replace(' ','_')}.xlsx", use_container_width=True)

        gdf_pol, col_cp_geo, b_pol = None, None, None
        if modo == "Polígonos CP":
            archs = sorted([f for f in os.listdir('mapas') if f.endswith('.geojson')]) if os.path.exists('mapas') else []
            if archs:
                edo_sel = st.selectbox("📍 Estado:", [f.replace('.geojson','').replace('_',' ') for f in archs])
                gdf_pol = gpd.read_file(f"mapas/{archs[[f.replace('.geojson','').replace('_',' ') for f in archs].index(edo_sel)]}").to_crs("EPSG:4326")
                col_cp_geo = next((c for c in ['d_cp','CP','CODIGOPOSTAL'] if c in gdf_pol.columns), gdf_pol.columns[0])
                b = gdf_pol.total_bounds; b_pol = [[float(b[1]), float(b[0])], [float(b[3]), float(b[2])]]

        xl_file = st.file_uploader("📂 Cargar Excel", type=["xlsx"])
        if xl_file and st.button("🚀 PROCESAR"):
            if modo == "Crecimiento":
                xl = pd.ExcelFile(xl_file); st.session_state.dict_hojas = {s: normalizar(xl.parse(s), modo) for s in xl.sheet_names}
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
            else: st.session_state.df_datos = normalizar(pd.read_excel(xl_file), modo)
            st.rerun()

        if modo == "Crecimiento" and st.session_state.dict_hojas:
            nh = list(st.session_state.dict_hojas.keys())
            c1, c2 = st.columns(2)
            if c1.button("⬅️ Ant.") and st.session_state.idx_hoja > 0: st.session_state.idx_hoja -= 1
            if c2.button("Sig. ➡️") and st.session_state.idx_hoja < len(nh)-1: st.session_state.idx_hoja += 1

        st.write("---")
        labs = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
        acts = [i for i, l in enumerate(labs) if st.checkbox(l, value=True, key=f"r{i}_{modo}")]
        ver_n = st.toggle("🏷️ Ver Nombres Fijos", key="persist_nombres")
        m_ana = st.toggle("🔍 Tabla de Análisis", key="persist_analisis")

    with col_m:
        hay_d = (modo == "Crecimiento" and st.session_state.dict_hojas) or (modo != "Crecimiento" and st.session_state.df_datos is not None)
        if not hay_d: st.info("👋 Por favor, procesa un archivo para visualizar.")
        else:
            m = folium.Map(location=[19.4, -99.1], zoom_start=11, tiles="CartoDB Voyager")
            clrs = {0:"#FFF", 1:"#FF0", 2:"#FFA500", 3:"#F00", 4:"#FF4500", 5:"#800000"}; rep_coords = []

            if modo == "Crecimiento":
                nh_all = list(st.session_state.dict_hojas.keys())
                for i_fg, nom_fg in enumerate(nh_all):
                    fg = folium.FeatureGroup(name=nom_fg, show=(i_fg == st.session_state.idx_hoja))
                    data_fg = [r for r in st.session_state.analisis_cache[nom_fg] if r['R_ID'] in acts]
                    for p in data_fg:
                        folium.Circle([p['LAT'], p['LON']], radius=p['RAD'], color=clrs[p['R_ID']], fill=True, fill_opacity=0.3, tooltip=f"{p['Zona']}: {p['Traslape']}%").add_to(fg)
                        if ver_n: folium.Marker([p['LAT'], p['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-shadow: 0 0 1px #FFF; width:100px;">{p["Zona"]}</div>')).add_to(fg)
                    fg.add_to(m)
                folium.LayerControl(position='topright', collapsed=False).add_to(m)
                df_c = st.session_state.dict_hojas[nh_all[st.session_state.idx_hoja]]
                m.fit_bounds([[df_c['LAT'].min(), df_c['LON'].min()], [df_c['LAT'].max(), df_c['LON'].max()]])
            
            elif modo == "Polígonos CP" and gdf_pol is not None:
                df_p = st.session_state.df_datos[st.session_state.df_datos['R_ID'].isin(acts)].set_index('CP')
                for _, r in gdf_pol.iterrows():
                    cp_g = str(r[col_cp_geo]).zfill(5)
                    if cp_g in df_p.index:
                        row = df_p.loc[cp_g]
                        v_p = row['VOL'] if isinstance(row, pd.Series) else row.iloc[0]['VOL']
                        n_p = row['NOM'] if isinstance(row, pd.Series) else row.iloc[0]['NOM']
                        
                        # --- MODIFICACIÓN: SE AGREGA TOOLTIP ---
                        folium.GeoJson(
                            r['geometry'], 
                            style_function=lambda x, v=v_p: {
                                'fillColor':clrs[obtener_rango_id(v,True)], 
                                'color':'#000', 
                                'weight':1, 
                                'fillOpacity':0.4
                            },
                            tooltip=f"Zona: {n_p} | Vol: {int(v_p)}"
                        ).add_to(m)
                        
                        if ver_n:
                            c = r['geometry'].centroid
                            folium.Marker([c.y, c.x], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-align:center; width:80px;">{n_p}</div>')).add_to(m)
                m.fit_bounds(b_pol)

            else: # Coordenadas
                df_v = st.session_state.df_datos[st.session_state.df_datos['R_ID'].isin(acts)]
                pts = df_v.to_dict('records')
                for i, p1 in enumerate(pts):
                    otros = [p for j, p in enumerate(pts) if i != j]
                    tr_r = round(calcular_traslape_real(p1, otros), 1)
                    vol_p = int(p1['VOL'])
                    
                    # --- LÓGICA DE ANÁLISIS CORREGIDA ---
                    if (25 <= vol_p <= 35) or (tr_r < 50):
                        st_v = "🟢 Sano"
                    elif (tr_r >= 50) and (vol_p < 25):
                        st_v = "🔴 Crítico"
                    else:
                        st_v = "🟡 Atención" # Para volúmenes > 35 con traslape > 50%
                    
                    ints = [round((area_interseccion(p1['RAD'], p2['RAD'], np.sqrt((p1['LAT']-p2['LAT'])**2 + ((p1['LON']-p2['LON'])*np.cos(np.radians(p1['LAT'])))**2)*111139)/(np.pi*p1['RAD']**2))*100,1) for p2 in otros if np.sqrt((p1['LAT']-p2['LAT'])**2 + ((p1['LON']-p2['LON'])*np.cos(np.radians(p1['LAT'])))**2)*111139 < (p1['RAD']+p2['RAD'])]
                    folium.Circle([p1['LAT'], p1['LON']], radius=p1['RAD'], color=clrs[p1['R_ID']], fill=True, fill_opacity=0.3, tooltip=f"{p1['NOM']}: {tr_r}%").add_to(m)
                    
                    if ver_n: 
                        folium.Marker([p1['LAT'], p1['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:#000; text-shadow: 0 0 1px #FFF; width:100px;">{p1["NOM"]}</div>')).add_to(m)
                    
                    rep_coords.append({
                        "ST": st_v, 
                        "ZONA": p1['NOM'], 
                        "VOLUMEN": vol_p, 
                        "TRANSLAPE REAL": f"{tr_r}%", 
                        "TRANSLAPE ACUMULADO": f"{round(sum(ints),1)}%"
                    })
                
                if not df_v.empty: 
                    m.fit_bounds([[df_v['LAT'].min(), df_v['LON'].min()], [df_v['LAT'].max(), df_v['LON'].max()]])

            map_html = m.get_root().render(); components.html(map_html, height=450)

            # --- CÁLCULOS SIEMPRE DISPONIBLES PARA EXCEL Y DASHBOARD ---
            if modo == "Crecimiento":
                hoja_act = nh_all[st.session_state.idx_hoja]
                df_ex = pd.DataFrame(st.session_state.analisis_cache[hoja_act])
                t_e = len(df_ex) or 1
                b = len(df_ex[df_ex['Traslape'] <= 25])
                m_v = len(df_ex[(df_ex['Traslape'] > 25) & (df_ex['Traslape'] <= 50)])
                a = len(df_ex[(df_ex['Traslape'] > 50) & (df_ex['Traslape'] <= 75)])
                c = len(df_ex[df_ex['Traslape'] > 75])

            # --- CÁLCULOS PREVIOS (SIEMPRE DISPONIBLES) ---
            if modo == "Crecimiento":
                idx_actual = st.session_state.idx_hoja
                hoja_act = nh_all[idx_actual]
                df_ex = pd.DataFrame(st.session_state.analisis_cache[hoja_act])
                t_e = len(df_ex) or 1
                b = len(df_ex[df_ex['Traslape'] <= 25])
                m_v = len(df_ex[(df_ex['Traslape'] > 25) & (df_ex['Traslape'] <= 50)])
                a = len(df_ex[(df_ex['Traslape'] > 50) & (df_ex['Traslape'] <= 75)])
                c = len(df_ex[df_ex['Traslape'] > 75])
                p_act = st.session_state.historico_resumen[idx_actual]['Prom']

            if m_ana:
                st.write("---")
                if modo == "Crecimiento":
                    # --- TÍTULO Y DASHBOARD ---
                    st.markdown(f"<h2 style='text-align: center;'>{hoja_act} ({t_e} VRs)</h2>", unsafe_allow_html=True)
                    
                    df_h = pd.DataFrame(st.session_state.historico_resumen)
                    base = alt.Chart(df_h).encode(x=alt.X('Mes:O', sort=alt.SortField('idx'), title="Meses"))
                    barras = base.mark_bar(color='#1f77b4', opacity=0.4).encode(y=alt.Y('Zonas:Q', title="Total VRs"))
                    linea = base.mark_line(color='#FFD700', size=4, point=True).encode(y=alt.Y('Prom:Q', title="Traslape Total (%)"))
                    etiquetas = linea.mark_text(align='center', baseline='bottom', dy=-12, color='white', fontWeight='bold').encode(text=alt.Text('Prom:Q', format='.1f'))
                    st.altair_chart(alt.layer(barras, linea, etiquetas).resolve_scale(y='independent').properties(height=300), use_container_width=True)

                    # --- INDICADORES CON DELTA ---
                    delta_html = ""
                    if idx_actual > 0:
                        diff = round(p_act - st.session_state.historico_resumen[idx_actual-1]['Prom'], 1)
                        color_d, icon_d = ("#dc3545", "▲") if diff > 0 else ("#28a745", "▼")
                        delta_html = f"<p style='color:{color_d}; font-size:15px; margin:0;'>{icon_d} {abs(diff)}% vs mes ant.</p>"

                    st.markdown(f"""
                        <div style="display: flex; justify-content: space-around; background: #1e1e1e; padding: 20px; border-radius: 12px; border: 1px solid #444; text-align: center;">
                            <div><p style="color: #bbb; margin:0;">📊 Traslape Total</p><h2 style="margin:0;">{round(p_act,1)}%</h2>{delta_html}</div>
                            <div style="border-left: 1px solid #444; padding-left: 20px;"><p style="color: #28a745; font-weight: bold; margin:0;">🟢 Bajo</p><h2 style="margin:0; color: #28a745;">{round(b/t_e*100,1)}%</h2><p style="color:#28a745; margin:0;">{b} VRs</p></div>
                            <div><p style="color: #ffc107; font-weight: bold; margin:0;">🟡 Medio</p><h2 style="margin:0; color: #ffc107;">{round(m_v/t_e*100,1)}%</h2><p style="color:#ffc107; margin:0;">{m_v} VRs</p></div>
                            <div><p style="color: #fd7e14; font-weight: bold; margin:0;">🟠 Alto</p><h2 style="margin:0; color: #fd7e14;">{round(a/t_e*100,1)}%</h2><p style="color:#fd7e14; margin:0;">{a} VRs</p></div>
                            <div><p style="color: #dc3545; font-weight: bold; margin:0;">🔴 Crítico</p><h2 style="margin:0; color: #dc3545;">{round(c/t_e*100,1)}%</h2><p style="color:#dc3545; margin:0;">{c} VRs</p></div>
                        </div><br>""", unsafe_allow_html=True)
                    
                    st.dataframe(df_ex[["ST", "Zona", "VOL", "Traslape"]].rename(columns={"Zona":"VR", "VOL":"VOLUMEN", "Traslape":"% TR"}), use_container_width=True, hide_index=True)
                
                elif modo == "Coordenadas":
                    st.subheader("📋 Análisis Operativo")
                    st.dataframe(pd.DataFrame(rep_coords), use_container_width=True, hide_index=True)
    
        # --- SECCIÓN DE DESCARGAS: DASHBOARD ESTRATÉGICO FINAL (REESTABLECIDA Y MEJORADA) ---
        from datetime import datetime
        import xlsxwriter.utility
        import unicodedata

        def limpiar_texto_pro(t):
            if not isinstance(t, str): return str(t)
            t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('ASCII')
            return t.strip().upper()

        st.write("---")
        c_desc1, c_desc2 = st.columns(2)

        # 1. RENDERIZADO ÚNICO DEL MAPA (Como estaba cuando funcionaba)
        map_html = m.get_root().render()
        components.html(map_html, height=500) 
        
        c_desc1.download_button(label="🗺️ Descargar Mapa HTML", data=map_html, file_name=f"mapa_{modo.lower().replace(' ','_')}.html", use_container_width=True)

        # 2. GENERACIÓN DEL EXCEL RÉPLICA IMAGEN
        fecha_hoy = datetime.now().strftime("%d_%m_%Y")
        nombre_archivo_excel = f"REPORTE_{fecha_hoy}.xlsx"
        buf = io.BytesIO()
        
        with pd.ExcelWriter(buf, engine='xlsxwriter') as wr:
            wb = wr.book
            # --- FORMATOS DE ALTA FIDELIDAD ---
            f_white = wb.add_format({'bg_color': '#FFFFFF'})
            f_title = wb.add_format({'bold': True, 'font_size': 14, 'font_color': '#000000'})
            f_hdr   = wb.add_format({'bold': True, 'bg_color': '#1F4E78', 'font_color': 'white', 'border': 1, 'align': 'center', 'font_size': 9})
            f_lbl   = wb.add_format({'bold': True, 'bg_color': '#1F4E78', 'font_color': 'white', 'border': 1, 'align': 'left', 'font_size': 8})
            f_perc  = wb.add_format({'bg_color': '#FFFFFF', 'bold': True, 'align': 'center', 'num_format': '0.0%', 'border': 1, 'font_size': 9})
            f_val   = wb.add_format({'bg_color': '#FFFFFF', 'align': 'center', 'border': 1, 'font_size': 9})
            
            f_v = wb.add_format({'bg_color': '#92D050', 'bold': True, 'border': 1, 'num_format': '0.0%', 'align': 'center'})
            f_a = wb.add_format({'bg_color': '#FFFF00', 'bold': True, 'border': 1, 'num_format': '0.0%', 'align': 'center'})
            f_n = wb.add_format({'bg_color': '#FFC000', 'bold': True, 'border': 1, 'num_format': '0.0%', 'align': 'center'})
            f_r = wb.add_format({'bg_color': '#FF0000', 'font_color': 'white', 'bold': True, 'border': 1, 'num_format': '0.0%', 'align': 'center'})

            if modo == "Crecimiento" and st.session_state.historico_resumen:
                ws = wb.add_worksheet("RESUMEN")
                ws.hide_gridlines(2)
                ws.set_column('A:A', 28, f_white); ws.set_column('B:Z', 15, f_white)
                ws.write('A1', "RESUMEN DE ANALISIS GENERAL", f_title)

                # Etiquetas Laterales (Columna A)
                ws.write(4, 0, "MES / PERIODO", f_hdr)
                ws.write(5, 0, "TRASLAPE TOTAL %", f_lbl)
                rows_cfg = [
                    ("NIVEL BAJO (%)", 7, f_v), ("VR", 8, f_val), ("P. VOL", 9, f_val),
                    ("NIVEL MEDIO (%)", 11, f_a), ("VR", 12, f_val), ("P. VOL", 13, f_val),
                    ("NIVEL ALTO (%)", 15, f_n), ("VR", 16, f_val), ("P. VOL", 17, f_val),
                    ("NIVEL CRÍTICO (%)", 19, f_r), ("VR", 20, f_val), ("P. VOL", 21, f_val),
                    ("TOTAL VRs", 23, f_lbl), ("CARGA PROM. GLOBAL", 24, f_lbl)
                ]
                for txt, r, _ in rows_cfg: ws.write(r, 0, txt, f_lbl)

                col_idx = 1
                for h in st.session_state.historico_resumen:
                    df_m = pd.DataFrame(st.session_state.analisis_cache[h['Mes']])
                    total_vrs = len(df_m) or 1
                    ws.write(4, col_idx, h['Mes'].upper(), f_hdr)
                    ws.write(5, col_idx, h['Prom']/100, f_perc)
                    
                    for n_min, n_max, rb in [(0,25,7),(25,50,11),(50,75,15),(75,100,19)]:
                        msk = (df_m['Traslape']<=25) if n_min==0 else ((df_m['Traslape']>n_min)&(df_m['Traslape']<=n_max))
                        sub = df_m[msk]; count = len(sub); pvol = sub['VOL'].mean() if count>0 else 0
                        fmt = f_v if rb==7 else f_a if rb==11 else f_n if rb==15 else f_r
                        ws.write(rb, col_idx, count/total_vrs, fmt)
                        ws.write(rb+1, col_idx, count, f_val)
                        ws.write(rb+2, col_idx, int(pvol), f_val)
                    
                    ws.write(23, col_idx, total_vrs, f_val)
                    ws.write(24, col_idx, int(df_m['VOL'].mean()), wb.add_format({'bg_color':'#DDEBF7','border':1,'align':'center'}))
                    col_idx += 1

                # --- COLUMNA TENDENCIA (SPARKINES) ---
                ws.write(4, col_idx, "TENDENCIA", f_hdr)
                lc = xlsxwriter.utility.xl_col_to_name(col_idx - 1)
                for rs in [5, 7, 11, 15, 19, 23, 24]:
                    ws.add_sparkline(rs, col_idx, {'range': f'RESUMEN!B{rs+1}:{lc}{rs+1}', 'type': 'column', 'style': 18})

                # --- LAS 3 GRÁFICAS DE TU IMAGEN ---
                # G1: TRASLAPE VS VRS
                g1 = wb.add_chart({'type': 'column'}); l1 = wb.add_chart({'type': 'line'})
                g1.add_series({'name': 'VRs', 'categories': f'=RESUMEN!$B$5:${lc}$5', 'values': f'=RESUMEN!$B$24:${lc}$24', 'fill': {'color': '#5B9BD5'}})
                l1.add_series({'name': 'Traslape %', 'values': f'=RESUMEN!$B$6:${lc}$6', 'y2_axis': True, 'line': {'color': '#C00000', 'width': 2}, 'marker': {'type': 'circle'}})
                g1.combine(l1); ws.insert_chart('B28', g1, {'x_scale': 1.1})

                # G2: MEDICION DE NIVEL
                g2 = wb.add_chart({'type': 'column', 'subtype': 'percent_stacked'})
                for n, r, c in [('Bajo',7,'#92D050'),('Medio',11,'#FFFF00'),('Alto',15,'#FFC000'),('Crítico',19,'#FF0000')]:
                    g2.add_series({'name': n, 'categories': f'=RESUMEN!$B$5:${lc}$5', 'values': f'=RESUMEN!$B${r+1}:${lc}${r+1}', 'fill': {'color': c}})
                ws.insert_chart('G28', g2, {'x_scale': 1.1})

                # G3: DILUCION DE VOLUMEN VS VRS
                g3 = wb.add_chart({'type': 'column'}); l3 = wb.add_chart({'type': 'line'})
                g3.add_series({'name': 'CARGA PROM', 'categories': f'=RESUMEN!$B$5:${lc}$5', 'values': f'=RESUMEN!$B$25:${lc}$25', 'fill': {'color': '#5B9BD5'}, 'data_labels': {'value': True}})
                l3.add_series({'name': 'TOTAL VRs', 'values': f'=RESUMEN!$B$24:${lc}$24', 'line': {'color': '#C00000'}, 'data_labels': {'value': True}})
                g3.combine(l3); ws.insert_chart('L28', g3, {'x_scale': 1.1})

                # --- PESTAÑAS DE DETALLE (SÓLO 1 VEZ) ---
                for idx_m, n_h in enumerate(st.session_state.dict_hojas.keys()):
                    df_d = pd.DataFrame(st.session_state.analisis_cache[n_h]).copy()
                    m_ant = list(st.session_state.dict_hojas.keys())[idx_m-1] if idx_m > 0 else None
                    df_p = {limpiar_texto_pro(r['Zona']): r for r in st.session_state.analisis_cache[m_ant]} if m_ant else {}
                    ws_det = wb.add_worksheet(n_h[:31]); ws_det.hide_gridlines(2)
                    ws_det.write(0, 0, f"DETALLE: {n_h.upper()}", wb.add_format({'bold':True,'font_size':14}))
                    ws_det.add_table(3, 0, len(df_d)+3, 4, {'columns': [{'header': 'VR'}, {'header': 'VOLUMEN'}, {'header': 'Δ VOL'}, {'header': '% TRASLAPE'}, {'header': 'Δ TRASLAPE'}], 'style': 'Table Style Medium 2'})
                    for ri, r in df_d.iterrows():
                        re = ri+4; zl = limpiar_texto_pro(r['Zona'])
                        ws_det.write(re, 0, r['Zona']); ws_det.write(re, 1, r['VOL'])
                        if zl in df_p:
                            dv, dt = int(r['VOL']-df_p[zl]['VOL']), round(r['Traslape']-df_p[zl]['Traslape'], 1)
                            ws_det.write(re, 2, f"▲ +{dv}.0" if dv>0 else f"▼ {abs(dv)}.0" if dv<0 else "▼ SIN CAMBIO", wb.add_format({'font_color':'#00B050' if dv>0 else '#FF0000' if dv<0 else '#000','bold':True,'align':'right'}))
                            ws_det.write(re, 4, f"▲ {dt}%" if dt>0 else f"▼ {abs(dt)}%" if dt<0 else "▼ SIN CAMBIO", wb.add_format({'font_color':'#FF0000' if dt>0 else '#00B050' if dt<0 else '#000','bold':True,'align':'right'}))
                        else: [ws_det.write(re, c, "▼ NUEVO", wb.add_format({'align':'right','bold':True})) for c in [2, 4]]
                        ws_det.write(re, 3, r['Traslape']/100, f_v if r['Traslape']<=25 else f_a if r['Traslape']<=50 else f_n if r['Traslape']<=75 else f_r)

            else: pd.DataFrame(rep_coords).to_excel(wr, sheet_name="Reporte", index=False)
            
        c_desc2.download_button(label="📊 DESCARGAR REPORTE", data=buf.getvalue(), file_name=nombre_archivo_excel, use_container_width=True)
