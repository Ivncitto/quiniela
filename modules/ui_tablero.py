"""
ui_tablero.py — Mi Quiniela personal.

Muestra los partidos en pestañas por fase:
  Grupos | 16avos | Octavos | Cuartos | Semifinal | Tercer Lugar | Final

Cada partido en formato compacto:
  📅 fecha · ciudad
  [Equipo Local]  [ GOL ] — [ GOL ]  [Equipo Visitante]   [💾 Guardar / 🔒]
"""

import streamlit as st
from datetime import datetime

from modules.firestore_db import (
    get_partidos,
    get_pronosticos_usuario,
    guardar_pronosticos_batch,
)
from modules.horario import esta_cerrado, formatear_fecha_local, fase_en_curso
from modules.scoring import es_eliminatoria


def _excluir_penal(este: str, otro: str) -> None:
    """Callback: al marcar un equipo como ganador de penales, desmarca el otro."""
    if st.session_state.get(este):
        st.session_state[otro] = False

_ORDEN_FASES = [
    "Grupos", "16avos", "Octavos", "Cuartos",
    "Semifinal", "Tercer Lugar", "Final",
]

_CSS = """
<style>
    /* Tarjeta de partido */
    .match-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(76,175,80,0.15);
        border-radius: 12px;
        padding: 0.55rem 0.75rem 0.45rem;
        margin-bottom: 0.5rem;
        transition: border-color 0.2s;
    }
    .match-card:hover { border-color: rgba(76,175,80,0.35); }
    .match-card.locked {
        border-color: rgba(239,83,80,0.2);
        background: rgba(239,83,80,0.025);
    }
    .match-card.saved {
        border-color: rgba(76,175,80,0.4);
        background: rgba(76,175,80,0.04);
    }
    /* Info de fecha/sede */
    .match-meta {
        font-size: 0.72rem;
        color: rgba(200,230,200,0.45);
        margin-bottom: 0.3rem;
        line-height: 1.4;
    }
    /* Badge jornada */
    .badge-jornada {
        display: inline-block;
        background: rgba(46,125,50,0.3);
        border: 1px solid rgba(76,175,80,0.3);
        border-radius: 20px;
        padding: 2px 10px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #81C784;
        margin-bottom: 0.6rem;
    }
    /* Nombre de equipo alineado */
    .team-name-left  { text-align: right;  font-weight: 600; padding-top: 0.4rem; font-size: 0.95rem; }
    .team-name-right { text-align: left;   font-weight: 600; padding-top: 0.4rem; font-size: 0.95rem; }
    .vs-sep          { text-align: center; font-weight: 800; padding-top: 0.35rem; color: rgba(200,230,200,0.3); }
    /* Sin pronóstico badge */
    .badge-sin {
        font-size: 0.68rem; color: rgba(200,230,200,0.35);
        font-style: italic;
    }
    .badge-ok {
        font-size: 0.68rem; color: #66BB6A;
    }
    /* Divisor de jornada */
    .jornada-sep {
        border: none;
        border-top: 1px dashed rgba(76,175,80,0.2);
        margin: 1rem 0 0.6rem;
    }
</style>
"""


def _fmt_fecha(fecha_iso: str) -> str:
    """Formatea fecha ISO (UTC) a hora local de México: 'Lun 11 Jun · 13:00'."""
    return formatear_fecha_local(fecha_iso)


