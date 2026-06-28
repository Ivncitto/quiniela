"""
Módulo de cálculo de puntuación de la Quiniela.

Sistema de puntuación (se conserva el de siempre + bono de penales):

  MARCADOR (todas las fases)
    - 5 puntos: Marcador exacto correcto.
    - 3 puntos: Resultado correcto (local/empate/visitante) pero marcador diferente.
    - 0 puntos: Resultado incorrecto o sin pronóstico.

  PENALES — bono EXTRA solo en fases eliminatorias (16avos en adelante)
    - +2 puntos: si se acierta quién gana la tanda de penales. Lo puede llenar
      CUALQUIERA (haya pronosticado empate o no); solo otorga puntos si el
      partido realmente se definió en penales (el admin registró un ganador) y
      se acierta ese ganador. No importan los goles de la tanda ni el marcador.
      Es aditivo al marcador.

    Así, un partido eliminatorio que va a penales puede dar hasta 7 puntos
    (5 por el marcador exacto del empate + 2 por acertar el ganador en penales).

  La fase de Grupos NO usa penales (un empate ahí es resultado final).

Representación del ganador en penales: "L" (gana el local) o "V" (gana el
visitante). Se guarda en el campo "penales" tanto del pronóstico como del
marcador real.
"""

import pandas as pd


# Puntos extra por acertar el ganador en penales (solo eliminatorias, en empate).
PUNTOS_PENALES = 2

# Fases que habilitan el bono de penales. Todo lo demás (Grupos) no lo usa.
FASES_ELIMINATORIA = {
    "16avos", "Octavos", "Cuartos", "Semifinal", "Tercer Lugar", "Final",
}


def es_eliminatoria(fase: str | None) -> bool:
    """True si la fase usa el esquema eliminatorio (penales habilitados)."""
    return fase in FASES_ELIMINATORIA


# ─── Funciones auxiliares ─────────────────────────────────────────────────────

def _resultado(goles_local: int, goles_visitante: int) -> str:
    """
    Determina el resultado de un partido.

    Returns:
        'L' si gana el local, 'E' si hay empate, 'V' si gana el visitante.
    """
    if goles_local > goles_visitante:
        return "L"
    elif goles_local == goles_visitante:
        return "E"
    else:
        return "V"


# ─── Función principal de puntuación ─────────────────────────────────────────

def desglose_puntos(pronostico: dict, marcador_real: dict, fase: str | None = None) -> dict:
    """
    Calcula el desglose de puntos de un pronóstico dado el marcador real.

    Args:
        pronostico:    {"local": int, "visitante": int, "penales": "L"|"V"|None}
        marcador_real: {"local": int|None, "visitante": int|None, "penales": "L"|"V"|None}
        fase:          fase del partido (para habilitar el bono de penales).

    Returns:
        Dict con:
          base            -> puntos por marcador (0, 3 o 5)
          penales         -> puntos extra por penales (0 o 2)
          total           -> base + penales
          exacto          -> True si acertó el marcador exacto (5 pts)
          resultado       -> True si acertó solo el resultado (3 pts)
          acierto_penales -> True si acertó el ganador en penales (+2 pts)
        Todo en 0/False si el partido aún no tiene marcador real.
    """
    out = {
        "base": 0, "penales": 0, "total": 0,
        "exacto": False, "resultado": False, "acierto_penales": False,
    }

    marcador_real = marcador_real or {}
    real_local = marcador_real.get("local")
    real_visitante = marcador_real.get("visitante")

    # Si no hay marcador real, no se pueden calcular puntos aún
    if real_local is None or real_visitante is None:
        return out

    pron = pronostico or {}
    pron_local = pron.get("local")
    pron_visitante = pron.get("visitante")

    # ── Puntos base por marcador (sistema de siempre: 5 / 3 / 0) ──────────────
    if pron_local is not None and pron_visitante is not None:
        if pron_local == real_local and pron_visitante == real_visitante:
            out["base"] = 5
            out["exacto"] = True
        elif _resultado(pron_local, pron_visitante) == _resultado(real_local, real_visitante):
            out["base"] = 3
            out["resultado"] = True

    # ── Bono de penales: solo eliminatorias ───────────────────────────────────
    # Lo puede ganar CUALQUIERA que haya elegido al ganador de penales, sin
    # importar su marcador: basta con que el partido se haya ido a penales
    # (el admin registró un ganador real) y que se acierte ese ganador.
    if es_eliminatoria(fase):
        real_pen = marcador_real.get("penales")
        pron_pen = pron.get("penales")
        if real_pen and pron_pen and pron_pen == real_pen:
            out["penales"] = PUNTOS_PENALES
            out["acierto_penales"] = True

    out["total"] = out["base"] + out["penales"]
    return out


