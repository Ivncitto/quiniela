"""
seed_data.py - Cargador de datos iniciales para la Quiniela
========================================================================
Este script carga los 72 partidos de la Fase de Grupos del Mundial 2026
(12 grupos × 6 partidos) y los slots vacíos para las fases eliminatorias
en tu base de datos Firestore.

⚠️  CÓMO USAR:
  1. Asegúrate de que el archivo .streamlit/secrets.toml esté configurado.
  2. Ejecuta: python seed_data.py
  3. Solo necesitas correrlo UNA vez. Tiene protección contra duplicados.

💡 GRUPOS USADOS:
   Los grupos a continuación son orientativos. Puedes editarlos antes
   de ejecutar el script para reflejar los grupos reales del sorteo.
"""

import io
import os
import sys
from datetime import datetime
from itertools import combinations

import firebase_admin
from firebase_admin import credentials, firestore

# ─── Configuración de credenciales ───────────────────────────────────────────
# Para correr este script localmente SIN Streamlit,
# leemos el secrets.toml directamente con tomllib / toml.

def cargar_credenciales_desde_toml() -> dict:
    """Lee las credenciales desde .streamlit/secrets.toml."""
    ruta_secrets = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")

    if not os.path.exists(ruta_secrets):
        print(f"[ERROR] No se encontro el archivo: {ruta_secrets}")
        print("   Crea y configura .streamlit/secrets.toml antes de correr este script.")
        sys.exit(1)

    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # pip install tomli
        except ImportError:
            print("[ERROR] Necesitas Python 3.11+ o instalar tomli: pip install tomli")
            sys.exit(1)

    with open(ruta_secrets, "rb") as f:
        secrets = tomllib.load(f)

    return secrets


def inicializar_firebase(secrets: dict):
    """Inicializa Firebase Admin SDK."""
    if firebase_admin._apps:
        return firestore.client()

    fb = secrets["firebase"]
    cred_dict = {
        "type":                         fb["type"],
        "project_id":                   fb["project_id"],
        "private_key_id":               fb["private_key_id"],
        "private_key":                  fb["private_key"],
        "client_email":                 fb["client_email"],
        "client_id":                    fb["client_id"],
        "auth_uri":                     fb["auth_uri"],
        "token_uri":                    fb["token_uri"],
        "auth_provider_x509_cert_url":  fb.get(
            "auth_provider_x509_cert_url",
            "https://www.googleapis.com/oauth2/v1/certs"
        ),
        "client_x509_cert_url":         fb.get("client_x509_cert_url", ""),
    }
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    return firestore.client()


# ─── Datos del torneo ─────────────────────────────────────────────────────────

# Grupos del Mundial 2026
# 📝 Edita estos equipos con los resultados reales del sorteo si ya ocurrió.
GRUPOS = {
    "A": ["México", "Corea del Sur", "Sudáfrica", "Playoff D"],
    "B": ["Canadá", "Suiza", "Catar", "Playoff A"],
    "C": ["Brasil", "Marruecos", "Escocia", "Haití"],
    "D": ["EEUU", "Australia", "Paraguay", "Playoff C"],
    "E": ["Alemania", "Ecuador", "C. de Marfil", "Curaçao"],
    "F": ["Países Bajos", "Japón", "Túnez", "Playoff B"],
    "G": ["Bélgica", "Irán", "Egipto", "Nueva Zelanda"],
    "H": ["España", "Uruguay", "Arabia Saudí", "Cabo Verde"],
    "I": ["Francia", "Senegal", "Noruega", "Playoff 2"],
    "J": ["Argentina", "Austria", "Algeria", "Jordania"],
    "K": ["Portugal", "Colombia", "Uzbekistán", "Playoff 1"],
    "L": ["Inglaterra", "Croacia", "Panamá", "Ghana"]
}

# Fechas base para la fase de grupos (Mundial 2026: ~11 Jun - 2 Jul 2026)
# Se asignan de forma aproximada por jornada por grupo.
FECHA_BASE_GRUPOS = datetime(2026, 6, 11)

# Fases eliminatorias (equipos TBD = por definir)
FASES_ELIMINATORIAS = [
    {
        "fase": "16avos",
        "cantidad": 16,
        "fecha_inicio": datetime(2026, 7, 4),
    },
    {
        "fase": "Octavos",
        "cantidad": 8,
        "fecha_inicio": datetime(2026, 7, 10),
    },
    {
        "fase": "Cuartos",
        "cantidad": 4,
        "fecha_inicio": datetime(2026, 7, 15),
    },
    {
        "fase": "Semifinal",
        "cantidad": 2,
        "fecha_inicio": datetime(2026, 7, 18),
    },
    {
        "fase": "Tercer Lugar",
        "cantidad": 1,
        "fecha_inicio": datetime(2026, 7, 21),
    },
    {
        "fase": "Final",
        "cantidad": 1,
        "fecha_inicio": datetime(2026, 7, 22),
    },
]


# ─── Generación de partidos de grupos ────────────────────────────────────────