def _partido_card(partido: dict, uid: str, mis_pronosticos: dict) -> None:
    """Renderiza la tarjeta de un partido con inputs de pronóstico."""
    pid          = partido["id"]
    e_local      = partido.get("equipo_local",     "Por definir")
    e_visitante  = partido.get("equipo_visitante",  "Por definir")
    # Cerrado = bloqueo manual del admin O ya llegó la hora de inicio.
    bloqueado    = esta_cerrado(partido)
    fecha_iso    = partido.get("fecha",              "")
    ciudad       = partido.get("ciudad",             "")
    estadio      = partido.get("estadio",            "")

    pronostico  = mis_pronosticos.get(pid, {})
    hay_prono   = bool(pronostico)
    mi_local    = int(pronostico.get("local",     0)) if hay_prono else None
    mi_visitante= int(pronostico.get("visitante", 0)) if hay_prono else None
    mi_penales  = pronostico.get("penales")  # "L" / "V" / None
    es_elim     = es_eliminatoria(partido.get("fase"))

    # Clase CSS de la tarjeta
    clase = "match-card"
    if bloqueado:
        clase += " locked"
    elif hay_prono:
        clase += " saved"

    # ── Info de fecha / sede ───────────────────────────────────────────────────
    info_partes = []
    if fecha_iso:
        info_partes.append(f"📅 {_fmt_fecha(fecha_iso)}")
    if ciudad:
        info_partes.append(f"📍 {ciudad}")
    if estadio:
        info_partes.append(f"🏟 {estadio}")

    estado_html = (
        '<span style="color:#EF5350; font-size:0.7rem; font-weight:600;">🔒 CERRADO</span>'
        if bloqueado else
        '<span style="color:#66BB6A; font-size:0.7rem; font-weight:600;">🔓 ABIERTO</span>'
    )

    info_html = "  ·  ".join(info_partes) if info_partes else ""

    st.markdown(
        f'<div class="{clase}">'
        f'<div class="match-meta">{estado_html}{'  &nbsp;&nbsp;' + info_html if info_html else ""}</div>',
        unsafe_allow_html=True,
    )

    # ── Fila de inputs ─────────────────────────────────────────────────────────
    c_tl, c_sl, c_sep, c_sv, c_tv, c_btn = st.columns([2.5, 0.7, 0.25, 0.7, 2.5, 1.4])

    with c_tl:
        st.markdown(f'<div class="team-name-left">{e_local}</div>', unsafe_allow_html=True)
    with c_sl:
        val_l = st.number_input(
            "gol_local", value=mi_local, min_value=0, max_value=30,
            key=f"tb_sl_{pid}", label_visibility="collapsed",
            disabled=bloqueado, placeholder="0",
        )
    with c_sep:
        st.markdown('<div class="vs-sep">—</div>', unsafe_allow_html=True)
    with c_sv:
        val_v = st.number_input(
            "gol_vis", value=mi_visitante, min_value=0, max_value=30,
            key=f"tb_sv_{pid}", label_visibility="collapsed",
            disabled=bloqueado, placeholder="0",
        )
    with c_tv:
        st.markdown(f'<div class="team-name-right">{e_visitante}</div>', unsafe_allow_html=True)
    with c_btn:
        # Sin botón individual: solo indicador de estado.
        # El guardado se hace con el botón "Guardar TODOS" de la página.
        if bloqueado:
            badge = '<span class="badge-ok">✅ Guardado</span>' if hay_prono else '<span class="badge-sin">Sin pronóstico</span>'
        elif hay_prono:
            badge = '<span class="badge-ok">✅ Guardado</span>'
        else:
            badge = '<span class="badge-sin">✏️ Sin guardar</span>'
        st.markdown(
            f'<div style="padding-top:0.4rem; text-align:center;">{badge}</div>',
            unsafe_allow_html=True,
        )

    # ── Penales: solo eliminatorias y solo si el pronóstico es EMPATE ──────────
    if es_elim:
        # Leer el marcador ACTUAL de los widgets (ya instanciados arriba).
        cur_l = st.session_state.get(f"tb_sl_{pid}", mi_local)
        cur_v = st.session_state.get(f"tb_sv_{pid}", mi_visitante)
        es_empate = (cur_l is not None and cur_v is not None and int(cur_l) == int(cur_v))

        if es_empate:
            kL, kV = f"tb_penL_{pid}", f"tb_penV_{pid}"
            # Inicializar estado desde el pronóstico guardado (solo la 1ª vez).
            if kL not in st.session_state:
                st.session_state[kL] = (mi_penales == "L")
            if kV not in st.session_state:
                st.session_state[kV] = (mi_penales == "V")

            st.markdown(
                '<div style="font-size:0.72rem; color:#FFD54F; margin:0.1rem 0 0.15rem;">'
                '🥅 ¿Quién gana en PENALES? (+2 pts extra · opcional)</div>',
                unsafe_allow_html=True,
            )
            cp1, cp2 = st.columns(2)
            with cp1:
                st.checkbox(
                    e_local, key=kL, disabled=bloqueado,
                    on_change=_excluir_penal, args=(kL, kV),
                )
            with cp2:
                st.checkbox(
                    e_visitante, key=kV, disabled=bloqueado,
                    on_change=_excluir_penal, args=(kV, kL),
                )

    st.markdown('</div>', unsafe_allow_html=True)


