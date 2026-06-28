"""
Módulo de interfaz: Quinielas de Todos (transparencia).

Permite seleccionar a cualquier participante y ver su quiniela completa
comparada contra el marcador real, partido por partido, con los puntos
obtenidos. Pensado para dar transparencia al evento.
"""

import pandas as pd
import streamlit as st

from modules.firestore_db import (
    get_todos_los_usuarios,
    get_pronosticos_usuario,
    get_partidos,
)
from modules.scoring import desglose_puntos

_ORDEN_FASES = [
    "Grupos", "16avos", "Octavos", "Cuartos",
    "Semifinal", "Tercer Lugar", "Final",
]


def _pts_badge(d: dict) -> str:
    """Etiqueta textual para la columna de puntos a partir del desglose."""
    if d["exacto"]:
        base = "🎯 5 (exacto)"
    elif d["resultado"]:
        base = "✅ 3 (resultado)"
    else:
        base = "— 0"
    if d["acierto_penales"]:
        base += f"  +2 🥅 = {d['total']}"
    return base


def _nombre_penal(pen, local: str, visit: str) -> str:
    """Nombre del equipo ganador en penales según 'L'/'V'."""
    if pen == "L":
        return local
    if pen == "V":
        return visit
    return ""


def mostrar_quinielas_otros():
    """Renderiza la vista de transparencia: quiniela de un participante vs. real."""

    # ── Encabezado ────────────────────────────────────────────────────────────
    st.markdown("""
    <div style="margin-bottom: 1.5rem;">
        <h1 style="font-size: 2rem; margin-bottom: 0.2rem;">🔍 Quinielas de Todos</h1>
        <p style="color: rgba(200,230,200,0.55); margin: 0;">
            Transparencia · Mira el pronóstico de cada participante frente al marcador real
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Carga de datos ────────────────────────────────────────────────────────
    with st.spinner("Cargando datos..."):
        usuarios = get_todos_los_usuarios()
        partidos = get_partidos()

    if not usuarios:
        st.info("Aún no hay usuarios registrados.")
        return
    if not partidos:
        st.warning("No hay partidos cargados.")
        return

    # ── Selector de participante y de fase ─────────────────────────────────────
    # Mapa nombre visible → uid
    mapa_nombre_uid = {u.get("nombre", u.get("uid", "?")): u.get("uid", "") for u in usuarios}
    nombres = sorted(mapa_nombre_uid.keys())

    fases_disponibles = ["Todas"] + [
        f for f in _ORDEN_FASES if any(p.get("fase") == f for p in partidos)
    ]

    col_u, col_f = st.columns([2, 2])
    with col_u:
        nombre_sel = st.selectbox("👤 Participante", options=nombres, key="qo_user")
    with col_f:
        fase_sel = st.selectbox("📅 Fase", options=fases_disponibles, index=0, key="qo_fase")

    uid_sel = mapa_nombre_uid.get(nombre_sel, "")

    # Pronósticos del participante seleccionado
    pronos = get_pronosticos_usuario(uid_sel)

    # ── Construir filas (partido por partido) ──────────────────────────────────
    partidos_orden = sorted(partidos, key=lambda x: x.get("fecha", ""))
    if fase_sel != "Todas":
        partidos_orden = [p for p in partidos_orden if p.get("fase") == fase_sel]

    filas = []
    pts_total = exactos = parciales = jugados = sin_pronostico = 0
    acum = 0   # puntos acumulados en orden cronológico

    for p in partidos_orden:
        pid   = p["id"]
        local = p.get("equipo_local", "Por definir")
        visit = p.get("equipo_visitante", "Por definir")
        real  = p.get("marcador_real", {}) or {}
        prono = pronos.get(pid)

        hay_real  = real.get("local") is not None
        hay_prono = bool(prono)

        d = desglose_puntos(prono or {}, real, p.get("fase"))
        pts = d["total"]

        prono_str = f"{int(prono['local'])} - {int(prono['visitante'])}" if hay_prono else "— sin pronóstico"
        real_str  = f"{int(real['local'])} - {int(real['visitante'])}" if hay_real else "Pendiente"

        # Anexar el ganador de penales (solo eliminatoria + empate)
        if hay_prono and prono.get("penales"):
            prono_str += f"  🥅 {_nombre_penal(prono.get('penales'), local, visit)}"
        if hay_real and real.get("penales"):
            real_str += f"  🥅 {_nombre_penal(real.get('penales'), local, visit)}"

        if hay_real:
            jugados += 1
            pts_total += pts
            acum += pts
            if d["exacto"]:
                exactos += 1
            elif d["resultado"]:
                parciales += 1
        if not hay_prono:
            sin_pronostico += 1

        filas.append({
            "📅 Fecha":      p.get("fecha", "")[:10],
            "Fase":          p.get("fase", ""),
            "⚽ Partido":    f"{local}  vs  {visit}",
            "🔮 Pronóstico": prono_str,
            "⚽ Real":       real_str,
            "🏆 Puntos":     _pts_badge(d) if hay_real else "—",
            "🧮 Acumulado":  acum,
            "_pts":          d["base"] if hay_real else -1,   # color por marcador; -1 = pendiente
        })

    # ── Métricas de resumen del participante ───────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🏆 Puntos", pts_total)
    m2.metric("🎯 Exactos (5)", exactos)
    m3.metric("✅ Parciales (3)", parciales)
    m4.metric("⚽ Jugados", jugados)

    st.markdown("<br>", unsafe_allow_html=True)

    if not filas:
        st.info("No hay partidos para mostrar en esta selección.")
        return

    # ── Tabla comparativa con filas resaltadas ─────────────────────────────────
    df = pd.DataFrame(filas)
    df.index += 1
    df.index.name = "#"

    def _estilo_fila(row):
        """Verde fuerte = exacto (5), verde tenue = resultado (3), sin color el resto."""
        pts = row["_pts"]
        if pts == 5:
            css = "background-color: rgba(76,175,80,0.40); color: #EAFBEA;"
        elif pts == 3:
            css = "background-color: rgba(76,175,80,0.14); color: #E8F5E9;"
        else:
            css = ""
        return [css] * len(row)

    styler = df.style.apply(_estilo_fila, axis=1)

    st.dataframe(
        styler,
        use_container_width=True,
        column_order=[
            "📅 Fecha", "Fase", "⚽ Partido",
            "🔮 Pronóstico", "⚽ Real", "🏆 Puntos", "🧮 Acumulado",
        ],
        column_config={
            "📅 Fecha":      st.column_config.TextColumn("📅 Fecha", width="small"),
            "Fase":          st.column_config.TextColumn("Fase", width="small"),
            "⚽ Partido":    st.column_config.TextColumn("⚽ Partido", width="large"),
            "🔮 Pronóstico": st.column_config.TextColumn("🔮 Pronóstico", width="small"),
            "⚽ Real":       st.column_config.TextColumn("⚽ Real", width="small"),
            "🏆 Puntos":     st.column_config.TextColumn("🏆 Puntos", width="medium"),
            "🧮 Acumulado":  st.column_config.NumberColumn("🧮 Acumulado", width="small", format="%d"),
        },
    )

    st.caption(
        f"Mostrando **{len(filas)}** partidos · "
        f"{sin_pronostico} sin pronóstico de {nombre_sel}."
    )

    # ── Refresco manual ────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Actualizar", key="qo_refresh"):
        get_pronosticos_usuario.clear()
        get_partidos.clear()
        get_todos_los_usuarios.clear()
        st.rerun()
