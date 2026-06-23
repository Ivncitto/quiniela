"""
actualizar_resultados.py — Robot de marcadores (football-data.org → Firestore).
================================================================================
Jala los resultados del Mundial 2026 desde football-data.org y los escribe en
el documento agregado meta/partidos (de donde lee la app).

DISEÑO DE CUOTA (football-data.org Free = 10 req/min):
  - Lee la BD primero (0 llamadas a la API).
  - Solo llama a la API si hay algo de la FECHA EN CURSO que revisar:
      • un partido de hoy que ya debió terminar (kickoff + ~135 min) y aún no
        tiene marcador, o
      • un partido eliminatorio próximo (<12 h) cuyos equipos siguen "Por definir".
  - UNA sola llamada trae TODOS los partidos del rango (hoy, o hoy→mañana).
  - Nunca re-revisa partidos que ya tienen marcador.

USO:
    python actualizar_resultados.py            # modo normal (respeta el gating, escribe)
    python actualizar_resultados.py --test     # fuerza 1 llamada y muestra cambios SIN escribir (dry-run)
    python actualizar_resultados.py --forzar   # fuerza 1 llamada y escribe (ignora el gating)
    python actualizar_resultados.py --dry-run  # como normal pero sin escribir

CREDENCIALES (local o GitHub Actions):
  - Firebase:  variable de entorno FIREBASE_CREDENTIALS_JSON (JSON completo),
               o en su defecto .streamlit/secrets.toml ([firebase]).
  - Token API: variable de entorno FOOTBALL_DATA_TOKEN,
               o en su defecto .streamlit/secrets.toml ([footballdata] token).
"""

import os
import sys
import json
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

# Salida UTF-8 en Windows (sin reemplazar el objeto stdout: evita cerrar el buffer).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# Importable tanto desde la raíz del proyecto como con working-directory=quiniela
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.horario import parse_kickoff, TZ_LOCAL, DURACION_ESTIMADA_MIN  # noqa: E402

# Inglés (fuente de datos) → Español (BD). Espejo de EQUIPOS_ES en seed_real.py;
# se inlinea para no acoplar el robot con seed_real (48 equipos fijos del torneo).
EQUIPOS_ES = {
    "Mexico": "México", "South Africa": "Sudáfrica", "South Korea": "Corea del Sur",
    "Czech Republic": "Rep. Checa", "Canada": "Canadá",
    "Bosnia & Herzegovina": "Bosnia-Herzegovina", "USA": "EEUU", "Qatar": "Catar",
    "Switzerland": "Suiza", "Brazil": "Brasil", "Morocco": "Marruecos",
    "Haiti": "Haití", "Scotland": "Escocia", "Australia": "Australia",
    "Türkiye": "Turquía", "Germany": "Alemania", "Curaçao": "Curaçao",
    "Netherlands": "Países Bajos", "Japan": "Japón", "Ivory Coast": "Costa de Marfil",
    "Ecuador": "Ecuador", "Sweden": "Suecia", "Tunisia": "Túnez",
    "Spain": "España", "Cape Verde Islands": "Cabo Verde", "Belgium": "Bélgica",
    "Egypt": "Egipto", "Saudi Arabia": "Arabia Saudí", "Uruguay": "Uruguay",
    "Iran": "Irán", "New Zealand": "Nueva Zelanda", "France": "Francia",
    "Senegal": "Senegal", "Iraq": "Irak", "Norway": "Noruega",
    "Argentina": "Argentina", "Algeria": "Argelia", "Austria": "Austria",
    "Jordan": "Jordania", "Portugal": "Portugal", "Congo DR": "R.D. Congo",
    "England": "Inglaterra", "Croatia": "Croacia", "Ghana": "Ghana",
    "Panama": "Panamá", "Uzbekistan": "Uzbekistán", "Colombia": "Colombia",
    "Paraguay": "Paraguay",
}

# ── Config API ────────────────────────────────────────────────────────────────
API_BASE = "https://api.football-data.org/v4"
COMPETICION = "WC"          # FIFA World Cup
VENTANA_BRACKET_H = 12      # adelanto para rellenar equipos de eliminatorias
LOOKBACK_H = 24             # rango hacia atrás al forzar / calcular el dateFrom
POLL_MAX_H = 6              # tope: dejar de revisar un partido 6 h tras su inicio
                            # (si la API nunca lo marcó FINISHED, se captura a mano)