def _tab_grupos(partidos: list[dict], uid: str, mis_pronosticos: dict) -> None:
    """Renderiza el tab de Fase de Grupos organizado por Grupo (A, B, C…)."""
    ps_grupos = [p for p in partidos if p.get("fase") == "Grupos"]

    if not ps_grupos:
        st.info("No hay partidos de Grupos cargados.")
        return

    grupos = sorted({p.get("grupo", "") for p in ps_grupos if p.get("grupo")})

    # Sin campo 'grupo': mostrar todos ordenados por fecha (fallback)
    if not grupos:
        for partido in sorted(ps_grupos, key=lambda x: x.get("fecha", "")):
            _partido_card(partido, uid, mis_pronosticos)
        return

    # Agrupar por Grupo
    for grupo in grupos:
        ps_grupo = sorted(
            [p for p in ps_grupos if p.get("grupo") == grupo],
            key=lambda x: x.get("fecha", ""),
        )

        # Calcular progreso de pronósticos en este grupo
        con_prono = sum(1 for p in ps_grupo if p["id"] in mis_pronosticos)
        total_g   = len(ps_grupo)

        with st.expander(
            f"📌 Grupo {grupo}  —  {total_g} partidos  |  "
            f"✅ {con_prono} pronosticados  ·  ⏳ {total_g - con_prono} pendientes",
            expanded=(grupo == grupos[0]),
        ):
            for partido in ps_grupo:
                _partido_card(partido, uid, mis_pronosticos)


def _tab_fase(partidos: list[dict], fase: str, uid: str, mis_pronosticos: dict) -> None:
    """Renderiza el tab de una fase eliminatoria."""
    ps_fase = sorted(
        [p for p in partidos if p.get("fase") == fase],
        key=lambda x: x.get("fecha", ""),
    )

    if not ps_fase:
        st.info(f"No hay partidos de {fase} todavía. El admin los actualizará cuando avance el torneo.")
        return

    con_prono = sum(1 for p in ps_fase if p["id"] in mis_pronosticos)
    total     = len(ps_fase)

    st.markdown(
        f'<div style="margin-bottom:0.8rem; color:rgba(200,230,200,0.5); font-size:0.82rem;">'
        f'✅ {con_prono} de {total} pronosticados</div>',
        unsafe_allow_html=True,
    )

    for partido in ps_fase:
        _partido_card(partido, uid, mis_pronosticos)


def _guardar_todos_pronosticos(uid: str, partidos: list[dict], mis_pronosticos: dict) -> int:
    """
    Guarda en lote todos los pronósticos que el usuario haya llenado en
    partidos NO bloqueados, leyendo los valores de los widgets en session_state.

    Solo guarda un partido si AMBOS marcadores tienen valor y si cambió
    respecto a lo ya guardado. Devuelve cuántos se guardaron.
    """
    predicciones = []
    for partido in partidos:
        if esta_cerrado(partido):
            continue
        pid  = partido["id"]
        k_sl = f"tb_sl_{pid}"
        k_sv = f"tb_sv_{pid}"
        if k_sl not in st.session_state or k_sv not in st.session_state:
            continue

        sl = st.session_state.get(k_sl)
        sv = st.session_state.get(k_sv)
        if sl is None or sv is None:
            continue

        # Ganador de penales: solo eliminatoria + empate; si no, None (lo limpia).
        penales = None
        if es_eliminatoria(partido.get("fase")) and int(sl) == int(sv):
            if st.session_state.get(f"tb_penL_{pid}"):
                penales = "L"
            elif st.session_state.get(f"tb_penV_{pid}"):
                penales = "V"

        # Omitir si no cambió respecto a lo ya guardado (marcador + penales)
        prev = mis_pronosticos.get(pid, {})
        if (prev.get("local") == sl and prev.get("visitante") == sv
                and prev.get("penales") == penales):
            continue

        predicciones.append((pid, int(sl), int(sv), penales))

    if predicciones:
        return guardar_pronosticos_batch(uid, predicciones)
    return 0


