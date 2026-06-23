"""
horario.py — Lógica de tiempo y estado de los partidos.

Centraliza TODO lo que dependa de la hora:
  - Bloqueo automático de pronósticos: un partido se cierra JUSTO en el instante
    de su inicio (kickoff). Ej.: kickoff 13:00 → cerrado a las 13:00:00
    (último segundo para apostar: 12:59:59).
  - Estado visible del partido para el panel del día: PROXIMO / EN_JUEGO / FINAL.
  - Selección y formato de "los partidos de hoy".

⚠️ ZONA HORARIA (confirmado por el usuario)
   El campo `fecha` se guarda en **hora local de México** (ej. "2026-06-23T17:00"
   = 17:00 en CDMX), sin sufijo de zona. Aquí se interpreta como hora de México
   tanto para mostrar como para bloquear y para decidir "qué es hoy".
   Si algún día cambia la zona del torneo, ajusta solo TZ_LOCAL.
"""

from datetime import datetime, timedelta

import pytz

# ── Configuración ─────────────────────────────────────────────────────────────
TZ_LOCAL = pytz.timezone("America/Mexico_City")  # zona en la que están guardadas las horas

# Duración estimada de un partido, de kickoff a pitazo final. Determina cuándo
# el robot EMPIEZA a revisar (antes de esto no consulta la API) y el estado
# "EN_JUEGO" del panel. Fórmula acordada:
#   90' juego + 15' descanso + 8' hidratación + 12' tiempo agregado = 125 min.
DURACION_ESTIMADA_MIN = 125

_DIAS  = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_MESES = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
          "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def ahora_local() -> datetime:
    """Instante actual en la zona local (CDMX), con tzinfo."""
    return datetime.now(TZ_LOCAL)


def parse_kickoff(fecha_iso: str):
    """
    Convierte la cadena ISO guardada (hora local de México, normalmente naive)
    en un datetime con tzinfo local. Devuelve None si es inválida o vacía.
    """
    if not fecha_iso:
        return None
    try:
        dt = datetime.fromisoformat(fecha_iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return TZ_LOCAL.localize(dt)        # naive ⇒ ya es hora de México
    return dt.astimezone(TZ_LOCAL)


def kickoff_local(partido: dict):
    """Hora de inicio en la zona local (CDMX). None si no hay fecha."""
    return parse_kickoff(partido.get("fecha", ""))


def tiene_marcador(partido: dict) -> bool:
    """True si el partido ya tiene marcador real (local no nulo)."""
    return partido.get("marcador_real", {}).get("local") is not None


def esta_cerrado(partido: dict, ahora: datetime | None = None) -> bool:
    """
    ¿Está cerrado para pronosticar?

    Cerrado si:
      - el admin lo bloqueó manualmente (campo `bloqueado`), O
      - ya llegó (o pasó) el instante de inicio.

    kickoff a las 13:00 → cerrado cuando ahora >= 13:00:00 (12:59:59 abierto).
    """
    if partido.get("bloqueado", False):
        return True

    kickoff = parse_kickoff(partido.get("fecha", ""))
    if kickoff is None:
        return False  # Sin fecha válida: solo cuenta el bloqueo manual.

    ahora = ahora or ahora_local()
    return ahora >= kickoff


def estado_partido(partido: dict, ahora: datetime | None = None) -> str:
    """
    Estado para el panel del día:
      - "FINAL"     → ya tiene marcador real.
      - "EN_JUEGO"  → empezó y sigue dentro de la ventana estimada, sin marcador.
      - "PROXIMO"   → todavía no empieza.
      - "PENDIENTE" → ya debió terminar pero aún no hay marcador (falta capturarlo).
      - "SIN_FECHA" → no tiene fecha válida.
    """
    if tiene_marcador(partido):
        return "FINAL"

    kickoff = parse_kickoff(partido.get("fecha", ""))
    if kickoff is None:
        return "SIN_FECHA"

    ahora = ahora or ahora_local()
    if ahora < kickoff:
        return "PROXIMO"
    if ahora < kickoff + timedelta(minutes=DURACION_ESTIMADA_MIN):
        return "EN_JUEGO"
    return "PENDIENTE"


def partidos_de_hoy(partidos: list[dict], ahora: datetime | None = None) -> list[dict]:
    """
    Partidos cuyo inicio (hora local CDMX) cae HOY, ordenados por hora.
    """
    ahora = ahora or ahora_local()
    hoy = ahora.date()
    del_dia = []
    for p in partidos:
        k = parse_kickoff(p.get("fecha", ""))
        if k is not None and k.date() == hoy:
            del_dia.append((k, p))
    del_dia.sort(key=lambda t: t[0])
    return [p for _, p in del_dia]


def formatear_fecha_local(fecha_iso: str) -> str:
    """
    Formatea una fecha ISO (hora de México) a 'Mar 23 Jun · 17:00'.
    Si no se puede parsear, devuelve un recorte de la cadena original.
    """
    k = parse_kickoff(fecha_iso)
    if k is None:
        return fecha_iso[:16] if fecha_iso and len(fecha_iso) >= 16 else (fecha_iso or "")
    return f"{_DIAS[k.weekday()]} {k.day} {_MESES[k.month]} · {k.strftime('%H:%M')}"