# stage de la API → fase de nuestra BD
_STAGE_A_FASE = {
    "GROUP_STAGE":     "Grupos",
    "LAST_32":         "16avos",
    "ROUND_OF_32":     "16avos",
    "LAST_16":         "Octavos",
    "ROUND_OF_16":     "Octavos",
    "QUARTER_FINALS":  "Cuartos",
    "QUARTER_FINAL":   "Cuartos",
    "SEMI_FINALS":     "Semifinal",
    "SEMI_FINAL":      "Semifinal",
    "THIRD_PLACE":     "Tercer Lugar",
    "FINAL":           "Final",
}


# ── Normalización / traducción de equipos ─────────────────────────────────────
def _norm(nombre: str) -> str:
    """Clave canónica: minúsculas, sin acentos, solo alfanumérico."""
    if not nombre:
        return ""
    s = unicodedata.normalize("NFKD", str(nombre))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


# Inglés (API) → Español (BD), indexado por clave normalizada.
_EN_A_ES = {_norm(en): es for en, es in EQUIPOS_ES.items()}
# Alias extra por variantes de nombre de la API observadas / probables.
for _alias_en, _es in {
    "Bosnia-Herzegovina": "Bosnia-Herzegovina",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Congo DR": "R.D. Congo",
    "DR Congo": "R.D. Congo",
    "Turkey": "Turquía",
    "Türkiye": "Turquía",
    "Cape Verde": "Cabo Verde",
    "Cabo Verde": "Cabo Verde",
    "Czechia": "Rep. Checa",
    "South Korea": "Corea del Sur",
    "Korea Republic": "Corea del Sur",
    "United States": "EEUU",
    "USA": "EEUU",
    "Ivory Coast": "Costa de Marfil",
    "Côte d'Ivoire": "Costa de Marfil",
}.items():
    _EN_A_ES[_norm(_alias_en)] = _es


def traducir(nombre_api: str) -> str:
    """Traduce el nombre de la API al español de la BD (o lo deja igual si no hay match)."""
    return _EN_A_ES.get(_norm(nombre_api), nombre_api)


def _clave_equipo(nombre_es: str) -> str:
    """Clave canónica de un equipo ya en español (BD)."""
    return _norm(nombre_es)


def _es_tbd(nombre: str) -> bool:
    n = (nombre or "").strip().lower()
    return (not n) or n.startswith("por definir") or n.startswith("tbd")


# ── Credenciales ──────────────────────────────────────────────────────────────
def _cargar_secrets_toml() -> dict:
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")
    if not os.path.exists(ruta):
        return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(ruta, "rb") as f:
        return tomllib.load(f)


def obtener_token() -> str:
    tok = os.environ.get("FOOTBALL_DATA_TOKEN")
    if tok:
        return tok.strip()
    sec = _cargar_secrets_toml()
    tok = sec.get("footballdata", {}).get("token")
    if not tok:
        print("[ERROR] No hay token. Define FOOTBALL_DATA_TOKEN o [footballdata] token en secrets.toml.")
        sys.exit(1)
    return tok.strip()


def inicializar_firestore():
    import firebase_admin
    from firebase_admin import credentials, firestore

    if firebase_admin._apps:
        return firestore.client()

    cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        sec = _cargar_secrets_toml()
        fb = sec.get("firebase")
        if not fb:
            print("[ERROR] No hay credenciales Firebase (ni FIREBASE_CREDENTIALS_JSON ni secrets.toml).")
            sys.exit(1)
        cred = credentials.Certificate({
            "type": fb["type"], "project_id": fb["project_id"],
            "private_key_id": fb["private_key_id"], "private_key": fb["private_key"],
            "client_email": fb["client_email"], "client_id": fb["client_id"],
            "auth_uri": fb["auth_uri"], "token_uri": fb["token_uri"],
            "auth_provider_x509_cert_url": fb.get("auth_provider_x509_cert_url",
                                                  "https://www.googleapis.com/oauth2/v1/certs"),
            "client_x509_cert_url": fb.get("client_x509_cert_url", ""),
        })
    firebase_admin.initialize_app(cred)
    return firestore.client()


# ── Lectura / escritura de partidos ───────────────────────────────────────────
def leer_partidos(db) -> list[dict]:
    snap = db.collection("meta").document("partidos").get()
    if not snap.exists:
        print("[ERROR] No existe meta/partidos. Siembra los datos primero.")
        sys.exit(1)
    return snap.to_dict().get("lista", []) or []


