"""
api_resultados.py — Puente entre la app (Panel Admin) y el robot de marcadores.
================================================================================
Permite que el Panel Admin consulte football-data.org POR FASE y previsualice
qué equipos/marcadores rellenaría, SIN escribir nada. La escritura se hace
después con un segundo botón (patrón seguro: previsualizar → aplicar).

Reutiliza la lógica ya probada de `actualizar_resultados.py` (traducción de
equipos, llamada a la API y conciliación API↔BD) en vez de duplicarla.

OJO (lo mismo que en la bitácora §5): las eliminatorias se emparejan por ORDEN
cronológico dentro de la fase. Por eso esta función NUNCA escribe: solo propone,
y el admin confirma viendo los cruces.
"""

import os
import sys
import copy
from datetime import timedelta

# La app corre desde la raíz (streamlit run app.py), pero garantizamos que la
# raíz esté en sys.path para poder importar el script del robot.
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

import actualizar_resultados as robot          # noqa: E402
from modules.horario import TZ_LOCAL, parse_kickoff  # noqa: E402


def obtener_token() -> str | None:
    """Token de football-data: st.secrets → variable de entorno → secrets.toml."""
    try:
        import streamlit as st
        tok = st.secrets.get("footballdata", {}).get("token")
        if tok:
            return str(tok).strip()
    except Exception:
        pass
    tok = os.environ.get("FOOTBALL_DATA_TOKEN")
    if tok:
        return tok.strip()
    try:
        sec = robot._cargar_secrets_toml()
        tok = sec.get("footballdata", {}).get("token")
        return str(tok).strip() if tok else None
    except Exception:
        return None


def _rango_fechas_fase(partidos: list[dict], fase: str):
    """(dateFrom, dateTo) en YYYY-MM-DD (hora MX) que cubre TODA la fase, con
    1 día de colchón a cada lado para no perder partidos por husos horarios."""
    fechas = []
    for p in partidos:
        if p.get("fase") == fase:
            k = parse_kickoff(p.get("fecha", ""))
            if k is not None:
                fechas.append(k)
    if not fechas:
        return None, None
    dmin = (min(fechas).astimezone(TZ_LOCAL) - timedelta(days=1)).date()
    dmax = (max(fechas).astimezone(TZ_LOCAL) + timedelta(days=1)).date()
    return dmin.isoformat(), dmax.isoformat()


def previsualizar_fase(partidos: list[dict], fase: str, token: str) -> dict:
    """
    Consulta la API para el rango de fechas de `fase` y calcula —sin escribir—
    qué cambiaría SOLO en esa fase.

    Devuelve:
      {
        "dfrom", "dto", "n_matches": int,
        "batch":  [ {id, equipo_local?, equipo_visitante?, marcador_real?}, ... ],
        "log":    [str, ...]   # bitácora cruda de aplicar_cambios
        "avisos": [str, ...]   # solo las líneas ⚠️ (desajustes / sin match)
      }
    o {"error": "..."} si algo falla.
    """
    dfrom, dto = _rango_fechas_fase(partidos, fase)
    if not dfrom:
        return {"error": f"No hay partidos de {fase} con fecha en la BD."}

    try:
        matches = robot.consultar_api(token, dfrom, dto)
    except Exception as e:
        return {"error": f"Falló la consulta a la API: {e}"}

    # Aplicamos sobre una COPIA para no tocar la lista real ni escribir en BD.
    copia = copy.deepcopy(partidos)
    log = robot.aplicar_cambios(copia, matches)

    # Diff: solo construimos el batch con los cambios de ESTA fase.
    orig_por_id = {p["id"]: p for p in partidos}
    batch = []
    for p in copia:
        if p.get("fase") != fase:
            continue
        o = orig_por_id.get(p["id"], {})
        cambio = {"id": p["id"]}
        if (p.get("equipo_local") != o.get("equipo_local")
                or p.get("equipo_visitante") != o.get("equipo_visitante")):
            cambio["equipo_local"] = p.get("equipo_local")
            cambio["equipo_visitante"] = p.get("equipo_visitante")
        mr_new = p.get("marcador_real", {}) or {}
        if mr_new.get("local") is not None and mr_new != (o.get("marcador_real") or {}):
            cambio["marcador_real"] = mr_new
        if len(cambio) > 1:   # algo además de "id"
            batch.append(cambio)

    # Solo avisos relevantes a ESTA fase (el colchón de fechas puede atrapar
    # partidos de fases vecinas y generar avisos ajenos que confunden).
    fl = fase.lower()
    avisos = [
        c for c in log
        if c.startswith("⚠️") and (fl in c.lower() or "desconocido" in c.lower())
    ]
    return {
        "dfrom": dfrom, "dto": dto, "n_matches": len(matches),
        "batch": batch, "log": log, "avisos": avisos,
    }
