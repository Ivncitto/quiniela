"""
Módulo de interfaz: Puntos por Grupos.
Muestra el ranking filtrado solo para la Fase de Grupos del torneo.
"""

import streamlit as st
from modules.firestore_db import get_todos_los_usuarios, get_todos_pronosticos, get_partidos
from modules.scoring import calcular_ranking_fase, calcular_ranking


_ORDEN_FASES = [
    "Grupos",
    "16avos",
    "Octavos",
    "Cuartos",
    "Semifinal",
    "Tercer Lugar",
    "Final",
]


def mostrar_puntos_grupos():
    """
    Renderiza el desglose de puntos por fase del torneo.
    Por defecto muestra la Fase de Grupos, con selector para otras fases.
    """

    # ── Encabezado ────────────────────────────────────────────────────────────
    st.markdown("""
    <div style="margin-bottom: 1.5rem;">
        <h1 style="font-size: 2rem; margin-bottom: 0.2rem;">📊 Puntos por Fase</h1>
        <p style="color: rgba(200,230,200,0.55); margin: 0;">
            Desglose del rendimiento por etapa del torneo
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Carga de datos ────────────────────────────────────────────────────────
    with st.spinner("Cargando datos..."):
        usuarios    = get_todos_los_usuarios()
        pronosticos = get_todos_pronosticos()
        partidos    = get_partidos()

    if not usuarios:
        st.info("Aún no hay usuarios registrados.")
        return

    # Detectar qué fases existen en los partidos cargados
    fases_disponibles = sorted(
        list({p.get("fase", "") for p in partidos if p.get("fase")}),
        key=lambda f: _ORDEN_FASES.index(f) if f in _ORDEN_FASES else 99,
    )

    if not fases_disponibles:
        st.warning("No se encontraron partidos en Firestore.")
        return

    # ── Selector de fase ──────────────────────────────────────────────────────
    col_sel, col_info = st.columns([2, 3])
    with col_sel:
        fase_seleccionada = st.selectbox(
            "📅 Seleccionar Fase",
            options=fases_disponibles,
            index=0,
            key="selector_fase_puntos",
        )

    # ── Estadísticas de la fase ───────────────────────────────────────────────
    partidos_fase = [p for p in partidos if p.get("fase") == fase_seleccionada]
    jugados_fase  = sum(
        1 for p in partidos_fase
        if p.get("marcador_real", {}).get("local") is not None
    )

    with col_info:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="padding: 0.6rem 1rem; background: rgba(76,175,80,0.08);
                    border-left: 3px solid #4CAF50; border-radius: 6px;">
            <span style="color: #81C784; font-weight: 600;">
                {fase_seleccionada}
            </span>
            &nbsp;·&nbsp;
            <span style="color: rgba(200,230,200,0.6);">
                {jugados_fase} / {len(partidos_fase)} partidos jugados
            </span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Calcular y mostrar ranking de la fase ─────────────────────────────────
    df_fase = calcular_ranking_fase(usuarios, pronosticos, partidos, fase_seleccionada)

    if df_fase.empty:
        st.info(f"Sin datos de pronósticos para la fase: **{fase_seleccionada}**.")
        return

    df_display = df_fase.drop(columns=["uid"], errors="ignore")

    st.dataframe(
        df_display,
        use_container_width=True,
        column_config={
            "Nombre":       st.column_config.TextColumn("👤 Nombre",            width="medium"),
            "Puntos":       st.column_config.NumberColumn("🏆 Puntos en Fase",   width="small", format="%d"),
            "🎯 Exactos":   st.column_config.NumberColumn("🎯 Exactos (5pts)",   width="small", format="%d"),
            "✅ Parciales": st.column_config.NumberColumn("✅ Parciales (3pts)", width="small", format="%d"),
            "🥅 Penales":   st.column_config.NumberColumn("🥅 Penales (+2)",     width="small", format="%d"),
            "⚽ Jugados":   st.column_config.NumberColumn("⚽ Jugados",           width="small", format="%d"),
        },
        hide_index=False,
    )

    # ── Comparativa entre fases ───────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📈 Comparativa entre Fases")
    st.caption("Puntos acumulados por cada participante en cada fase del torneo.")

    # Construir tabla comparativa
    filas_comp = {u["nombre"]: {} for u in usuarios}

    for fase in fases_disponibles:
        df_f = calcular_ranking_fase(usuarios, pronosticos, partidos, fase)
        if df_f.empty:
            continue
        for _, row in df_f.iterrows():
            nombre = row["Nombre"]
            if nombre in filas_comp:
                filas_comp[nombre][fase] = int(row["Puntos"])

    import pandas as pd
    df_comp = pd.DataFrame.from_dict(filas_comp, orient="index")
    df_comp.index.name = "Familiar"

    # Agregar columna de total
    if not df_comp.empty:
        df_comp["TOTAL"] = df_comp.sum(axis=1)
        df_comp = df_comp.sort_values("TOTAL", ascending=False)

        # Ordenar columnas en el orden correcto del torneo
        cols_ordenadas = [f for f in _ORDEN_FASES if f in df_comp.columns]
        if "TOTAL" in df_comp.columns:
            cols_ordenadas.append("TOTAL")
        df_comp = df_comp[cols_ordenadas]

        st.dataframe(df_comp, use_container_width=True)
    else:
        st.info("No hay suficientes datos para la comparativa aún.")

    # ── Botón de refresco ─────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Actualizar Datos", key="btn_refresh_fases"):
        get_todos_pronosticos.clear()
        get_partidos.clear()
        st.rerun()
