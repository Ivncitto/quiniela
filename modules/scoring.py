"""
Módulo de cálculo de puntuación de la Quiniela.

Sistema de puntuación:
  - 3 puntos: Marcador exacto correcto.
  - 1 punto:  Resultado correcto (local/empate/visitante) pero marcador diferente.
  - 0 puntos: Resultado incorrecto o sin pronóstico.

Toda la lógica de negocio está centralizada aquí para facilitar
pruebas unitarias y mantenimiento.
"""

import pandas as pd


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

def calcular_puntos(pronostico: dict, marcador_real: dict) -> int:
    """
    Calcula los puntos obtenidos por un pronóstico dado el marcador real.

    Args:
        pronostico:    {"local": int, "visitante": int}
        marcador_real: {"local": int | None, "visitante": int | None}

    Returns:
        0, 1 o 3 puntos. Retorna 0 si el partido aún no tiene marcador real.
    """
    # Si no hay marcador real, no se pueden calcular puntos aún
    real_local = marcador_real.get("local")
    real_visitante = marcador_real.get("visitante")

    if real_local is None or real_visitante is None:
        return 0

    pron_local = pronostico.get("local")
    pron_visitante = pronostico.get("visitante")

    # Sin pronóstico registrado
    if pron_local is None or pron_visitante is None:
        return 0

    # ── 3 puntos: Marcador exacto ─────────────────────────────────────────────
    if pron_local == real_local and pron_visitante == real_visitante:
        return 5

    # ── 1 punto: Resultado correcto ───────────────────────────────────────────
    if _resultado(pron_local, pron_visitante) == _resultado(real_local, real_visitante):
        return 3

    # ── 0 puntos: Sin acierto ─────────────────────────────────────────────────
    return 0


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
        Nombre, Puntos, Exactos (3pts), Parciales (1pt), Jugados.
    """
    # Mapa de partidos para búsqueda rápida: {partido_id: marcador_real}
    mapa_partidos: dict[str, dict] = {
        p["id"]: p.get("marcador_real", {})
        for p in partidos
    }

    filas = []

    for usuario in usuarios:
        uid = usuario.get("uid", "")
        nombre = usuario.get("nombre", "Desconocido")

        # Filtrar pronósticos de este usuario
        prons_usuario = [p for p in pronosticos if p.get("usuario_uid") == uid]

        puntos_total = 0
        exactos = 0
        parciales = 0
        jugados = 0

        for pron in prons_usuario:
            partido_id = pron.get("partido_id", "")
            marcador_real = mapa_partidos.get(partido_id, {})
            marcador_pron = pron.get("marcador", {})

            pts = calcular_puntos(marcador_pron, marcador_real)

            # Solo contar si el partido ya tiene marcador real
            if marcador_real.get("local") is not None:
                jugados += 1
                puntos_total += pts
                if pts == 3:
                    exactos += 1
                elif pts == 1:
                    parciales += 1

        filas.append({
            "uid": uid,
            "Nombre": nombre,
            "Puntos": puntos_total,
            "🎯 Exactos": exactos,
            "✅ Parciales": parciales,
            "⚽ Jugados": jugados,
        })

    if not filas:
        return pd.DataFrame(columns=["Nombre", "Puntos", "🎯 Exactos", "✅ Parciales", "⚽ Jugados"])

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
        Dict con: puntos_total, exactos, parciales, jugados, pendientes.
    """
    mapa_partidos = {p["id"]: p for p in partidos}
    prons_usuario = [p for p in pronosticos if p.get("usuario_uid") == uid]

    puntos_total = 0
    exactos = 0
    parciales = 0
    jugados = 0

    for pron in prons_usuario:
        partido = mapa_partidos.get(pron.get("partido_id", ""), {})
        marcador_real = partido.get("marcador_real", {})
        pts = calcular_puntos(pron.get("marcador", {}), marcador_real)

        if marcador_real.get("local") is not None:
            jugados += 1
            puntos_total += pts
            if pts == 3:
                exactos += 1
            elif pts == 1:
                parciales += 1

    return {
        "puntos_total": puntos_total,
        "exactos": exactos,
        "parciales": parciales,
        "jugados": jugados,
        "pronosticos_registrados": len(prons_usuario),
    }