# ── Función pública ───────────────────────────────────────────────────────────

def mostrar_tablero():
    """Vista principal: Mi Quiniela con pestañas por fase."""
    st.markdown(_CSS, unsafe_allow_html=True)

    uid    = st.session_state.get("uid", "")
    nombre = st.session_state.get("nombre", "Tú")

    # ── Encabezado ────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="margin-bottom:1rem;">
        <h1 style="font-size:1.8rem; margin-bottom:0.1rem;">
            📋 Mi Quiniela
        </h1>
        <p style="color:rgba(200,230,200,0.5); margin:0; font-size:0.85rem;">
            {nombre} · Ingresa tus pronósticos antes de que el partido comience
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Cargar datos ──────────────────────────────────────────────────────────
    with st.spinner("Cargando partidos..."):
        partidos = get_partidos()

    if not partidos:
        st.warning("No hay partidos cargados. Contacta al administrador.")
        return

    mis_pronosticos = get_pronosticos_usuario(uid)

    # ── Métricas rápidas ──────────────────────────────────────────────────────
    total        = len(partidos)
    pronosticados = len(mis_pronosticos)
    pendientes   = sum(1 for p in partidos if not esta_cerrado(p) and p["id"] not in mis_pronosticos)
    bloqueados   = sum(1 for p in partidos if esta_cerrado(p))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("⚽ Partidos",      total)
    c2.metric("✅ Pronosticados", pronosticados)
    c3.metric("⏳ Pendientes",    pendientes)
    c4.metric("🔒 Bloqueados",    bloqueados)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Guardar todos los pronósticos de una vez ───────────────────────────────
    st.info("💡 Llena los marcadores que quieras y pulsa **Guardar TODOS** para guardarlos de una sola vez.")
    if st.button("💾 Guardar TODOS mis pronósticos", key="tb_save_all_top",
                 type="primary", use_container_width=True):
        n = _guardar_todos_pronosticos(uid, partidos, mis_pronosticos)
        st.toast(f"✅ {n} pronóstico(s) guardado(s)." if n else "No había pronósticos nuevos para guardar.")
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Pestañas por fase ──────────────────────────────────────────────────────
    fases_disponibles = [
        f for f in _ORDEN_FASES
        if any(p.get("fase") == f for p in partidos)
    ]

    if not fases_disponibles:
        st.warning("No se encontraron fases en los partidos.")
        return

    # Abrir por defecto en la ronda en curso según la fecha de hoy. Streamlit no
    # permite "seleccionar" pestaña, así que ponemos esa fase de primera (la 1ª
    # pestaña es la activa al entrar). El resto conserva el orden del torneo.
    fase_actual = fase_en_curso(partidos)
    if fase_actual in fases_disponibles:
        fases_disponibles = [fase_actual] + [f for f in fases_disponibles if f != fase_actual]

    tabs = st.tabs(fases_disponibles)

    for tab, fase in zip(tabs, fases_disponibles):
        with tab:
            if fase == "Grupos":
                _tab_grupos(partidos, uid, mis_pronosticos)
            else:
                _tab_fase(partidos, fase, uid, mis_pronosticos)

    # ── Guardar todos (abajo) ──────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("💾 Guardar TODOS mis pronósticos", key="tb_save_all_bottom",
                 type="primary", use_container_width=True):
        n = _guardar_todos_pronosticos(uid, partidos, mis_pronosticos)
        st.toast(f"✅ {n} pronóstico(s) guardado(s)." if n else "No había pronósticos nuevos para guardar.")
        st.rerun()

    # ── Refresco manual ────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Recargar partidos", key="tb_refresh"):
        get_partidos.clear()
        get_pronosticos_usuario.clear()
        st.rerun()
