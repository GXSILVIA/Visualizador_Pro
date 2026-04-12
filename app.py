#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

#-*- coding: utf-8 -*-
# Copyright 2026 Silvia Guadalupe Garcia Espinosa

import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap
import geopandas as gpd
import os
import io
import yaml
import time
import numpy as np
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_folium import st_folium


# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Pro AMZL", layout="wide")

if 'dict_datos' not in st.session_state: st.session_state.dict_datos = {}
if 'zona_seleccionada' not in st.session_state: st.session_state.zona_seleccionada = None
if 'reproduciendo' not in st.session_state: st.session_state.reproduciendo = False
if 'fec_slider_idx' not in st.session_state: st.session_state.fec_slider_idx = 0

def area_interseccion(r1, r2, d):
    if d >= r1 + r2: return 0.0
    if d <= abs(r1 - r2): return np.pi * min(r1, r2)**2
    p1 = r1**2 * np.arccos(np.clip((d**2 + r1**2 - r2**2) / (2 * d * r1), -1, 1))
    p2 = r2**2 * np.arccos(np.clip((d**2 + r2**2 - r1**2) / (2 * d * r2), -1, 1))
    p3 = 0.5 * np.sqrt(max(0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return p1 + p2 - p3

@st.cache_data
def cargar_capa_estado(archivo):
    ruta = f"mapas/{archivo}"
    if os.path.exists(ruta):
        gdf = gpd.read_file(ruta).to_crs("EPSG:4326")
        gdf['geometry'] = gdf['geometry'].simplify(0.002)
        col_geo = next((p for p in ['d_cp', 'CP', 'CODIGOPOSTAL', 'ZONA'] if p in gdf.columns), gdf.columns[0])
        return gdf, col_geo
    return None, None

# --- 2. SEGURIDAD ---
try:
    with open('config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
    name, auth_status, username = authenticator.login(location='main')
except: st.error("Error en config.yaml"); st.stop()

if auth_status:
    def normalizar_df(df, modo_ref):
        df.columns = df.columns.str.strip().str.upper()
        mapa = {'LAT':['LAT','LATITUD'],'LON':['LON','LONGITUD'],'VOL':['VOL','VOLUMEN'],'RAD':['RADIO','RAD'],'CP':['CP','C.P.'],'NOM':['NOMBRE','ZONA'],'PER':['PERSONA','RESPONSABLE'], 'FEC':['FECHA','DATE']}
        rename_dict = {c: k for k, v in mapa.items() for c in df.columns if c in v}
        df = df.rename(columns=rename_dict)
        for c in ['LAT', 'LON', 'VOL']: df[c] = pd.to_numeric(df.get(c, 0), errors='coerce').fillna(0)
        df['RAD'] = pd.to_numeric(df.get('RAD', 750), errors='coerce').fillna(750)
        if 'FEC' in df.columns: df['FEC'] = pd.to_datetime(df['FEC'], errors='coerce')
        df['CP'] = df.get('CP', '0').astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
        if 'NOM' not in df.columns: df['NOM'] = df['CP']
        if 'PER' not in df.columns: df['PER'] = "N/A"
        lim = [100, 200, 300, 400] if "Polígonos" in modo_ref else [15, 20, 30, 40]
        df['RANGO_ID'] = df['VOL'].apply(lambda v: next((i for i, l in enumerate(lim, 1) if v <= l), 5) if v > 0 else 0)
        df['COORD_KEY'] = df['LAT'].round(4).astype(str) + "," + df['LON'].round(4).astype(str)
        return df

    # --- 3. UI SUPERIOR ---
    col_mapa, col_panel = st.columns([3, 1.3])
    with col_panel:
        st.title("🛡️ Panel AMZL")
        authenticator.logout('Cerrar Sesión', 'sidebar')
        buf_p = io.BytesIO()
        with pd.ExcelWriter(buf_p, engine='openpyxl') as writer:
            pd.DataFrame(columns=['LAT', 'LON', 'VOL', 'RAD', 'CP', 'NOMBRE', 'RESPONSABLE', 'FECHA']).to_excel(writer, index=False)
        st.download_button("📥 Plantilla", data=buf_p.getvalue(), file_name="plantilla_amzl.xlsx", use_container_width=True)
        modo = st.radio("Capa Principal", ["Coordenadas", "Polígonos CP"])
        archivo_excel = st.file_uploader("📂 Cargar Datos", type=["xlsx"])
        if archivo_excel and st.button("🔄 Procesar"):
            xl = pd.ExcelFile(archivo_excel)
            st.session_state.dict_datos = {p: normalizar_df(xl.parse(p), modo) for p in xl.sheet_names}
            st.session_state.fec_slider_idx = 0; st.rerun()

        if st.session_state.dict_datos:
            fecha_sel = st.select_slider("🕒 Periodo:", options=list(st.session_state.dict_datos.keys()))
            df_act = st.session_state.dict_datos[fecha_sel]
            if 'FEC' in df_act.columns and not df_act['FEC'].dropna().empty:
                if st.toggle("🕒 Modo Tiempo"):
                    lista_fec = sorted(df_act['FEC'].dropna().unique())
                    c_p1, c_p2 = st.columns(2)
                    if c_p1.button("▶️ Play/Stop"): st.session_state.reproduciendo = not st.session_state.reproduciendo
                    f_idx = st.session_state.fec_slider_idx
                    fec_actual = c_p2.select_slider("Fecha", options=lista_fec, value=lista_fec[f_idx], format_func=lambda x: x.strftime('%d/%m'))
                    if st.session_state.reproduciendo and f_idx < len(lista_fec)-1:
                        st.session_state.fec_slider_idx += 1; time.sleep(0.3); st.rerun()
                    else: st.session_state.reproduciendo = False
                    df_act = df_act[df_act['FEC'] <= fec_actual]
            modo_analisis = st.toggle("🔍 Análisis Total", value=False)
            lbls = ["⚪ R0", "🟡 R1-100", "🟠 R101-200", "🔴 R201-300", "🏮 R301-400", "🍷 R401+"] if "Polígonos" in modo else ["⚪ R0", "🟡 R1-15", "🟠 R16-20", "🔴 R21-30", "🏮 R31-40", "🍷 R41+"]
            activos = [i for i, l in enumerate(lbls) if st.sidebar.checkbox(l, value=True, key=f"c_{i}")] if False else [0,1,2,3,4,5]
            ver_nombres = st.toggle("🏷️ Nombres", value=True)
            archivo_sel = st.selectbox("GeoJSON", sorted([f for f in os.listdir('mapas') if f.endswith('.geojson')])) if "Polígonos" in modo else None

    # --- 4. MAPA ---
    with col_mapa:
        if st.session_state.dict_datos:
            df_m = df_act[(df_act['LAT'] != 0) & (df_act['LON'] != 0)].copy()
            center = [df_m['LAT'].mean(), df_m['LON'].mean()] if not df_m.empty else [19.4, -99.1]
            m = folium.Map(location=center, zoom_start=12, tiles="CartoDB Voyager")
            if not df_m.empty:
                COLORS = {0:"#FFF", 1:"#FF0", 2:"#F90", 3:"#F44", 4:"#F00", 5:"#600"}
                if "Polígonos" in modo and archivo_sel:
                    gdf, col_geo = cargar_capa_estado(archivo_sel)
                    if gdf is not None:
                        merged = gdf.merge(df_m, left_on=col_geo, right_on='CP')
                        for _, f in merged.iterrows():
                            folium.GeoJson(f['geometry'], style_function=lambda x, c=COLORS.get(f['RANGO_ID'],"#888"): {'fillColor':c, 'color':'#444', 'fillOpacity':0.5, 'weight':1}).add_to(m)
                else:
                    for _, f in df_m.drop_duplicates('COORD_KEY').iterrows():
                        c = COLORS.get(f['RANGO_ID'], "#888")
                        folium.Circle([f['LAT'], f['LON']], radius=f['RAD'], color=c, fill=True, fill_opacity=0.3, tooltip=f"Vol: {f['VOL']}").add_to(m)
                        if ver_nombres:
                            folium.Marker([f['LAT'], f['LON']], icon=folium.features.DivIcon(html=f'<div style="font-size:8pt; font-weight:bold; color:black; text-shadow: -1px -1px 0 #fff, 1px -1px 0 #fff, -1px 1px 0 #fff, 1px 1px 0 #fff; width:150px;">{f["PER"]}</div>')).add_to(m)
                # PROTECCIÓN FIT_BOUNDS: Solo si hay área real (puntos distintos)
                if df_m['LAT'].nunique() > 1 and df_m['LON'].nunique() > 1:
                    m.fit_bounds([[df_m['LAT'].min(), df_m['LON'].min()], [df_m['LAT'].max(), df_m['LON'].max()]])
            map_out = st_folium(m, width="100%", height=450, key=f"m_{fecha_sel}")
            if map_out.get('last_object_clicked'):
                lc = map_out['last_object_clicked']
                df_act['d_t'] = ((df_act['LAT']-lc['lat'])**2 + (df_act['LON']-lc['lng'])**2)**0.5
                st.session_state.zona_seleccionada = df_act.nsmallest(1, 'd_t')['COORD_KEY'].iloc[0]; st.rerun()

    # --- 5. INFORME (PEGADO ABAJO) ---
    if st.session_state.dict_datos:
        if st.session_state.zona_seleccionada:
            sel = df_act[df_act['COORD_KEY'] == st.session_state.zona_seleccionada]
            if not sel.empty:
                m_r = sel.iloc[0]
                df_c = (df_act if modo_analisis else df_m).copy()
                df_c['dist_m'] = (((df_c['LAT'] - m_r['LAT'])**2 + (df_c['LON'] - m_r['LON'])**2)**0.5) * 111139
                df_c['%_ENCIMADO'] = df_c.apply(lambda r: (area_interseccion(m_r['RAD'], r['RAD'], r['dist_m']) / (np.pi * min(m_r['RAD'], r['RAD'])**2)) * 100, axis=1)
                df_rep = df_c[df_c['%_ENCIMADO'] >= 30].sort_values('%_ENCIMADO', ascending=False)
                st.subheader(f"📊 Análisis: {m_r['NOM']}")
                r1, r2 = st.columns(2)
                with r1:
                    st.bar_chart(df_rep.groupby('PER')['VOL'].sum())
                    if st.button("🗑️ Limpiar"): st.session_state.zona_seleccionada = None; st.rerun()
                with r2:
                    def est(v): return 'background-color: #721c24; color: white' if v >= 99 else ('background-color: #ff4b4b' if v >= 80 else ('background-color: #ffa500' if v >= 50 else 'background-color: #f1c40f'))
                    # Añadida columna FECHA al reporte
                    cols_rep = ['NOM', 'PER', 'VOL', '%_ENCIMADO']
                    if 'FEC' in df_rep.columns: cols_rep.insert(2, 'FEC')
                    st.dataframe(df_rep[cols_rep].style.applymap(est, subset=['%_ENCIMADO']).format({'%_ENCIMADO': '{:.1f}%'}), use_container_width=True)
        elif 'lista_fec' in locals() and st.session_state.fec_slider_idx == len(lista_fec)-1:
            st.success(f"📈 Resumen Final: {int(df_act['VOL'].sum())} Vol | {df_act['PER'].nunique()} Responsables")
            st.line_chart(df_act.groupby('FEC')['VOL'].sum())

elif auth_status is False: st.error('Credenciales incorrectas')
elif auth_status is None: st.warning('Ingrese credenciales')
