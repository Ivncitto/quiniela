"""
seed_real.py — Mundial 2026: carga los 104 partidos reales a Firestore.
Equipos en español, fases y grupos correctos.

Uso:
    python seed_real.py              # Solo agrega nuevos (omite existentes)
    python seed_real.py --forzar     # Sobreescribe existentes
    python seed_real.py --limpiar    # Borra TODOS los partidos y recarga
"""
import io, os, sys
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── Imports de seed_data para reutilizar credenciales ────────────────────────
from seed_data import cargar_credenciales_desde_toml, inicializar_firebase


# ── Traducciones de equipos ───────────────────────────────────────────────────
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

CIUDADES_ES = {"Mexico City": "Ciudad de México"}

# ── Equipo → Grupo (Sorteo real Mundial 2026) ─────────────────────────────────
EQUIPO_A_GRUPO = {
    "México": "A", "Corea del Sur": "A", "Sudáfrica": "A", "Rep. Checa": "A",
    "Canadá": "B", "Suiza": "B", "Catar": "B", "Bosnia-Herzegovina": "B",
    "Brasil": "C", "Marruecos": "C", "Escocia": "C", "Haití": "C",
    "EEUU": "D", "Australia": "D", "Paraguay": "D", "Turquía": "D",
    "Alemania": "E", "Ecuador": "E", "Costa de Marfil": "E", "Curaçao": "E",
    "Países Bajos": "F", "Japón": "F", "Túnez": "F", "Suecia": "F",
    "Bélgica": "G", "Irán": "G", "Egipto": "G", "Nueva Zelanda": "G",
    "España": "H", "Uruguay": "H", "Arabia Saudí": "H", "Cabo Verde": "H",
    "Francia": "I", "Senegal": "I", "Noruega": "I", "Irak": "I",
    "Argentina": "J", "Austria": "J", "Argelia": "J", "Jordania": "J",
    "Portugal": "K", "Colombia": "K", "Uzbekistán": "K", "R.D. Congo": "K",
    "Inglaterra": "L", "Croacia": "L", "Panamá": "L", "Ghana": "L",
}


def tr(nombre: str) -> str:
    """Traduce nombre de equipo al español. TBD → 'Por definir'."""
    if not nombre or nombre.upper().startswith("TBD"):
        return "Por definir"
    return EQUIPOS_ES.get(nombre, nombre)


def determinar_fase_grupo(raw: dict) -> tuple:
    md = raw.get("matchday")
    home_raw = raw.get("homeTeam", "")

    if md in (1, 2, 3):
        local_es = tr(home_raw)
        grupo = EQUIPO_A_GRUPO.get(local_es) or EQUIPO_A_GRUPO.get(tr(raw.get("awayTeam", "")))
        return "Grupos", grupo, md

    hl = home_raw.lower()
    if "round of 32" in hl:   return "16avos", None, None
    if "round of 16" in hl:   return "Octavos", None, None
    if "quarter-final" in hl: return "Cuartos", None, None
    if "semi-final" in hl:    return "Semifinal", None, None
    if "3rd place" in hl:     return "Tercer Lugar", None, None
    if "final" in hl:         return "Final", None, None
    return "Desconocida", None, None


def procesar(raw: dict) -> dict:
    fase, grupo, jornada = determinar_fase_grupo(raw)
    fecha_str = raw.get("date", "2026-01-01")
    hora_str  = raw.get("time", "00:00")
    try:
        fecha_iso = datetime.fromisoformat(f"{fecha_str}T{hora_str}:00").isoformat()
    except Exception:
        fecha_iso = fecha_str

    ciudad  = CIUDADES_ES.get(raw.get("city", ""), raw.get("city", ""))
    estadio = raw.get("stadium", "")

    return {
        "id":               f"WC26-{raw['id']}",
        "fase":             fase,
        "grupo":            grupo,
        "jornada":          jornada,
        "equipo_local":     tr(raw.get("homeTeam", "")),
        "equipo_visitante": tr(raw.get("awayTeam", "")),
        "fecha":            fecha_iso,
        "ciudad":           ciudad,
        "estadio":          estadio,
        "bloqueado":        fase != "Grupos",   # Grupos abiertos, resto bloqueado
        "marcador_real":    {"local": None, "visitante": None},
    }


