"""
Módulo de interfaz: Tabla General de Ranking.
Muestra el ranking de todos los familiares ordenado por puntos totales.
"""

import streamlit as st
from modules.firestore_db import get_todos_los_usuarios, get_todos_pronosticos, get_partidos
from modules.scoring import calcular_ranking


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
