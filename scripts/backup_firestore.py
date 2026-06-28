"""
backup_firestore.py — Respaldo y restauración de la quiniela (Firestore).
================================================================================
Crea un respaldo COMPLETO (con fecha/hora) de todo lo que importa de la quiniela
y puede restaurarlo si algo sale mal. Pensado para correr ANTES de cada ronda de
eliminatorias (16avos, Octavos, …), donde el robot rellena cruces por orden.

QUÉ RESPALDA (una lectura por documento):
  - meta/partidos        → partidos + marcadores reales (lo que escribe el robot)
  - pronosticos/{uid}    → los pronósticos de CADA persona (el robot NO los toca,
                           pero se incluyen para tener un snapshot completo)
  - usuarios/{uid}        → perfiles de participantes

USO:
    # Respaldar (lo normal antes de los 16avos):
    python scripts/backup_firestore.py
        → guarda backups/quiniela_backup_AAAAMMDD_HHMMSS.json

    # Ver qué hay dentro de un respaldo, sin tocar nada:
    python scripts/backup_firestore.py --inspeccionar backups/quiniela_backup_....json

    # Restaurar (DRY-RUN por defecto: solo muestra qué haría):
    python scripts/backup_firestore.py --restaurar backups/quiniela_backup_....json
    # …y para que ESCRIBA de verdad hay que confirmar explícitamente:
    python scripts/backup_firestore.py --restaurar <archivo> --si

    # Restaurar solo una parte:
    python scripts/backup_firestore.py --restaurar <archivo> --solo-partidos --si
    python scripts/backup_firestore.py --restaurar <archivo> --solo-pronosticos --si

CREDENCIALES (igual que actualizar_resultados.py):
  - Firebase: variable de entorno FIREBASE_CREDENTIALS_JSON (JSON completo),
              o en su defecto .streamlit/secrets.toml ([firebase]).
"""

import os
import sys
import json
from datetime import datetime

# Salida UTF-8 en Windows (sin reemplazar stdout: evita cerrar el buffer).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# Raíz del proyecto = carpeta padre de /scripts (donde está actualizar_resultados.py).
_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, _RAIZ)

_DIR_BACKUPS = os.path.join(_RAIZ, "backups")


# ── Credenciales (mismo criterio que el robot) ────────────────────────────────
def _cargar_secrets_toml() -> dict:
    ruta = os.path.join(_RAIZ, ".streamlit", "secrets.toml")
    if not os.path.exists(ruta):
        return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(ruta, "rb") as f:
        return tomllib.load(f)


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
            print("[ERROR] No hay credenciales Firebase "
                  "(ni FIREBASE_CREDENTIALS_JSON ni .streamlit/secrets.toml).")
            sys.exit(1)
        cred = credentials.Certificate({
            "type": fb["type"], "project_id": fb["project_id"],
            "private_key_id": fb["private_key_id"], "private_key": fb["private_key"],
            "client_email": fb["client_email"], "client_id": fb["client_id"],
            "auth_uri": fb["auth_uri"], "token_uri": fb["token_uri"],
            "auth_provider_x509_cert_url": fb.get(
                "auth_provider_x509_cert_url",
                "https://www.googleapis.com/oauth2/v1/certs"),
            "client_x509_cert_url": fb.get("client_x509_cert_url", ""),
        })
    firebase_admin.initialize_app(cred)
    return firestore.client()


# ── Respaldo ──────────────────────────────────────────────────────────────────
def respaldar(db) -> dict:
    """Lee meta/partidos, pronosticos/* y usuarios/* y arma el snapshot."""
    snap = db.collection("meta").document("partidos").get()
    meta_partidos = snap.to_dict() if snap.exists else None
    n_partidos = len((meta_partidos or {}).get("lista", []) or [])

    pronosticos = {}
    for doc in db.collection("pronosticos").stream():
        pronosticos[doc.id] = doc.to_dict()

    usuarios = {}
    for doc in db.collection("usuarios").stream():
        usuarios[doc.id] = doc.to_dict()

    return {
        "exportado": datetime.now().isoformat(),
        "_resumen": {
            "partidos": n_partidos,
            "pronosticos": len(pronosticos),
            "usuarios": len(usuarios),
        },
        "meta_partidos": meta_partidos,
        "pronosticos": pronosticos,
        "usuarios": usuarios,
    }


def guardar_archivo(backup: dict) -> str:
    os.makedirs(_DIR_BACKUPS, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = os.path.join(_DIR_BACKUPS, f"quiniela_backup_{sello}.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2)
    return ruta


# ── Restauración ──────────────────────────────────────────────────────────────
def restaurar(db, backup: dict, *, partidos: bool, pronos: bool, escribir: bool) -> None:
    if partidos:
        meta = backup.get("meta_partidos")
        if not meta or "lista" not in meta:
            print("  ⚠️  El respaldo no tiene meta_partidos; se omite.")
        else:
            n = len(meta.get("lista", []) or [])
            if escribir:
                db.collection("meta").document("partidos").set(meta)
                print(f"  💾 meta/partidos restaurado ({n} partidos).")
            else:
                print(f"  [DRY-RUN] reescribiría meta/partidos con {n} partidos.")

    if pronos:
        pr = backup.get("pronosticos", {}) or {}
        if escribir:
            for uid, data in pr.items():
                db.collection("pronosticos").document(uid).set(data)
            print(f"  💾 pronosticos restaurados ({len(pr)} personas).")
        else:
            print(f"  [DRY-RUN] reescribiría {len(pr)} documentos de pronosticos.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    argv = sys.argv[1:]

    # --inspeccionar: solo lee el archivo, no toca Firestore ni credenciales.
    if "--inspeccionar" in argv:
        ruta = _valor_de(argv, "--inspeccionar")
        with open(ruta, "r", encoding="utf-8") as f:
            backup = json.load(f)
        print(f"📄 {ruta}")
        print(f"   exportado: {backup.get('exportado')}")
        print(f"   resumen:   {backup.get('_resumen')}")
        return

    print("=" * 60)
    print("  Respaldo / restauración de la quiniela (Firestore)")
    print("=" * 60)
    db = inicializar_firestore()

    if "--restaurar" in argv:
        ruta = _valor_de(argv, "--restaurar")
        with open(ruta, "r", encoding="utf-8") as f:
            backup = json.load(f)
        escribir = "--si" in argv
        solo_p = "--solo-partidos" in argv
        solo_q = "--solo-pronosticos" in argv
        # Por defecto restaura ambas; los flags --solo-* acotan.
        partidos = solo_p or not solo_q
        pronos = solo_q or not solo_p
        print(f"  Origen: {ruta}  ·  exportado {backup.get('exportado')}")
        print(f"  Resumen del respaldo: {backup.get('_resumen')}")
        if not escribir:
            print("\n  🧪 DRY-RUN (no escribe). Agrega --si para restaurar de verdad.")
        restaurar(db, backup, partidos=partidos, pronos=pronos, escribir=escribir)
        return

    # Modo por defecto: respaldar.
    backup = respaldar(db)
    ruta = guardar_archivo(backup)
    r = backup["_resumen"]
    print(f"  ✅ Respaldo guardado: {ruta}")
    print(f"     {r['partidos']} partidos · {r['pronosticos']} personas con "
          f"pronósticos · {r['usuarios']} usuarios.")


def _valor_de(argv: list, flag: str) -> str:
    i = argv.index(flag)
    if i + 1 >= len(argv):
        print(f"[ERROR] Falta la ruta del archivo después de {flag}.")
        sys.exit(1)
    return argv[i + 1]


if __name__ == "__main__":
    main()