def generar_partidos_grupos() -> list[dict]:
    """
    Genera los 72 partidos de la fase de grupos.
    Cada grupo de 4 equipos genera C(4,2) = 6 partidos.
    """
    partidos = []

    for letra_grupo, equipos in GRUPOS.items():
        pares = list(combinations(equipos, 2))  # 6 combinaciones por grupo

        for i, (local, visitante) in enumerate(pares):
            # Distribuir fechas: cada jornada cada ~5 días
            jornada       = i // 2         # 0, 0, 1, 1, 2, 2  (2 partidos por día aprox)
            dias_offset   = (ord(letra_grupo) - ord("A")) + jornada * 4
            fecha_partido = datetime(
                2026,
                6,
                11 + (dias_offset % 21),  # 21 días de fase de grupos
            )

            partido_id = f"GRP-{letra_grupo}-{i + 1}"

            partidos.append({
                "id":                partido_id,
                "fase":              "Grupos",
                "grupo":             letra_grupo,
                "equipo_local":      local,
                "equipo_visitante":  visitante,
                "fecha":             fecha_partido.isoformat(),
                "bloqueado":         False,     # Abierto por defecto
                "marcador_real": {
                    "local":    None,
                    "visitante": None,
                },
            })

    return partidos


# ─── Generación de rondas eliminatorias ──────────────────────────────────────

def generar_partidos_eliminatorios() -> list[dict]:
    """
    Genera los slots vacíos para las rondas eliminatorias.
    Los equipos se llenan con "Por definir" y el admin los actualiza.
    """
    partidos = []

    for ronda in FASES_ELIMINATORIAS:
        fase     = ronda["fase"]
        cantidad = ronda["cantidad"]
        fecha_ini= ronda["fecha_inicio"]

        for i in range(cantidad):
            partido_id = f"{fase.upper().replace(' ', '-')}-{i + 1}"
            fecha = datetime(fecha_ini.year, fecha_ini.month, fecha_ini.day + (i // 2))

            partidos.append({
                "id":               partido_id,
                "fase":             fase,
                "grupo":            None,
                "equipo_local":     f"Por definir {chr(65 + i*2)}",
                "equipo_visitante": f"Por definir {chr(66 + i*2)}",
                "fecha":            fecha.isoformat(),
                "bloqueado":        True,    # Cerrado hasta que se conozcan los equipos
                "marcador_real": {
                    "local":    None,
                    "visitante": None,
                },
            })

    return partidos


# ─── Función de carga a Firestore ─────────────────────────────────────────────

def cargar_partidos(db, partidos: list[dict], forzar: bool = False):
    """
    Carga los partidos a Firestore usando batch writes.
    Si el partido ya existe y forzar=False, lo omite.

    Args:
        db:      Cliente de Firestore.
        partidos: Lista de dicts con los partidos a cargar.
        forzar:  Si True, sobreescribe partidos existentes.
    """
    col_partidos = db.collection("partidos")
    batch        = db.batch()
    cargados     = 0
    omitidos     = 0
    batch_count  = 0
    MAX_BATCH    = 400  # Firestore limita 500 ops por batch

    for partido in partidos:
        partido_id  = partido.pop("id")  # El ID va como ID del documento, no como campo
        doc_ref     = col_partidos.document(partido_id)
        doc_existente = doc_ref.get()

        if doc_existente.exists and not forzar:
            partido["id"] = partido_id  # Restaurar
            omitidos += 1
            continue

        # Añadir el id como campo también (para consultas en la app)
        partido["id"] = partido_id
        batch.set(doc_ref, partido)
        cargados    += 1
        batch_count += 1

        # Commit del batch cada MAX_BATCH operaciones
        if batch_count >= MAX_BATCH:
            batch.commit()
            batch = db.batch()
            batch_count = 0

    # Commit final
    if batch_count > 0:
        batch.commit()

    print(f"\n   [OK] Partidos cargados:  {cargados}")
    print(f"   [--] Partidos omitidos: {omitidos}")


# ─── Script principal ─────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Quiniela - Cargador de datos iniciales")
    print("  Mundial 2026")
    print("=" * 60)

    print("\nLeyendo credenciales desde .streamlit/secrets.toml...")
    secrets = cargar_credenciales_desde_toml()

    print("Conectando con Firebase Firestore...")
    db = inicializar_firebase(secrets)
    print("   Conexion exitosa.")

    print("\nGenerando partidos de Fase de Grupos (72 partidos)...")
    partidos_grupos = generar_partidos_grupos()
    print(f"   {len(partidos_grupos)} partidos generados.")

    print("\nGenerando slots de rondas eliminatorias...")
    partidos_eliminatorios = generar_partidos_eliminatorios()
    print(f"   {len(partidos_eliminatorios)} slots generados.")

    todos_los_partidos = partidos_grupos + partidos_eliminatorios
    print(f"\nTotal a cargar: {len(todos_los_partidos)} partidos.")

    respuesta = input("\nProceder con la carga? (s/n): ").strip().lower()
    if respuesta != "s":
        print("Carga cancelada.")
        return

    forzar = False
    resp_forzar = input("Sobreescribir partidos que ya existen? (s/n): ").strip().lower()
    if resp_forzar == "s":
        forzar = True
        print("Modo forzado activado.")

    print("\nCargando a Firestore...")
    cargar_partidos(db, todos_los_partidos, forzar=forzar)

    print("\n" + "=" * 60)
    print("  Carga completada exitosamente!")
    print("  Ahora puedes iniciar la app con: streamlit run app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