def escribir_partidos(db, lista: list[dict]) -> None:
    db.collection("meta").document("partidos").set({
        "lista": lista,
        "actualizado": datetime.now(timezone.utc).isoformat(),
    })


# ── Gating: ¿hay algo de la fecha en curso que revisar? ───────────────────────
def calcular_rango_a_revisar(partidos: list[dict], ahora: datetime):
    """
    Devuelve (necesita, date_from, date_to, razones).
    date_from/date_to en formato YYYY-MM-DD (None si no hay nada que revisar).
    """
    razones = []
    fechas = []

    fin_estimado = timedelta(minutes=DURACION_ESTIMADA_MIN)
    for p in partidos:
        k = parse_kickoff(p.get("fecha", ""))
        if k is None:
            continue
        finalizado = p.get("marcador_real", {}).get("local") is not None

        # (A) Resultado: ya pasó la hora estimada de fin y aún no hay marcador.
        #     Solo dentro de la ventana [fin_estimado, kickoff + POLL_MAX_H].
        if not finalizado and (k + fin_estimado) <= ahora <= (k + timedelta(hours=POLL_MAX_H)):
            razones.append(f"resultado pendiente: {p.get('equipo_local')} vs {p.get('equipo_visitante')}")
            fechas.append(k)

        # (B) Eliminatoria próxima con equipos por definir.
        if p.get("fase") != "Grupos":
            tbd = _es_tbd(p.get("equipo_local")) or _es_tbd(p.get("equipo_visitante"))
            if tbd and ahora <= k <= (ahora + timedelta(hours=VENTANA_BRACKET_H)):
                razones.append(f"bracket por definir: partido {p.get('id')}")
                fechas.append(k)

    if not fechas:
        return False, None, None, []

    dmin = min(fechas).astimezone(TZ_LOCAL).date()
    dmax = max(fechas).astimezone(TZ_LOCAL).date()
    return True, dmin.isoformat(), dmax.isoformat(), razones


# ── Llamada a la API ──────────────────────────────────────────────────────────
def consultar_api(token: str, date_from: str, date_to: str) -> list[dict]:
    url = f"{API_BASE}/competitions/{COMPETICION}/matches"
    params = {"dateFrom": date_from, "dateTo": date_to}
    r = requests.get(url, headers={"X-Auth-Token": token}, params=params, timeout=30)
    restantes = r.headers.get("X-Requests-Available-Minute", "?")
    print(f"[API] GET matches {date_from}..{date_to} → HTTP {r.status_code} · cuota/min restante: {restantes}")
    r.raise_for_status()
    return r.json().get("matches", [])


