"""
Panel de Administrador — Rediseñado.

Diseño:
  - Pestañas por fase: Grupos | 16avos | Octavos | Cuartos | Semifinal | Tercer Lugar | Final
  - Cada partido en formato compacto de una sola fila:
      [Equipo Local] [Score] — [Score] [Equipo Visitante] | [💾 Guardar] [🔒/🔓]
  - Los nombres de equipo son editables (clave para partidos eliminatorios).
  - En Grupos los partidos se listan en orden cronológico (por fecha).
  - Bloqueo/desbloqueo individual y de toda la fase.
"""

import streamlit as st
from datetime import datetime

from modules.firestore_db import (
    get_partidos,
    actualizar_marcador_real,
    actualizar_equipos_partido,
    guardar_partidos_batch,
    toggle_bloqueo_partido,
    toggle_bloqueo_fase,
)

_ORDEN_FASES = [
    "Grupos",
    "16avos",
    "Octavos",
    "Cuartos",
    "Semifinal",
    "Tercer Lugar",
    "Final",
]

# CSS específico del panel admin
_CSS_ADMIN = """
<style>
    /* Fila de partido */
    .partido-row {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(76,175,80,0.15);
        border-radius: 10px;
        padding: 0.45rem 0.7rem;
        margin: 0.3rem 0;
        transition: border-color 0.2s;
    }
    .partido-row:hover {
        border-color: rgba(76,175,80,0.4);
    }
    .partido-row.bloqueado {
        border-color: rgba(239,83,80,0.25);
        background: rgba(239,83,80,0.03);
    }
    /* Ocultar labels de inputs dentro del panel admin */
    .admin-input label { display: none !important; }
    /* Separador vs */
    .vs-sep {
        text-align: center;
        font-weight: 800;
        color: rgba(200,230,200,0.3);
        padding-top: 0.45rem;
        font-size: 1.1rem;
    }
    /* Header de grupo */
    .grupo-header {
        background: linear-gradient(90deg, rgba(46,125,50,0.18), transparent);
        border-left: 3px solid #4CAF50;
        padding: 0.4rem 0.8rem;
        border-radius: 0 8px 8px 0;
        margin: 0.8rem 0 0.4rem;
    }
</style>
"""


def _partido_row(partido: dict) -> None:
    """
    Renderiza una fila compacta de partido en el panel admin.

    Formato:
        [Equipo Local] [🔲] — [🔲] [Equipo Visitante] | [💾 Guardar] [🔒/🔓]
    """
    pid          = partido["id"]
    e_local      = partido.get("equipo_local",     "Por definir A")
    e_visitante  = partido.get("equipo_visitante",  "Por definir B")
    bloqueado    = partido.get("bloqueado",          False)
    marcador     = partido.get("marcador_real",      {})
    real_l       = marcador.get("local")
    real_v       = marcador.get("visitante")

    estado_color = "#EF5350" if bloqueado else "#66BB6A"
    estado_icon  = "🔒" if bloqueado else "🔓"
    hay_score    = real_l is not None

    # ── Indicador de estado inline ────────────────────────────────────────────
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">'
        f'<span style="width:7px;height:7px;border-radius:50%;'
        f'background:{estado_color};display:inline-block;"></span>'
        f'<span style="font-size:0.72rem;color:{estado_color};">'
        f'{"Cerrado" if bloqueado else "Abierto"}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Fila principal: nombres + scores + botones ─────────────────────────────
    c_tl, c_sl, c_sep, c_sv, c_tv, c_save, c_lock = st.columns(
        [2.8, 0.75, 0.25, 0.75, 2.8, 1.3, 0.9]
    )

    with c_tl:
        nuevo_local = st.text_input(
            "local", value=e_local,
            key=f"adm_tl_{pid}",
            label_visibility="collapsed",
        )

    with c_sl:
        score_local = st.number_input(
            "gl", value=int(real_l) if hay_score else None,
            min_value=0, max_value=30,
            key=f"adm_sl_{pid}",
            label_visibility="collapsed",
            placeholder="0",
        )

    with c_sep:
        st.markdown('<div class="vs-sep">—</div>', unsafe_allow_html=True)

    with c_sv:
        score_vis = st.number_input(
            "gv", value=int(real_v) if hay_score else None,
            min_value=0, max_value=30,
            key=f"adm_sv_{pid}",
            label_visibility="collapsed",
            placeholder="0",
        )

    with c_tv:
        nuevo_vis = st.text_input(
            "visitante", value=e_visitante,
            key=f"adm_tv_{pid}",
            label_visibility="collapsed",
        )

    with c_save:
        if st.button("💾 Guardar", key=f"adm_save_{pid}", use_container_width=True):
            # Guardar nombres si cambiaron
            if nuevo_local.strip() != e_local or nuevo_vis.strip() != e_visitante:
                actualizar_equipos_partido(pid, nuevo_local, nuevo_vis)
            # Guardar marcador solo si ambos campos tienen valor
            if score_local is not None and score_vis is not None:
                actualizar_marcador_real(pid, int(score_local), int(score_vis))
                st.toast(f"✅ {nuevo_local} {score_local}–{score_vis} {nuevo_vis}")
            else:
                st.toast(f"✏️ {nuevo_local} vs {nuevo_vis} (sin marcador)")
            st.rerun()

    with c_lock:
        if st.button(estado_icon, key=f"adm_lock_{pid}", use_container_width=True):
            toggle_bloqueo_partido(pid, not bloqueado)
            st.rerun()

    # Separador ligero
    st.markdown(
        "<hr style='border:none; border-top:1px solid rgba(76,175,80,0.07); margin:0.2rem 0;'>",
        unsafe_allow_html=True,
    )