# ── Datos reales del Mundial 2026 ─────────────────────────────────────────────
PARTIDOS_RAW = [
    # ─── Jornada 1 ───
    {"id":104456,"matchday":1,"date":"2026-06-11","time":"19:00","homeTeam":"Mexico","awayTeam":"South Africa","city":"Mexico City","stadium":"Estadio Banorte"},
    {"id":165651,"matchday":1,"date":"2026-06-12","time":"02:00","homeTeam":"South Korea","awayTeam":"Czech Republic","city":"Zapopan","stadium":"Estadio Akron"},
    {"id":165652,"matchday":1,"date":"2026-06-12","time":"19:00","homeTeam":"Canada","awayTeam":"Bosnia & Herzegovina","city":"Toronto","stadium":"BMO Field"},
    {"id":104457,"matchday":1,"date":"2026-06-13","time":"01:00","homeTeam":"USA","awayTeam":"Paraguay","city":"Inglewood, California","stadium":"SoFi Stadium"},
    {"id":104460,"matchday":1,"date":"2026-06-13","time":"19:00","homeTeam":"Qatar","awayTeam":"Switzerland","city":"","stadium":""},
    {"id":104458,"matchday":1,"date":"2026-06-13","time":"22:00","homeTeam":"Brazil","awayTeam":"Morocco","city":"East Rutherford, Nueva Jersey","stadium":"MetLife Stadium"},
    {"id":104459,"matchday":1,"date":"2026-06-14","time":"01:00","homeTeam":"Haiti","awayTeam":"Scotland","city":"Foxborough","stadium":"Gillette Stadium"},
    {"id":165653,"matchday":1,"date":"2026-06-14","time":"04:00","homeTeam":"Australia","awayTeam":"Türkiye","city":"Vancouver","stadium":"BC Place"},
    {"id":104461,"matchday":1,"date":"2026-06-14","time":"17:00","homeTeam":"Germany","awayTeam":"Curaçao","city":"Houston, Texas","stadium":"NRG Stadium"},
    {"id":104463,"matchday":1,"date":"2026-06-14","time":"20:00","homeTeam":"Netherlands","awayTeam":"Japan","city":"","stadium":""},
    {"id":104462,"matchday":1,"date":"2026-06-14","time":"23:00","homeTeam":"Ivory Coast","awayTeam":"Ecuador","city":"Philadelphia, Pensilvania","stadium":"Lincoln Financial Field"},
    {"id":165654,"matchday":1,"date":"2026-06-15","time":"02:00","homeTeam":"Sweden","awayTeam":"Tunisia","city":"Monterrey","stadium":"Estadio BBVA"},
    {"id":104467,"matchday":1,"date":"2026-06-15","time":"16:00","homeTeam":"Spain","awayTeam":"Cape Verde Islands","city":"Atlanta","stadium":"Mercedes-Benz Stadium"},
    {"id":104464,"matchday":1,"date":"2026-06-15","time":"19:00","homeTeam":"Belgium","awayTeam":"Egypt","city":"Seattle","stadium":"Lumen Field"},
    {"id":104466,"matchday":1,"date":"2026-06-15","time":"22:00","homeTeam":"Saudi Arabia","awayTeam":"Uruguay","city":"Miami Gardens, Florida","stadium":"Hard Rock Stadium"},
    {"id":104465,"matchday":1,"date":"2026-06-16","time":"01:00","homeTeam":"Iran","awayTeam":"New Zealand","city":"Inglewood, California","stadium":"SoFi Stadium"},
    {"id":104470,"matchday":1,"date":"2026-06-16","time":"19:00","homeTeam":"France","awayTeam":"Senegal","city":"East Rutherford, Nueva Jersey","stadium":"MetLife Stadium"},
    {"id":165655,"matchday":1,"date":"2026-06-16","time":"22:00","homeTeam":"Iraq","awayTeam":"Norway","city":"Foxborough","stadium":"Gillette Stadium"},
    {"id":104468,"matchday":1,"date":"2026-06-17","time":"01:00","homeTeam":"Argentina","awayTeam":"Algeria","city":"Kansas City, Misuri","stadium":"Arrowhead Stadium"},
    {"id":104469,"matchday":1,"date":"2026-06-17","time":"04:00","homeTeam":"Austria","awayTeam":"Jordan","city":"","stadium":""},
    {"id":165656,"matchday":1,"date":"2026-06-17","time":"17:00","homeTeam":"Portugal","awayTeam":"Congo DR","city":"Houston, Texas","stadium":"NRG Stadium"},
    {"id":104471,"matchday":1,"date":"2026-06-17","time":"20:00","homeTeam":"England","awayTeam":"Croatia","city":"","stadium":""},
    {"id":104472,"matchday":1,"date":"2026-06-17","time":"23:00","homeTeam":"Ghana","awayTeam":"Panama","city":"Toronto","stadium":"BMO Field"},
    {"id":104473,"matchday":1,"date":"2026-06-18","time":"02:00","homeTeam":"Uzbekistan","awayTeam":"Colombia","city":"Mexico City","stadium":"Estadio Azteca"},
    # ─── Jornada 2 ───
    {"id":165657,"matchday":2,"date":"2026-06-18","time":"16:00","homeTeam":"Czech Republic","awayTeam":"South Africa","city":"Atlanta","stadium":"Mercedes-Benz Stadium"},
    {"id":165658,"matchday":2,"date":"2026-06-18","time":"19:00","homeTeam":"Switzerland","awayTeam":"Bosnia & Herzegovina","city":"Inglewood, California","stadium":"SoFi Stadium"},
    {"id":104474,"matchday":2,"date":"2026-06-18","time":"22:00","homeTeam":"Canada","awayTeam":"Qatar","city":"Vancouver","stadium":"BC Place"},
    {"id":104475,"matchday":2,"date":"2026-06-19","time":"01:00","homeTeam":"Mexico","awayTeam":"South Korea","city":"Zapopan","stadium":"Estadio Akron"},
    {"id":104478,"matchday":2,"date":"2026-06-19","time":"19:00","homeTeam":"USA","awayTeam":"Australia","city":"Seattle","stadium":"Lumen Field"},
    {"id":104477,"matchday":2,"date":"2026-06-19","time":"22:00","homeTeam":"Scotland","awayTeam":"Morocco","city":"Foxborough","stadium":"Gillette Stadium"},
    {"id":104476,"matchday":2,"date":"2026-06-20","time":"00:30","homeTeam":"Brazil","awayTeam":"Haiti","city":"Philadelphia, Pensilvania","stadium":"Lincoln Financial Field"},
    {"id":165659,"matchday":2,"date":"2026-06-20","time":"03:00","homeTeam":"Türkiye","awayTeam":"Paraguay","city":"","stadium":""},
    {"id":165660,"matchday":2,"date":"2026-06-20","time":"17:00","homeTeam":"Netherlands","awayTeam":"Sweden","city":"Houston, Texas","stadium":"NRG Stadium"},
    {"id":104480,"matchday":2,"date":"2026-06-20","time":"20:00","homeTeam":"Germany","awayTeam":"Ivory Coast","city":"Toronto","stadium":"BMO Field"},
    {"id":104479,"matchday":2,"date":"2026-06-21","time":"00:00","homeTeam":"Ecuador","awayTeam":"Curaçao","city":"Kansas City, Misuri","stadium":"Arrowhead Stadium"},
    {"id":104481,"matchday":2,"date":"2026-06-21","time":"04:00","homeTeam":"Tunisia","awayTeam":"Japan","city":"Monterrey","stadium":"Estadio BBVA"},
    {"id":104484,"matchday":2,"date":"2026-06-21","time":"16:00","homeTeam":"Spain","awayTeam":"Saudi Arabia","city":"Atlanta","stadium":"Mercedes-Benz Stadium"},
    {"id":104482,"matchday":2,"date":"2026-06-21","time":"19:00","homeTeam":"Belgium","awayTeam":"Iran","city":"Inglewood, California","stadium":"SoFi Stadium"},
    {"id":104485,"matchday":2,"date":"2026-06-21","time":"22:00","homeTeam":"Uruguay","awayTeam":"Cape Verde Islands","city":"Miami Gardens, Florida","stadium":"Hard Rock Stadium"},
    {"id":104483,"matchday":2,"date":"2026-06-22","time":"01:00","homeTeam":"New Zealand","awayTeam":"Egypt","city":"Vancouver","stadium":"BC Place"},
    {"id":104486,"matchday":2,"date":"2026-06-22","time":"17:00","homeTeam":"Argentina","awayTeam":"Austria","city":"","stadium":""},
    {"id":165661,"matchday":2,"date":"2026-06-22","time":"21:00","homeTeam":"France","awayTeam":"Iraq","city":"Philadelphia, Pensilvania","stadium":"Lincoln Financial Field"},
    {"id":104488,"matchday":2,"date":"2026-06-23","time":"00:00","homeTeam":"Norway","awayTeam":"Senegal","city":"East Rutherford, Nueva Jersey","stadium":"MetLife Stadium"},
    {"id":104487,"matchday":2,"date":"2026-06-23","time":"03:00","homeTeam":"Jordan","awayTeam":"Algeria","city":"","stadium":""},
    {"id":104491,"matchday":2,"date":"2026-06-23","time":"17:00","homeTeam":"Portugal","awayTeam":"Uzbekistan","city":"Houston, Texas","stadium":"NRG Stadium"},
    {"id":104489,"matchday":2,"date":"2026-06-23","time":"20:00","homeTeam":"England","awayTeam":"Ghana","city":"Foxborough","stadium":"Gillette Stadium"},
    {"id":104490,"matchday":2,"date":"2026-06-23","time":"23:00","homeTeam":"Panama","awayTeam":"Croatia","city":"Toronto","stadium":"BMO Field"},
    {"id":165662,"matchday":2,"date":"2026-06-24","time":"02:00","homeTeam":"Colombia","awayTeam":"Congo DR","city":"Zapopan","stadium":"Estadio Akron"},
    # ─── Jornada 3 ───
    {"id":104495,"matchday":3,"date":"2026-06-24","time":"19:00","homeTeam":"Switzerland","awayTeam":"Canada","city":"Vancouver","stadium":"BC Place"},
    {"id":165663,"matchday":3,"date":"2026-06-24","time":"19:00","homeTeam":"Bosnia & Herzegovina","awayTeam":"Qatar","city":"Seattle","stadium":"Lumen Field"},
    {"id":104492,"matchday":3,"date":"2026-06-24","time":"22:00","homeTeam":"Morocco","awayTeam":"Haiti","city":"Atlanta","stadium":"Mercedes-Benz Stadium"},
    {"id":104493,"matchday":3,"date":"2026-06-24","time":"22:00","homeTeam":"Scotland","awayTeam":"Brazil","city":"Miami Gardens, Florida","stadium":"Hard Rock Stadium"},
    {"id":104494,"matchday":3,"date":"2026-06-25","time":"01:00","homeTeam":"South Africa","awayTeam":"South Korea","city":"Monterrey","stadium":"Estadio BBVA"},
    {"id":165664,"matchday":3,"date":"2026-06-25","time":"01:00","homeTeam":"Czech Republic","awayTeam":"Mexico","city":"Mexico City","stadium":"Estadio Azteca"},
    {"id":104496,"matchday":3,"date":"2026-06-25","time":"20:00","homeTeam":"Curaçao","awayTeam":"Ivory Coast","city":"Philadelphia, Pensilvania","stadium":"Lincoln Financial Field"},
    {"id":104497,"matchday":3,"date":"2026-06-25","time":"20:00","homeTeam":"Ecuador","awayTeam":"Germany","city":"East Rutherford, Nueva Jersey","stadium":"MetLife Stadium"},
    {"id":104499,"matchday":3,"date":"2026-06-25","time":"23:00","homeTeam":"Tunisia","awayTeam":"Netherlands","city":"Kansas City, Misuri","stadium":"Arrowhead Stadium"},
    {"id":165665,"matchday":3,"date":"2026-06-25","time":"23:00","homeTeam":"Japan","awayTeam":"Sweden","city":"","stadium":""},
    {"id":104498,"matchday":3,"date":"2026-06-26","time":"02:00","homeTeam":"Paraguay","awayTeam":"Australia","city":"","stadium":""},
    {"id":165666,"matchday":3,"date":"2026-06-26","time":"02:00","homeTeam":"Türkiye","awayTeam":"USA","city":"Inglewood, California","stadium":"SoFi Stadium"},
    {"id":104503,"matchday":3,"date":"2026-06-26","time":"19:00","homeTeam":"Norway","awayTeam":"France","city":"Foxborough","stadium":"Gillette Stadium"},
    {"id":165667,"matchday":3,"date":"2026-06-26","time":"19:00","homeTeam":"Senegal","awayTeam":"Iraq","city":"Toronto","stadium":"BMO Field"},
    {"id":104500,"matchday":3,"date":"2026-06-27","time":"00:00","homeTeam":"Cape Verde Islands","awayTeam":"Saudi Arabia","city":"Houston, Texas","stadium":"NRG Stadium"},
    {"id":104504,"matchday":3,"date":"2026-06-27","time":"00:00","homeTeam":"Uruguay","awayTeam":"Spain","city":"Zapopan","stadium":"Estadio Akron"},
    {"id":104501,"matchday":3,"date":"2026-06-27","time":"03:00","homeTeam":"Egypt","awayTeam":"Iran","city":"Seattle","stadium":"Lumen Field"},
    {"id":104502,"matchday":3,"date":"2026-06-27","time":"03:00","homeTeam":"New Zealand","awayTeam":"Belgium","city":"Vancouver","stadium":"BC Place"},
    {"id":104507,"matchday":3,"date":"2026-06-27","time":"21:00","homeTeam":"Croatia","awayTeam":"Ghana","city":"Philadelphia, Pensilvania","stadium":"Lincoln Financial Field"},
    {"id":104509,"matchday":3,"date":"2026-06-27","time":"21:00","homeTeam":"Panama","awayTeam":"England","city":"East Rutherford, Nueva Jersey","stadium":"MetLife Stadium"},
    {"id":104506,"matchday":3,"date":"2026-06-27","time":"23:30","homeTeam":"Colombia","awayTeam":"Portugal","city":"Miami Gardens, Florida","stadium":"Hard Rock Stadium"},
    {"id":165668,"matchday":3,"date":"2026-06-27","time":"23:30","homeTeam":"Congo DR","awayTeam":"Uzbekistan","city":"Atlanta","stadium":"Mercedes-Benz Stadium"},
    {"id":104505,"matchday":3,"date":"2026-06-28","time":"02:00","homeTeam":"Algeria","awayTeam":"Austria","city":"Kansas City, Misuri","stadium":"Arrowhead Stadium"},
    {"id":104508,"matchday":3,"date":"2026-06-28","time":"02:00","homeTeam":"Jordan","awayTeam":"Argentina","city":"","stadium":""},
    # ─── 16avos ───
    {"id":160042,"matchday":None,"date":"2026-06-28","time":"19:00","homeTeam":"TBD Home (Round of 32 #1)","awayTeam":"TBD Away (Round of 32 #1)","city":"","stadium":""},
    {"id":160043,"matchday":None,"date":"2026-06-29","time":"17:00","homeTeam":"TBD Home (Round of 32 #2)","awayTeam":"TBD Away (Round of 32 #2)","city":"","stadium":""},
    {"id":160044,"matchday":None,"date":"2026-06-29","time":"20:30","homeTeam":"TBD Home (Round of 32 #3)","awayTeam":"TBD Away (Round of 32 #3)","city":"","stadium":""},
    {"id":160045,"matchday":None,"date":"2026-06-30","time":"01:00","homeTeam":"TBD Home (Round of 32 #4)","awayTeam":"TBD Away (Round of 32 #4)","city":"","stadium":""},
    {"id":160046,"matchday":None,"date":"2026-06-30","time":"17:00","homeTeam":"TBD Home (Round of 32 #5)","awayTeam":"TBD Away (Round of 32 #5)","city":"","stadium":""},
    {"id":160047,"matchday":None,"date":"2026-06-30","time":"21:00","homeTeam":"TBD Home (Round of 32 #6)","awayTeam":"TBD Away (Round of 32 #6)","city":"","stadium":""},
    {"id":160048,"matchday":None,"date":"2026-07-01","time":"01:00","homeTeam":"TBD Home (Round of 32 #7)","awayTeam":"TBD Away (Round of 32 #7)","city":"","stadium":""},
    {"id":160049,"matchday":None,"date":"2026-07-01","time":"16:00","homeTeam":"TBD Home (Round of 32 #8)","awayTeam":"TBD Away (Round of 32 #8)","city":"","stadium":""},
    {"id":160050,"matchday":None,"date":"2026-07-01","time":"20:00","homeTeam":"TBD Home (Round of 32 #9)","awayTeam":"TBD Away (Round of 32 #9)","city":"","stadium":""},
    {"id":160051,"matchday":None,"date":"2026-07-02","time":"00:00","homeTeam":"TBD Home (Round of 32 #10)","awayTeam":"TBD Away (Round of 32 #10)","city":"","stadium":""},
    {"id":160052,"matchday":None,"date":"2026-07-02","time":"19:00","homeTeam":"TBD Home (Round of 32 #11)","awayTeam":"TBD Away (Round of 32 #11)","city":"","stadium":""},
    {"id":160053,"matchday":None,"date":"2026-07-02","time":"23:00","homeTeam":"TBD Home (Round of 32 #12)","awayTeam":"TBD Away (Round of 32 #12)","city":"","stadium":""},
    {"id":160054,"matchday":None,"date":"2026-07-03","time":"03:00","homeTeam":"TBD Home (Round of 32 #13)","awayTeam":"TBD Away (Round of 32 #13)","city":"","stadium":""},
    {"id":160055,"matchday":None,"date":"2026-07-03","time":"18:00","homeTeam":"TBD Home (Round of 32 #14)","awayTeam":"TBD Away (Round of 32 #14)","city":"","stadium":""},
    {"id":160056,"matchday":None,"date":"2026-07-03","time":"22:00","homeTeam":"TBD Home (Round of 32 #15)","awayTeam":"TBD Away (Round of 32 #15)","city":"","stadium":""},
    {"id":160057,"matchday":None,"date":"2026-07-04","time":"01:30","homeTeam":"TBD Home (Round of 32 #16)","awayTeam":"TBD Away (Round of 32 #16)","city":"","stadium":""},
    # ─── Octavos ───
    {"id":160058,"matchday":None,"date":"2026-07-04","time":"17:00","homeTeam":"TBD Home (Round of 16 #1)","awayTeam":"TBD Away (Round of 16 #1)","city":"","stadium":""},
    {"id":160059,"matchday":None,"date":"2026-07-04","time":"21:00","homeTeam":"TBD Home (Round of 16 #2)","awayTeam":"TBD Away (Round of 16 #2)","city":"","stadium":""},
    {"id":160060,"matchday":None,"date":"2026-07-05","time":"20:00","homeTeam":"TBD Home (Round of 16 #3)","awayTeam":"TBD Away (Round of 16 #3)","city":"","stadium":""},
    {"id":160061,"matchday":None,"date":"2026-07-06","time":"00:00","homeTeam":"TBD Home (Round of 16 #4)","awayTeam":"TBD Away (Round of 16 #4)","city":"","stadium":""},
    {"id":160062,"matchday":None,"date":"2026-07-06","time":"19:00","homeTeam":"TBD Home (Round of 16 #5)","awayTeam":"TBD Away (Round of 16 #5)","city":"","stadium":""},
    {"id":160063,"matchday":None,"date":"2026-07-07","time":"00:00","homeTeam":"TBD Home (Round of 16 #6)","awayTeam":"TBD Away (Round of 16 #6)","city":"","stadium":""},
    {"id":160064,"matchday":None,"date":"2026-07-07","time":"16:00","homeTeam":"TBD Home (Round of 16 #7)","awayTeam":"TBD Away (Round of 16 #7)","city":"","stadium":""},
    {"id":160065,"matchday":None,"date":"2026-07-07","time":"20:00","homeTeam":"TBD Home (Round of 16 #8)","awayTeam":"TBD Away (Round of 16 #8)","city":"","stadium":""},
    # ─── Cuartos ───
    {"id":160066,"matchday":None,"date":"2026-07-09","time":"20:00","homeTeam":"TBD Home (Quarter-finals #1)","awayTeam":"TBD Away (Quarter-finals #1)","city":"","stadium":""},
    {"id":160067,"matchday":None,"date":"2026-07-10","time":"19:00","homeTeam":"TBD Home (Quarter-finals #2)","awayTeam":"TBD Away (Quarter-finals #2)","city":"","stadium":""},
    {"id":160068,"matchday":None,"date":"2026-07-11","time":"21:00","homeTeam":"TBD Home (Quarter-finals #3)","awayTeam":"TBD Away (Quarter-finals #3)","city":"","stadium":""},
    {"id":160069,"matchday":None,"date":"2026-07-12","time":"01:00","homeTeam":"TBD Home (Quarter-finals #4)","awayTeam":"TBD Away (Quarter-finals #4)","city":"","stadium":""},
    # ─── Semifinal ───
    {"id":160070,"matchday":None,"date":"2026-07-14","time":"19:00","homeTeam":"TBD Home (Semi-finals #1)","awayTeam":"TBD Away (Semi-finals #1)","city":"","stadium":""},
    {"id":160071,"matchday":None,"date":"2026-07-15","time":"19:00","homeTeam":"TBD Home (Semi-finals #2)","awayTeam":"TBD Away (Semi-finals #2)","city":"","stadium":""},
    # ─── Tercer Lugar ───
    {"id":160072,"matchday":None,"date":"2026-07-18","time":"21:00","homeTeam":"TBD Home (3rd Place Final #1)","awayTeam":"TBD Away (3rd Place Final #1)","city":"","stadium":""},
    # ─── Final ───
    {"id":160073,"matchday":None,"date":"2026-07-19","time":"19:00","homeTeam":"TBD Home (Final #1)","awayTeam":"TBD Away (Final #1)","city":"","stadium":""},
]