def calcular_puntos(pronostico: dict, marcador_real: dict, fase: str | None = None) -> int:
    """
    Puntos totales obtenidos por un pronóstico (marcador + bono de penales).

    Returns:
        En Grupos: 0, 3 o 5.
        En eliminatorias con empate: además puede sumar +2 por penales (hasta 7).
    """
    return desglose_puntos(pronostico, marcador_real, fase)["total"]


# ─── Cálculo de rankings ──────────────────────────────────────────────────────

def calcular_ranking(
    usuarios: list[dict],
    pronosticos: list[dict],
    partidos: list[dict],
) -> pd.DataFrame:
    """
    Calcula el ranking general de todos los usuarios.

    Args:
        usuarios:    Lista de dicts con datos de usuarios (uid, nombre, rol...).
        pronosticos: Lista de todos los pronósticos en Firestore.
        partidos:    Lista de todos los partidos en Firestore.

    Returns:
        DataFrame ordenado por puntos (descendente) con columnas:
        Nombre, Puntos, Exactos (5pts), Parciales (3pts), Penales (+2), Jugados.
    """
    # Mapa de partidos para búsqueda rápida: {partido_id: partido}
    mapa_partidos: dict[str, dict] = {p["id"]: p for p in partidos}

    filas = []

    for usuario in usuarios:
        uid = usuario.get("uid", "")
        nombre = usuario.get("nombre", "Desconocido")

        # Filtrar pronósticos de este usuario
        prons_usuario = [p for p in pronosticos if p.get("usuario_uid") == uid]

        puntos_total = 0
        exactos = 0
        parciales = 0
        penales = 0
        jugados = 0

        for pron in prons_usuario:
            partido_id = pron.get("partido_id", "")
            partido = mapa_partidos.get(partido_id, {})
            marcador_real = partido.get("marcador_real", {})
            marcador_pron = pron.get("marcador", {})

            d = desglose_puntos(marcador_pron, marcador_real, partido.get("fase"))

            # Solo contar si el partido ya tiene marcador real
            if marcador_real.get("local") is not None:
                jugados += 1
                puntos_total += d["total"]
                if d["exacto"]:
                    exactos += 1
                elif d["resultado"]:
                    parciales += 1
                if d["acierto_penales"]:
                    penales += 1

        filas.append({
            "uid": uid,
            "Nombre": nombre,
            "Puntos": puntos_total,
            "🎯 Exactos": exactos,
            "✅ Parciales": parciales,
            "🥅 Penales": penales,
            "⚽ Jugados": jugados,
        })

    columnas = ["Nombre", "Puntos", "🎯 Exactos", "✅ Parciales", "🥅 Penales", "⚽ Jugados"]
    if not filas:
        return pd.DataFrame(columns=columnas)

    df = pd.DataFrame(filas)
    df = df.sort_values("Puntos", ascending=False).reset_index(drop=True)
    df.index += 1
    df.index.name = "Pos."

    return df


def calcular_ranking_fase(
    usuarios: list[dict],
    pronosticos: list[dict],
    partidos: list[dict],
    fase: str,
) -> pd.DataFrame:
    """
    Calcula el ranking filtrado por una fase específica del torneo.

    Args:
        fase: Ej. "Grupos", "16avos", "Octavos", "Cuartos", "Semifinal", "Final".

    Returns:
        DataFrame igual que calcular_ranking() pero solo con datos de esa fase.
    """
    # Filtrar partidos de la fase
    partidos_fase = [p for p in partidos if p.get("fase") == fase]
    ids_fase = {p["id"] for p in partidos_fase}

    # Filtrar pronósticos de esa fase
    pronosticos_fase = [p for p in pronosticos if p.get("partido_id") in ids_fase]

    return calcular_ranking(usuarios, pronosticos_fase, partidos_fase)


def resumen_pronostico_usuario(
    uid: str,
    pronosticos: list[dict],
    partidos: list[dict],
) -> dict:
    """
    Calcula un resumen de puntos de un usuario específico.

    Returns:
        Dict con: puntos_total, exactos, parciales, penales, jugados.
    """
    mapa_partidos = {p["id"]: p for p in partidos}
    prons_usuario = [p for p in pronosticos if p.get("usuario_uid") == uid]

    puntos_total = 0
    exactos = 0
    parciales = 0
    penales = 0
    jugados = 0

    for pron in prons_usuario:
        partido = mapa_partidos.get(pron.get("partido_id", ""), {})
        marcador_real = partido.get("marcador_real", {})
        d = desglose_puntos(pron.get("marcador", {}), marcador_real, partido.get("fase"))

        if marcador_real.get("local") is not None:
            jugados += 1
            puntos_total += d["total"]
            if d["exacto"]:
                exactos += 1
            elif d["resultado"]:
                parciales += 1
            if d["acierto_penales"]:
                penales += 1

    return {
        "puntos_total": puntos_total,
        "exactos": exactos,
        "parciales": parciales,
        "penales": penales,
        "jugados": jugados,
        "pronosticos_registrados": len(prons_usuario),
    }
