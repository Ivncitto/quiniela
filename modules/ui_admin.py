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

import json

import streamlit as st
from datetime import datetime

from modules.firestore_db import (
    get_partidos,
    actualizar_marcador_real,
    actualizar_equipos_partido,
    guardar_partidos_batch,
    toggle_bloqueo_partido,
    toggle_bloqueo_fase,
    toggle_forzar_abierto,
)
from modules.scoring import es_eliminatoria
from modules.horario import esta_cerrado


def _excluir_penal_adm(este: str, otro: str) -> None:
    """Callback: marcar un equipo como ganador de penales desmarca el otro."""
    if st.session_state.get(este):
        st.session_state[otro] = False


def _penales_adm(pid: str, es_elim: bool) -> str | None:
    """
    Ganador de penales capturado por el admin en una eliminatoria, sin importar
    el marcador. Devuelve "L"/"V"/None según el checkbox marcado.
    """
    if not es_elim:
        return None
    if st.session_state.get(f"adm_penL_{pid}"):
        return "L"
    if st.session_state.get(f"adm_penV_{pid}"):
        return "V"
    return None

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
    real_pen     = marcador.get("penales")  # "L" / "V" / None
    es_elim      = es_eliminatoria(partido.get("fase"))

    forzado      = partido.get("forzar_abierto", False)
    cerrado_efe  = esta_cerrado(partido)   # estado real para pronosticar
    estado_color = "#EF5350" if cerrado_efe else "#66BB6A"
    estado_icon  = "🔒" if bloqueado else "🔓"
    hay_score    = real_l is not None

    if forzado:
        texto_estado = "🔓 Reabierto (pronóstico tardío)"
    elif cerrado_efe:
        texto_estado = "Cerrado"
    else:
        texto_estado = "Abierto"

    # ── Indicador de estado inline ────────────────────────────────────────────
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">'
        f'<span style="width:7px;height:7px;border-radius:50%;'
        f'background:{estado_color};display:inline-block;"></span>'
        f'<span style="font-size:0.72rem;color:{estado_color};">'
        f'{texto_estado}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Fila principal: nombres + scores + botones ─────────────────────────────
    c_tl, c_sl, c_sep, c_sv, c_tv, c_save, c_lock, c_open = st.columns(
        [2.8, 0.75, 0.25, 0.75, 2.8, 1.3, 0.9, 1.0]
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
                pen = _penales_adm(pid, es_elim)
                actualizar_marcador_real(pid, int(score_local), int(score_vis), pen)
                extra = ""
                if pen == "L":
                    extra = f" · penales: {nuevo_local}"
                elif pen == "V":
                    extra = f" · penales: {nuevo_vis}"
                st.toast(f"✅ {nuevo_local} {score_local}–{score_vis} {nuevo_vis}{extra}")
            else:
                st.toast(f"✏️ {nuevo_local} vs {nuevo_vis} (sin marcador)")
            st.rerun()

    with c_lock:
        if st.button(estado_icon, key=f"adm_lock_{pid}", use_container_width=True):
            toggle_bloqueo_partido(pid, not bloqueado)
            st.rerun()

    with c_open:
        if forzado:
            if st.button("↩️", key=f"adm_reabrir_{pid}", use_container_width=True,
                         help="Quitar la reapertura: el partido vuelve a regirse por su hora."):
                toggle_forzar_abierto(pid, False)
                st.rerun()
        else:
            if st.button("🔓➕", key=f"adm_reabrir_{pid}", use_container_width=True,
                         help="Reabrir este partido para meter un pronóstico tardío, "
                              "aunque ya haya pasado su hora de inicio."):
                toggle_forzar_abierto(pid, True)
                st.toast(f"🔓 {e_local} vs {e_visitante} reabierto para pronóstico tardío.")
                st.rerun()

    # ── Penales: en toda eliminatoria, sin importar el marcador ───────────────
    # Si el partido se fue a penales, marca al ganador real aquí: todo participante
    # que lo haya acertado gana +2, haya pronosticado empate o no.
    if es_elim:
        kL, kV = f"adm_penL_{pid}", f"adm_penV_{pid}"
        if kL not in st.session_state:
            st.session_state[kL] = (real_pen == "L")
        if kV not in st.session_state:
            st.session_state[kV] = (real_pen == "V")

        cpx, cp1, cp2 = st.columns([2.8, 0.75 + 0.25 + 0.75, 2.8 + 1.3 + 0.9])
        with cpx:
            st.markdown(
                '<div style="font-size:0.72rem; color:#FFD54F; padding-top:0.35rem;">'
                '🥅 Ganador en penales (si hubo):</div>',
                unsafe_allow_html=True,
            )
        with cp1:
            st.checkbox(nuevo_local, key=kL, on_change=_excluir_penal_adm, args=(kL, kV))
        with cp2:
            st.checkbox(nuevo_vis, key=kV, on_change=_excluir_penal_adm, args=(kV, kL))

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
            pen = _penales_adm(pid, es_eliminatoria(partido.get("fase")))
            mr = partido.get("marcador_real", {})
            if mr.get("local") != sl or mr.get("visitante") != sv or mr.get("penales") != pen:
                cambio["marcador_real"] = {"local": int(sl), "visitante": int(sv), "penales": pen}

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


def _bloque_api(partidos: list[dict], fase: str) -> None:
    """
    Bloque "consultar football-data.org" para una fase, con flujo SEGURO en dos
    pasos: (1) previsualizar lo que rellenaría sin escribir, (2) aplicar si los
    cruces se ven bien. Reutiliza la lógica del robot vía modules.api_resultados.
    """
    from modules.api_resultados import previsualizar_fase, obtener_token

    sk = f"_api_prev_{fase}"
    with st.expander(f"🌐 Consultar resultados automáticamente ({fase})", expanded=False):
        token = obtener_token()
        if not token:
            st.info(
                "Falta el token de football-data. Agrégalo en "
                "`.streamlit/secrets.toml` → `[footballdata]` `token` para habilitar "
                "la consulta automática."
            )
            return

        st.caption(
            "**Paso 1:** consulta la API y *muestra* lo que rellenaría (no escribe). "
            "**Paso 2:** revisa los cruces y *aplica*. "
            "💡 Respalda antes con `python scripts/backup_firestore.py`."
        )

        if st.button("🔄 Consultar API y previsualizar", key=f"api_prev_btn_{fase}",
                     use_container_width=True):
            with st.spinner("Consultando football-data.org..."):
                st.session_state[sk] = previsualizar_fase(partidos, fase, token)
            st.rerun()

        prev = st.session_state.get(sk)
        if not prev:
            return

        if prev.get("error"):
            st.error(f"❌ {prev['error']}")
            return

        st.caption(
            f"Rango consultado: {prev['dfrom']} → {prev['dto']} · "
            f"{prev['n_matches']} partidos recibidos de la API."
        )

        for aviso in prev.get("avisos", []):
            st.warning(aviso)

        batch = prev.get("batch", [])
        if not batch:
            st.success("✅ La API no trae nada nuevo para esta fase (ya está al día).")
            return

        st.markdown(f"**{len(batch)} cambio(s) propuesto(s):**")
        filas = []
        for c in batch:
            partes = []
            if "equipo_local" in c:
                partes.append(f"equipos → {c['equipo_local']} vs {c['equipo_visitante']}")
            if "marcador_real" in c:
                mr = c["marcador_real"]
                partes.append(f"marcador → {mr['local']}–{mr['visitante']}")
            filas.append({"id": c["id"], "cambio": " · ".join(partes)})
        st.dataframe(filas, use_container_width=True, hide_index=True)

        ca, cb = st.columns(2)
        with ca:
            if st.button(f"✅ Aplicar {len(batch)} cambio(s)", key=f"api_apply_{fase}",
                         type="primary", use_container_width=True):
                guardar_partidos_batch(batch)
                st.session_state.pop(sk, None)
                st.toast(f"✅ {len(batch)} cambio(s) aplicado(s) a {fase}.")
                st.rerun()
        with cb:
            if st.button("✖️ Descartar previsualización", key=f"api_discard_{fase}",
                         use_container_width=True):
                st.session_state.pop(sk, None)
                st.rerun()


def _fmt_fecha_corta(fecha_iso: str) -> str:
    """Formatea fecha ISO (UTC) a hora local de México: 'Jue 11 Jun · 13:00'."""
    from modules.horario import formatear_fecha_local
    return formatear_fecha_local(fecha_iso)


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
    _bloque_api(partidos, "Grupos")
    st.markdown("<br>", unsafe_allow_html=True)
    _boton_guardar_todo(partidos_grupos, key="adm_save_all_grupos_top")
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Cabecera de columnas ───────────────────────────────────────────────────
    hc1, hc2, hc3, hc4, hc5, hc6, hc7, hc8 = st.columns(
        [2.8, 0.75, 0.25, 0.75, 2.8, 1.3, 0.9, 1.0]
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
    _bloque_api(partidos, fase)
    st.markdown("<br>", unsafe_allow_html=True)
    _boton_guardar_todo(ps_fase, key=f"adm_save_all_{fase}_top")
    st.markdown("<br>", unsafe_allow_html=True)

    # Cabecera
    hc1, hc2, hc3, hc4, hc5, hc6, hc7, hc8 = st.columns(
        [2.8, 0.75, 0.25, 0.75, 2.8, 1.3, 0.9, 1.0]
    )
    hc1.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">LOCAL</span>',      unsafe_allow_html=True)
    hc2.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">GOL</span>',       unsafe_allow_html=True)
    hc4.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">GOL</span>',       unsafe_allow_html=True)
    hc5.markdown('<span style="font-size:0.7rem;color:rgba(200,230,200,0.4);">VISITANTE</span>', unsafe_allow_html=True)

    for partido in ps_fase:
        _partido_row(partido)

    st.markdown("<br>", unsafe_allow_html=True)
    _boton_guardar_todo(ps_fase, key=f"adm_save_all_{fase}_bottom")


def _seccion_capturar_pronostico(partidos: list[dict]) -> None:
    """
    (Admin) Captura/edita el pronóstico de CUALQUIER participante en cualquier
    partido. Pensado para pronósticos tardíos que llegaron por fuera (mensaje)
    y no se metieron a tiempo. Sobreescribe lo que el participante tenga guardado.
    """
    from modules.firestore_db import (
        get_todos_los_usuarios,
        get_pronosticos_usuario,
        guardar_pronosticos_batch,
    )

    with st.expander("✍️ Capturar pronóstico de un participante (pronóstico tardío)"):
        usuarios = get_todos_los_usuarios()
        if not usuarios:
            st.info("No hay participantes registrados todavía.")
            return

        st.caption(
            "Escribe aquí el pronóstico de un participante que te llegó por fuera "
            "y no se metió a tiempo. **Sobreescribe** lo que tenga guardado en ese "
            "partido. (No cambia el marcador real, solo el pronóstico de esa persona.)"
        )

        mapa = {u.get("nombre", u.get("uid", "?")): u.get("uid", "") for u in usuarios}
        nombres = sorted(mapa)

        ps = sorted(partidos, key=lambda x: x.get("fecha", ""))

        def _lbl(p: dict) -> str:
            return (f"[{p.get('fase', '?')}] {p.get('equipo_local', '¿?')} vs "
                    f"{p.get('equipo_visitante', '¿?')} · {p.get('fecha', '')[:10]}")

        id_por_lbl = {_lbl(p): p["id"] for p in ps}

        col_u, col_p = st.columns([2, 3])
        with col_u:
            nombre_sel = st.selectbox("👤 Participante", nombres, key="capt_user")
        with col_p:
            lbl_sel = st.selectbox("⚽ Partido", list(id_por_lbl), key="capt_match")

        uid = mapa.get(nombre_sel, "")
        pid = id_por_lbl.get(lbl_sel, "")
        partido = next((p for p in ps if p["id"] == pid), {})
        es_elim = es_eliminatoria(partido.get("fase"))
        e_local = partido.get("equipo_local", "Local")
        e_vis   = partido.get("equipo_visitante", "Visitante")

        # Pronóstico actual de ese participante en ese partido
        prono = get_pronosticos_usuario(uid).get(pid, {})
        cur_l = prono.get("local")
        cur_v = prono.get("visitante")
        cur_pen = prono.get("penales")

        if prono:
            pen_txt = ""
            if cur_pen == "L":
                pen_txt = f" · 🥅 {e_local}"
            elif cur_pen == "V":
                pen_txt = f" · 🥅 {e_vis}"
            st.caption(f"Actual de **{nombre_sel}**: {cur_l}–{cur_v}{pen_txt}")
        else:
            st.caption(f"**{nombre_sel}** aún no tiene pronóstico en este partido.")

        cga, cgb = st.columns(2)
        with cga:
            gl = st.number_input(
                f"⚽ Goles {e_local}", min_value=0, max_value=30,
                value=int(cur_l) if cur_l is not None else None,
                key=f"capt_l_{uid}_{pid}", placeholder="0",
            )
        with cgb:
            gv = st.number_input(
                f"⚽ Goles {e_vis}", min_value=0, max_value=30,
                value=int(cur_v) if cur_v is not None else None,
                key=f"capt_v_{uid}_{pid}", placeholder="0",
            )

        penales = None
        if es_elim:
            opts = ["— (sin penales)", e_local, e_vis]
            idx = 1 if cur_pen == "L" else (2 if cur_pen == "V" else 0)
            sel = st.selectbox(
                "🥅 Si hay penales, ¿quién gana? (+2 pts extra)",
                opts, index=idx, key=f"capt_pen_{uid}_{pid}",
            )
            if sel == e_local:
                penales = "L"
            elif sel == e_vis:
                penales = "V"

        if st.button("💾 Guardar pronóstico del participante", type="primary", key="capt_save"):
            if gl is None or gv is None:
                st.warning("Pon ambos goles antes de guardar.")
            else:
                guardar_pronosticos_batch(uid, [(pid, int(gl), int(gv), penales)])
                st.success(f"✅ Pronóstico de {nombre_sel} guardado: {int(gl)}–{int(gv)} en {lbl_sel}.")
                st.rerun()


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

    # ── Capturar pronóstico de un participante (pronóstico tardío) ─────────────
    _seccion_capturar_pronostico(partidos)

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

    # ── Instrumentación: lecturas reales a Firestore en este proceso ───────────
    from modules.firestore_db import (
        LECTURAS,
        migrar_pronosticos_a_documento_unico,
        reconstruir_agregado_partidos,
        exportar_backup,
    )
    st.caption(f"🔎 Lecturas reales a Firestore en este proceso del servidor: **{LECTURAS['total']}** "
               "(no cuenta los aciertos de caché). Útil para auditar la cuota.")

    # ── Optimización de base de datos (migración única) ────────────────────────
    with st.expander("🛠️ Optimizar base de datos (reducir lecturas de Firestore)"):
        st.markdown(
            "**1) Pronósticos → 1 documento por usuario.** Convierte los pronósticos "
            "de *1 documento por partido* a *1 por usuario* (≈13). El ranking pasa de "
            "leer ~miles de documentos a ~1 por participante. **Se ejecuta una sola vez.**"
        )
        if st.button("🚀 Migrar pronósticos ahora", key="adm_migrar"):
            with st.spinner("Migrando pronósticos a documento único..."):
                res = migrar_pronosticos_a_documento_unico()
            st.success(
                f"✅ Migración completa · {res['usuarios']} usuarios · "
                f"{res['leidos']} documentos leídos · {res['borrados']} viejos borrados."
            )
            st.rerun()

        st.markdown("---")
        st.markdown(
            "**2) Partidos → 1 documento agregado.** El agregado se crea solo al "
            "leer; usa este botón solo si **volviste a sembrar** los partidos (seed) "
            "y necesitas refrescar el agregado."
        )
        if st.button("🔁 Reconstruir agregado de partidos", key="adm_reconstruir_partidos"):
            with st.spinner("Reconstruyendo lista de partidos..."):
                n = reconstruir_agregado_partidos()
            st.success(f"✅ Agregado reconstruido con {n} partidos.")
            st.rerun()

        st.markdown("---")
        st.markdown(
            "**3) Descargar respaldo (JSON).** Lee la base **una vez** y arma un "
            "backup: 1 entrada por persona con **todos los partidos** (los que no "
            "pronosticó quedan en `null`) + `meta-partidos`. Hazlo **antes de migrar**."
        )
        if st.button("📦 Preparar respaldo (lee la BD una vez)", key="adm_prep_backup"):
            with st.spinner("Leyendo y consolidando la base..."):
                backup = exportar_backup()
            st.session_state["_backup_json"] = json.dumps(backup, ensure_ascii=False, indent=2)
            st.session_state["_backup_partidos_json"] = json.dumps(
                backup["meta_partidos"], ensure_ascii=False, indent=2
            )
            st.success(
                f"✅ Respaldo listo: {len(backup['pronosticos'])} personas · "
                f"{len(backup['meta_partidos'])} partidos."
            )

        if st.session_state.get("_backup_json"):
            cda, cdb = st.columns(2)
            with cda:
                st.download_button(
                    "⬇️ Respaldo completo (pronósticos + partidos)",
                    data=st.session_state["_backup_json"],
                    file_name="quiniela_backup.json",
                    mime="application/json",
                    key="adm_dl_backup",
                    use_container_width=True,
                )
            with cdb:
                st.download_button(
                    "⬇️ Solo meta-partidos",
                    data=st.session_state["_backup_partidos_json"],
                    file_name="meta_partidos.json",
                    mime="application/json",
                    key="adm_dl_partidos",
                    use_container_width=True,
                )