# ── Firestore helpers ─────────────────────────────────────────────────────────

def limpiar_partidos(db) -> int:
    """Elimina TODOS los documentos de la colección 'partidos'."""
    col = db.collection("partidos")
    docs = list(col.stream())
    batch = db.batch()
    count = 0
    for doc in docs:
        batch.delete(doc.reference)
        count += 1
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()
    if count % 400 != 0:
        batch.commit()
    return count


def cargar_partidos(db, partidos: list[dict], forzar: bool = False):
    col = db.collection("partidos")
    batch = db.batch()
    cargados = omitidos = batch_count = 0
    MAX = 400

    for p in partidos:
        doc_id = p.pop("id")
        ref    = col.document(doc_id)
        p["id"] = doc_id

        if not forzar and ref.get().exists:
            omitidos += 1
            continue

        batch.set(ref, p)
        cargados    += 1
        batch_count += 1
        if batch_count >= MAX:
            batch.commit()
            batch = db.batch()
            batch_count = 0

    if batch_count > 0:
        batch.commit()

    print(f"   [OK] Cargados : {cargados}")
    print(f"   [--] Omitidos : {omitidos}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    forzar  = "--forzar"  in sys.argv
    limpiar = "--limpiar" in sys.argv

    print("=" * 55)
    print("  Mundial 2026 - Carga de partidos reales")
    print("=" * 55)

    print("\n[1/3] Conectando con Firestore...")
    secrets = cargar_credenciales_desde_toml()
    db      = inicializar_firebase(secrets)
    print("      OK.")

    if limpiar:
        print("\n[2/3] Limpiando coleccion 'partidos'...")
        n = limpiar_partidos(db)
        print(f"      {n} documentos eliminados.")
        forzar = True  # Si limpiamos, siempre cargamos todo
    else:
        print("\n[2/3] Modo: " + ("FORZAR (sobreescribe)" if forzar else "solo nuevos"))

    print(f"\n[3/3] Cargando {len(PARTIDOS_RAW)} partidos...")
    partidos = [procesar(raw.copy()) for raw in PARTIDOS_RAW]
    cargar_partidos(db, partidos, forzar=forzar)

    print("\n" + "=" * 55)
    print("  Partidos cargados. Recarga la app en el navegador.")
    print("=" * 55)


if __name__ == "__main__":
    main()
