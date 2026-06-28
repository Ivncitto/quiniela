"""
Módulo de interfaz: Tabla General de Ranking.
Muestra el ranking de todos los familiares ordenado por puntos totales.
"""

import streamlit as st
from modules.firestore_db import get_todos_los_usuarios, get_todos_pronosticos, get_partidos
from modules.scoring import calcular_ranking
from modules.horario import partidos_de_hoy, estado_partido, kickoff_local


# ── Estilos de cada estado del partido del día ────────────────────────────────
_ESTADOS = {
    "FINAL":     ("Final",        "#66BB6A", "rgba(76,175,80,0.12)"),
    "EN_JUEGO":  ("● En juego",   "#FFD54F", "rgba(255,193,7,0.12)"),
    "PROXIMO":   ("Próximo",      "rgba(200,230,200,0.55)", "rgba(255,255,255,0.04)"),
    "PENDIENTE": ("Por capturar", "#FFAB91", "rgba(255,112,67,0.10)"),
    "SIN_FECHA": ("—",            "rgba(200,230,200,0.4)", "rgba(255,255,255,0.04)"),
}


def _panel_partidos_hoy(partidos: list[dict]) -> None:
    """Muestra los partidos de HOY con su marcador y estado (sin consultar APIs)."""
    de_hoy = partidos_de_hoy(partidos)
    if not de_hoy:
        return  # No hay partidos hoy: no mostramos el bloque.

    st.markdown(
        '<h3 style="margin:0 0 0.6rem;">📅 Partidos de hoy</h3>',
        unsafe_allow_html=True,
    )

    for p in de_hoy:
        estado = estado_partido(p)
        etiqueta, color, bg = _ESTADOS.get(estado, _ESTADOS["SIN_FECHA"])

        kickoff = kickoff_local(p)
        hora = kickoff.strftime("%H:%M") if kickoff else "--:--"

        e_local = p.get("equipo_local", "Por definir")
        e_vis   = p.get("equipo_visitante", "Por definir")

        mr = p.get("marcador_real", {})
        if mr.get("local") is not None:
            centro = f'{int(mr["local"])} <span style="opacity:.45;">–</span> {int(mr["visitante"])}'
        else:
            centro = '<span style="opacity:.4;">vs</span>'

        st.markdown(
            f'''
            <div style="display:flex; align-items:center; gap:8px;
                        background:{bg}; border:1px solid rgba(76,175,80,0.15);
                        border-radius:10px; padding:0.45rem 0.7rem; margin-bottom:0.4rem;">
                <div style="width:48px; font-size:0.8rem; color:rgba(200,230,200,0.6);
                            font-weight:600;">{hora}</div>
                <div style="flex:1; text-align:right; font-weight:600;
                            font-size:0.92rem;">{e_local}</div>
                <div style="min-width:54px; text-align:center; font-weight:800;
                            font-size:1.05rem; color:#E8F5E9;">{centro}</div>
                <div style="flex:1; text-align:left; font-weight:600;
                            font-size:0.92rem;">{e_vis}</div>
                <div style="width:96px; text-align:right; font-size:0.72rem;
                            font-weight:700; color:{color};">{etiqueta}</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )

    st.divider()


def mostrar_tabla_general():
    """Renderiza la tabla general de ranking con métricas de resumen."""

    # ── Encabezado ────────────────────────────────────────────────────────────
    st.markdown("""
    <div style="margin-bottom: 1.5rem;">
        <h1 style="font-size: 2rem; margin-bottom: 0.2rem;">🏆 Tabla General</h1>
        <p style="color: rgba(200,230,200,0.55); margin: 0;">
            Ranking total del torneo · Actualizado cada 60 segundos
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Carga de datos ────────────────────────────────────────────────────────
    with st.spinner("Cargando ranking..."):
        usuarios    = get_todos_los_usuarios()
        pronosticos = get_todos_pronosticos()
        partidos    = get_partidos()

    # ── Partidos de hoy (lee la BD, sin consultar APIs) ───────────────────────
    _panel_partidos_hoy(partidos)

    if not usuarios:
        st.info("Aún no hay usuarios registrados en el torneo.")
        return

    # ── Calcular ranking ──────────────────────────────────────────────────────
    df = calcular_ranking(usuarios, pronosticos, partidos)

    # ── Métricas de resumen ───────────────────────────────────────────────────
    partidos_con_resultado = sum(
        1 for p in partidos
        if p.get("marcador_real", {}).get("local") is not None
    )
    total_partidos = len(partidos)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("👥 Participantes", len(usuarios))
    with col2:
        st.metric("⚽ Partidos Jugados", f"{partidos_con_resultado} / {total_partidos}")
    with col3:
        lider = df["Nombre"].iloc[0] if not df.empty else "—"
        st.metric("🥇 Líder Actual", lider)
    with col4:
        pts_lider = int(df["Puntos"].iloc[0]) if not df.empty else 0
        st.metric("⭐ Puntos del Líder", pts_lider)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabla de ranking ──────────────────────────────────────────────────────
    if df.empty:
        st.warning("No hay datos de pronósticos aún.")
        return

    # Mostrar con estilo usando st.dataframe
    df_display = df.drop(columns=["uid"], errors="ignore")

    st.dataframe(
        df_display,
        use_container_width=True,
        column_config={
            "Nombre":        st.column_config.TextColumn("👤 Nombre",         width="medium"),
            "Puntos":        st.column_config.NumberColumn("🏆 Puntos Totales", width="small", format="%d"),
            "🎯 Exactos":    st.column_config.NumberColumn("🎯 Exactos (5pts)", width="small", format="%d"),
            "✅ Parciales":  st.column_config.NumberColumn("✅ Parciales (3pts)", width="small", format="%d"),
            "🥅 Penales":    st.column_config.NumberColumn("🥅 Penales (+2)",   width="small", format="%d"),
            "⚽ Jugados":    st.column_config.NumberColumn("⚽ Jugados",         width="small", format="%d"),
        },
        hide_index=False,
    )

    # ── Podio visual ──────────────────────────────────────────────────────────
    if len(df) >= 3:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🥇 Podio")

        medallas = ["🥇", "🥈", "🥉"]
        colores  = ["#FFD700", "#C0C0C0", "#CD7F32"]
        col_a, col_b, col_c = st.columns(3)

        for i, (col, medalla, color) in enumerate(zip([col_a, col_b, col_c], medallas, colores)):
            with col:
                row = df.iloc[i]
                st.markdown(f"""
                <div style="
                    text-align: center;
                    padding: 1.5rem 1rem;
                    background: rgba(255,255,255,0.04);
                    border: 1px solid {color}44;
                    border-radius: 14px;
                    transition: all 0.3s;
                ">
                    <div style="font-size: 2.5rem;">{medalla}</div>
                    <div style="font-weight: 700; font-size: 1.1rem; color: {color};">
                        {row['Nombre']}
                    </div>
                    <div style="font-size: 2rem; font-weight: 900; color: {color};">
                        {int(row['Puntos'])} pts
                    </div>
                    <div style="color: rgba(200,230,200,0.5); font-size: 0.85rem;">
                        {int(row['🎯 Exactos'])} exactos · {int(row['✅ Parciales'])} parciales
                    </div>
                </div>
                """, unsafe_allow_html=True)

    # ── Botón de actualización manual ─────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Actualizar Ranking", key="btn_refresh_general"):
        get_todos_pronosticos.clear()
        get_partidos.clear()
        get_todos_los_usuarios.clear()
        st.rerun()