def _guardar_todos(lista: list[dict]) -> int:
    """
    Guarda en lote nombres y marcadores de todos los partidos de `lista`,
    leyendo los valores actuales de los widgets desde session_state.

    Solo guarda el marcador de un partido si AMBOS goles tienen valor.
    Devuelve cuántos partidos tuvieron cambios.
    """
    cambios = []
    for partido in lista:
        pid  = partido["id"]
        k_tl = f"adm_tl_{pid}"
        k_sl = f"adm_sl_{pid}"
        k_sv = f"adm_sv_{pid}"
        k_tv = f"adm_tv_{pid}"

        # Si el partido no se ha renderizado aún, no hay nada que leer
        if k_sl not in st.session_state and k_tl not in st.session_state:
            continue

        cambio: dict = {"id": pid}

        # ── Nombres de equipo ──
        nl = str(st.session_state.get(k_tl, partido.get("equipo_local", ""))).strip()
        nv = str(st.session_state.get(k_tv, partido.get("equipo_visitante", ""))).strip()
        if nl and nv and (nl != partido.get("equipo_local", "") or nv != partido.get("equipo_visitante", "")):
            cambio["equipo_local"]     = nl
            cambio["equipo_visitante"] = nv

        # ── Marcador (solo si ambos goles están definidos) ──
        sl = st.session_state.get(k_sl)
        sv = st.session_state.get(k_sv)
        if sl is not None and sv is not None:
            mr = partido.get("marcador_real", {})
            if mr.get("local") != sl or mr.get("visitante") != sv:
                cambio["marcador_real"] = {"local": int(sl), "visitante": int(sv)}

        if len(cambio) > 1:   # tiene algo además de "id"
            cambios.append(cambio)

    if cambios:
        guardar_partidos_batch(cambios)
    return len(cambios)


def _boton_guardar_todo(lista: list[dict], key: str) -> None:
    """Botón que guarda de una vez todos los marcadores de `lista`."""
    if st.button("💾 Guardar TODOS los marcadores", key=key, type="primary", use_container_width=True):
        n = _guardar_todos(lista)
        st.toast(f"✅ {n} partido(s) guardado(s)." if n else "No había cambios para guardar.")
        st.rerun()


def _fmt_fecha_corta(fecha_iso: str) -> str:
    """Formatea fecha ISO a 'Jue 11 Jun · 19:00' para el separador cronológico."""
    try:
        dt = datetime.fromisoformat(fecha_iso)
        dias  = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        meses = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        return f"{dias[dt.weekday()]} {dt.day} {meses[dt.month]} · {dt.strftime('%H:%M')}"
    except Exception:
        return fecha_iso[:16] if len(fecha_iso) >= 16 else fecha_iso


def _tab_grupos(partidos: list[dict]) -> None:
    """
    Renderiza el tab de Fase de Grupos como lista CRONOLÓGICA (por fecha),
    del primer partido al último, para asignar marcadores con facilidad.
    """
    partidos_grupos = sorted(
        [p for p in partidos if p.get("fase") == "Grupos"],
        key=lambda x: x.get("fecha", ""),
    )

    if not partidos_grupos:
        st.info("No hay partidos de Grupos cargados.")
        return

    # ── Acciones globales de fase ──────────────────────────────────────────────
    col_a, col_b, col_c = st.columns([1, 1, 3])
    with col_a:
        if st.button("🔒 Bloquear todos los Grupos", key="blq_fase_grupos", use_container_width=True):
            toggle_bloqueo_fase("Grupos", True)
            st.rerun()
    with col_b:
        if st.button("🔓 Desbloquear todos los Grupos", key="desblq_fase_grupos", use_container_width=True):
            toggle_bloqueo_fase("Grupos", False)
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    _boton_guardar_todo(partidos_grupos, key="adm_save_all_grupos_top")
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Cabecera de columnas ───────────────────────────────────────────────────
    hc1, hc2, hc3, hc4, hc5, hc6, hc7 = st.columns(
        [2.8, 0.75, 0.25, 0.75, 2.8, 1.3, 0.9]
    )
    hc1.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">LOCAL</span>',       unsafe_allow_html=True)
    hc2.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">GOL</span>',        unsafe_allow_html=True)
    hc4.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">GOL</span>',        unsafe_allow_html=True)
    hc5.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">VISITANTE</span>',  unsafe_allow_html=True)

    # ── Lista cronológica con separador de día ─────────────────────────────────
    dia_actual = None
    for partido in partidos_grupos:
        dia = partido.get("fecha", "")[:10]   # YYYY-MM-DD
        if dia != dia_actual:
            dia_actual = dia
            st.markdown(
                f'<div class="grupo-header">📅 {_fmt_fecha_corta(partido.get("fecha", ""))}'
                f'<span style="color:rgba(200,230,200,0.4); font-size:0.78rem;">'
                f'&nbsp;&nbsp;·&nbsp;&nbsp;Grupo {partido.get("grupo", "?")}</span></div>',
                unsafe_allow_html=True,
            )
        _partido_row(partido)

    st.markdown("<br>", unsafe_allow_html=True)
    _boton_guardar_todo(partidos_grupos, key="adm_save_all_grupos_bottom")