# ── Conciliación API ↔ BD ─────────────────────────────────────────────────────
def aplicar_cambios(partidos: list[dict], matches: list[dict]) -> list[str]:
    """Modifica `partidos` in-place según los `matches` de la API. Devuelve log de cambios."""
    cambios = []

    # Índice de partidos de grupos por par de equipos (clave canónica).
    idx_grupos = {}
    for p in partidos:
        if p.get("fase") == "Grupos":
            par = frozenset({_clave_equipo(p.get("equipo_local", "")),
                             _clave_equipo(p.get("equipo_visitante", ""))})
            idx_grupos[par] = p

    # Eliminatorias agrupadas por fase, ordenadas por fecha.
    elim_por_fase = {}
    for p in partidos:
        if p.get("fase") and p["fase"] != "Grupos":
            elim_por_fase.setdefault(p["fase"], []).append(p)
    for fase in elim_por_fase:
        elim_por_fase[fase].sort(key=lambda x: x.get("fecha", ""))

    # Emparejado de eliminatorias por ORDEN cronológico dentro de cada fase
    # (independiente de la zona horaria: la API trae UTC y la BD hora de México).
    api_elim = {}
    for m in matches:
        f = _STAGE_A_FASE.get(m.get("stage", ""))
        if f and f != "Grupos":
            api_elim.setdefault(f, []).append(m)
    slot_por_match = {}
    for fase, ms in api_elim.items():
        ms.sort(key=lambda mm: mm.get("utcDate", ""))
        db_slots = elim_por_fase.get(fase, [])
        if len(ms) != len(db_slots):
            cambios.append(f"⚠️ {fase}: API trae {len(ms)} partidos y la BD {len(db_slots)} "
                           "(revisar manualmente; no se emparejan por orden)")
        for i, mm in enumerate(ms):
            if i < len(db_slots):
                slot_por_match[id(mm)] = db_slots[i]

    for m in matches:
        stage = m.get("stage", "")
        fase = _STAGE_A_FASE.get(stage)
        home = m["homeTeam"].get("name")
        away = m["awayTeam"].get("name")
        status = m.get("status")
        ft = m.get("score", {}).get("fullTime", {})
        gh, ga = ft.get("home"), ft.get("away")
        finished = status == "FINISHED" and gh is not None and ga is not None

        home_es, away_es = traducir(home), traducir(away)

        partido = None
        if fase == "Grupos":
            par = frozenset({_clave_equipo(home_es), _clave_equipo(away_es)})
            partido = idx_grupos.get(par)
            if partido is None:
                cambios.append(f"⚠️ sin match en BD (grupos): {home}({home_es}) vs {away}({away_es})")
                continue
        elif fase:
            # Eliminatoria: slot emparejado por orden cronológico (ver arriba).
            partido = slot_por_match.get(id(m))
            if partido is None:
                continue  # desajuste de conteo: ya se avisó.
            # Rellenar equipos si están por definir.
            if not _es_tbd(home_es) and (_es_tbd(partido.get("equipo_local")) or partido.get("equipo_local") != home_es):
                if _es_tbd(partido.get("equipo_local")) or _es_tbd(partido.get("equipo_visitante")):
                    if partido.get("equipo_local") != home_es or partido.get("equipo_visitante") != away_es:
                        partido["equipo_local"] = home_es
                        partido["equipo_visitante"] = away_es
                        cambios.append(f"🔵 {fase}: equipos → {home_es} vs {away_es}")
        else:
            cambios.append(f"⚠️ stage desconocido '{stage}' ({home} vs {away})")
            continue

        # Escribir marcador (orientado a local/visitante de la BD).
        if finished:
            cl = _clave_equipo(partido.get("equipo_local", ""))
            if cl == _clave_equipo(home_es):
                local, visit = gh, ga
            elif cl == _clave_equipo(away_es):
                local, visit = ga, gh   # estaban invertidos respecto a la BD
            else:
                local, visit = gh, ga   # eliminatoria recién rellenada con orden de la API

            mr = partido.get("marcador_real", {})
            if mr.get("local") != local or mr.get("visitante") != visit:
                partido["marcador_real"] = {"local": int(local), "visitante": int(visit)}
                cambios.append(f"✅ {partido.get('equipo_local')} {local}–{visit} {partido.get('equipo_visitante')}")

    return cambios


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    test    = "--test"    in sys.argv
    forzar  = "--forzar"  in sys.argv or test
    dry_run = "--dry-run" in sys.argv or test

    print("=" * 60)
    print("  Robot de marcadores · football-data.org → Firestore")
    print("=" * 60)

    token = obtener_token()
    db = inicializar_firestore()
    partidos = leer_partidos(db)
    ahora = datetime.now(timezone.utc)
    print(f"  Partidos en BD: {len(partidos)} · ahora(UTC): {ahora.isoformat(timespec='seconds')}")

    if forzar:
        # Rango: ayer→mañana (local) para cubrir resultados y bracket.
        dfrom = (ahora.astimezone(TZ_LOCAL) - timedelta(hours=LOOKBACK_H)).date().isoformat()
        dto   = (ahora.astimezone(TZ_LOCAL) + timedelta(hours=VENTANA_BRACKET_H)).date().isoformat()
        razones = ["(forzado)"]
    else:
        necesita, dfrom, dto, razones = calcular_rango_a_revisar(partidos, ahora)
        if not necesita:
            print("  ⏸️  Nada que revisar de la fecha en curso. 0 llamadas a la API.")
            return

    print(f"  Motivos ({len(razones)}): " + "; ".join(razones[:5]) + ("..." if len(razones) > 5 else ""))

    matches = consultar_api(token, dfrom, dto)
    print(f"  Partidos recibidos de la API: {len(matches)}")

    cambios = aplicar_cambios(partidos, matches)

    if not cambios:
        print("  Sin cambios respecto a la BD.")
        return

    print("\n  Cambios detectados:")
    for c in cambios:
        print("   " + c)

    if dry_run:
        print("\n  🧪 DRY-RUN: no se escribió nada en Firestore.")
    else:
        escribir_partidos(db, partidos)
        print(f"\n  💾 Guardado en meta/partidos ({len(cambios)} cambios).")


if __name__ == "__main__":
    main()
