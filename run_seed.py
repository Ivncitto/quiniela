"""
run_seed.py — Carga partidos a Firestore SIN prompts interactivos.

Uso:
    python run_seed.py           # Solo carga partidos nuevos (omite existentes)
    python run_seed.py --forzar  # Sobreescribe todos los partidos
"""

import sys
import seed_data


def main():
    forzar = "--forzar" in sys.argv

    print("=" * 55)
    print("  Quiniela - Carga automatica de partidos")
    print("=" * 55)

    print("\n[1/4] Leyendo credenciales desde secrets.toml...")
    secrets = seed_data.cargar_credenciales_desde_toml()

    print("[2/4] Conectando con Firestore...")
    db = seed_data.inicializar_firebase(secrets)
    print("      Conexion exitosa.")

    print("\n[3/4] Generando partidos de Grupos (72)...")
    grupos = seed_data.generar_partidos_grupos()

    print("[3/4] Generando slots de Eliminatorias...")
    eliminatorios = seed_data.generar_partidos_eliminatorios()

    total = grupos + eliminatorios
    modo = "FORZAR (sobreescribe)" if forzar else "solo partidos nuevos"
    print(f"\n[4/4] Cargando {len(total)} partidos [{modo}]...")

    seed_data.cargar_partidos(db, total, forzar=forzar)

    print("\n" + "=" * 55)
    print("  Partidos cargados! Ya puedes usar la quiniela.")
    print("=" * 55)


if __name__ == "__main__":
    main()