def _tab_fase(partidos: list[dict], fase: str) -> None:
    """Renderiza un tab de fase eliminatoria."""
    ps_fase = sorted(
        [p for p in partidos if p.get("fase") == fase],
        key=lambda x: x.get("fecha", ""),
    )

    if not ps_fase:
        st.info(f"No hay partidos de {fase} cargados aún.")
        return

    # Acciones globales
    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        if st.button(f"🔒 Bloquear {fase}", key=f"blq_f_{fase}", use_container_width=True):
            toggle_bloqueo_fase(fase, True)
            st.rerun()
    with c2:
        if st.button(f"🔓 Desbloquear {fase}", key=f"desblq_f_{fase}", use_container_width=True):
            toggle_bloqueo_fase(fase, False)
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    _boton_guardar_todo(ps_fase, key=f"adm_save_all_{fase}_top")
    st.markdown("<br>", unsafe_allow_html=True)

    # Cabecera
    hc1, hc2, hc3, hc4, hc5, hc6, hc7 = st.columns(
        [2.8, 0.75, 0.25, 0.75, 2.8, 1.3, 0.9]
    )
    hc1.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">LOCAL</span>',      unsafe_allow_html=True)
    hc2.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">GOL</span>',       unsafe_allow_html=True)
    hc4.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">GOL</span>',       unsafe_allow_html=True)
    hc5.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">VISITANTE</span>', unsafe_allow_html=True)

    for partido in ps_fase:
        _partido_row(partido)

    st.markdown("<br>", unsafe_allow_html=True)
    _boton_guardar_todo(ps_fase, key=f"adm_save_all_{fase}_bottom")


# ─── Función pública principal ────────────────────────────────────────────────

def mostrar_panel_admin():
    """Renderiza el Panel de Administrador completo con pestañas por fase."""

    from modules.auth import es_admin
    if not es_admin():
        st.error("🚫 Acceso denegado. Solo para administradores.")
        return

    st.markdown(_CSS_ADMIN, unsafe_allow_html=True)

    # ── Encabezado ────────────────────────────────────────────────────────────
    st.markdown("""
    <div style="margin-bottom: 1rem;">
        <h1 style="font-size: 1.8rem; margin-bottom: 0.1rem;">⚙️ Panel Admin</h1>
        <p style="color: rgba(200,230,200,0.5); margin: 0; font-size: 0.85rem;">
            Edita equipos · Ingresa marcadores · Bloquea / Desbloquea partidos
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Cargar partidos ────────────────────────────────────────────────────────
    with st.spinner("Cargando partidos..."):
        partidos = get_partidos()

    if not partidos:
        st.warning("No hay partidos cargados. Ejecuta `python run_seed.py`.")
        return

    # Métricas rápidas
    total      = len(partidos)
    bloqueados = sum(1 for p in partidos if p.get("bloqueado", False))
    con_score  = sum(1 for p in partidos if p.get("marcador_real", {}).get("local") is not None)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📋 Total",       total)
    c2.metric("🔒 Bloqueados",  bloqueados)
    c3.metric("🔓 Abiertos",    total - bloqueados)
    c4.metric("⚽ Con marcador", con_score)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Pestañas por fase ──────────────────────────────────────────────────────
    fases_con_datos = [
        f for f in _ORDEN_FASES
        if any(p.get("fase") == f for p in partidos)
    ]

    tabs = st.tabs(fases_con_datos)

    for tab, fase in zip(tabs, fases_con_datos):
        with tab:
            if fase == "Grupos":
                _tab_grupos(partidos)
            else:
                _tab_fase(partidos, fase)

    # ── Refresco manual ────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Recargar desde Firestore", key="adm_refresh"):
        get_partidos.clear()
        st.rerun()
