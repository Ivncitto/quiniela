"""
Módulo de conexión y operaciones CRUD con Firebase Firestore.

NOTA: La autenticación es LOCAL (secrets.toml). Firestore solo almacena
datos de la quiniela. El identificador único de usuario es su nombre
(clave en secrets.toml), NO un UID de Firebase Auth.

Estrategia de caché:
  - get_db()              → @st.cache_resource  (singleton, se inicializa una vez)
  - get_partidos()        → @st.cache_data(ttl=60)  (se invalida al modificar)
  - get_todos_pronosticos → @st.cache_data(ttl=30)  (se invalida al guardar)
  - get_todos_usuarios    → @st.cache_data(ttl=300) (rara vez cambia)
  - get_pronosticos_uid   → @st.cache_data(ttl=30)  (por usuario)

Las funciones de escritura llaman a .clear() de las funciones
de lectura afectadas para evitar datos stale.
"""

from datetime import datetime

import firebase_admin
import streamlit as st
from firebase_admin import credentials, firestore

# FieldFilter fue movido en distintas versiones de google-cloud-firestore.
# Este bloque garantiza compatibilidad con firebase-admin 5.x y 6.x.
try:
    from google.cloud.firestore_v1.base_query import FieldFilter  # >= 2.11
except ImportError:
    from google.cloud.firestore_v1 import FieldFilter              # < 2.11


# ─── Instrumentación de lecturas (auditoría de cuota) ─────────────────────────
import logging

logger = logging.getLogger("quiniela.firestore")

# Contador de lecturas reales (por proceso del servidor). Cada función de lectura
# llama a _marca() SOLO cuando ejecuta de verdad (no en aciertos de caché).
LECTURAS = {"total": 0}


def _marca(n: int, etiqueta: str) -> None:
    """Registra n lecturas reales a Firestore para diagnóstico de cuota."""
    LECTURAS["total"] += n
    logger.info("FIRESTORE READ x%d · %s · total_proceso=%d", n, etiqueta, LECTURAS["total"])


# ─── Inicialización del SDK (Singleton) ───────────────────────────────────────

@st.cache_resource
def get_db():
    """
    Inicializa Firebase Admin SDK y retorna el cliente de Firestore.
    @st.cache_resource garantiza que solo se ejecuta una vez por sesión
    del servidor, evitando errores de "app ya inicializada".
    """
    if not firebase_admin._apps:
        # Reconstruir dict de credenciales desde st.secrets
        # (Streamlit serializa el JSON de la cuenta de servicio en campos individuales)
        cred_dict = {
            "type":                         st.secrets["firebase"]["type"],
            "project_id":                   st.secrets["firebase"]["project_id"],
            "private_key_id":               st.secrets["firebase"]["private_key_id"],
            "private_key":                  st.secrets["firebase"]["private_key"],
            "client_email":                 st.secrets["firebase"]["client_email"],
            "client_id":                    st.secrets["firebase"]["client_id"],
            "auth_uri":                     st.secrets["firebase"]["auth_uri"],
            "token_uri":                    st.secrets["firebase"]["token_uri"],
            "auth_provider_x509_cert_url":  st.secrets["firebase"].get(
                "auth_provider_x509_cert_url",
                "https://www.googleapis.com/oauth2/v1/certs"
            ),
            "client_x509_cert_url":         st.secrets["firebase"].get(
                "client_x509_cert_url", ""
            ),
        }
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)

    return firestore.client()


# ─── Usuarios ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_usuario_por_uid(uid: str) -> dict | None:
    """
    Obtiene el perfil de un usuario por su UID.

    CACHEADO 10 min: este documento casi nunca cambia y se consultaba en CADA
    restauración de sesión / rerun, lo que disparaba decenas de miles de lecturas.
    El caché se invalida explícitamente al crear/renombrar usuarios.
    """
    db = get_db()
    doc = db.collection("usuarios").document(uid).get()
    _marca(1, f"get_usuario_por_uid({uid})")
    if doc.exists:
        return doc.to_dict()
    return None


def crear_usuario_si_no_existe(uid: str, nombre: str) -> dict:
    """
    Crea un documento de usuario en la colección 'usuarios' si no existe.
    Se llama automáticamente en el primer login de un usuario nuevo.

    Args:
        uid:    Nombre clave del usuario (igual que en secrets.toml, ej: "Ivan").
        nombre: Nombre visible a mostrar (igual que uid en este sistema).
    """
    db = get_db()

    perfil = {
        "uid":            uid,
        "nombre":         nombre,
        "fecha_registro": datetime.now().isoformat(),
    }
    db.collection("usuarios").document(uid).set(perfil)

    # Invalidar caché de usuarios (lista y documento individual)
    get_todos_los_usuarios.clear()
    get_usuario_por_uid.clear()
    return perfil


@st.cache_data(ttl=3600)
def get_todos_los_usuarios() -> list[dict]:
    """
    Retorna todos los usuarios registrados.
    Cacheado 1 hora (la lista de participantes casi nunca cambia).
    """
    db = get_db()
    docs = list(db.collection("usuarios").stream())
    _marca(len(docs), "get_todos_los_usuarios")
    return [doc.to_dict() for doc in docs]


def actualizar_nombre_usuario(uid: str, nuevo_nombre: str):
    """Actualiza el nombre de un usuario en Firestore."""
    db = get_db()
    db.collection("usuarios").document(uid).update({"nombre": nuevo_nombre})
    get_todos_los_usuarios.clear()
    get_usuario_por_uid.clear()


# ─── Partidos ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_partidos() -> list[dict]:
    """
    Retorna todos los partidos ordenados por fecha.
    Cacheado 10 minutos. Se invalida explícitamente al actualizar
    marcadores o bloqueos, así que no hace falta una TTL corta.
    """
    db = get_db()
    docs = list(db.collection("partidos").order_by("fecha").stream())
    _marca(len(docs), "get_partidos")
    partidos = []
    for doc in docs:
        partido = doc.to_dict()
        partido["id"] = doc.id   # Incluir el ID del documento
        partidos.append(partido)
    return partidos


def actualizar_marcador_real(partido_id: str, local: int, visitante: int):
    """
    (Admin) Actualiza el marcador real de un partido.
    Invalida el caché de partidos y pronósticos.
    """
    db = get_db()
    db.collection("partidos").document(partido_id).update({
        "marcador_real": {"local": local, "visitante": visitante}
    })
    get_partidos.clear()
    get_todos_pronosticos.clear()


def guardar_partidos_batch(cambios: list[dict]):
    """
    (Admin) Guarda en LOTE nombres y/o marcadores de varios partidos.

    Args:
        cambios: lista de dicts. Cada uno debe tener "id" y opcionalmente
                 "equipo_local"+"equipo_visitante" y/o "marcador_real".
                 Solo se escriben los campos presentes.
    """
    db = get_db()
    batch = db.batch()
    escritos = 0
    for c in cambios:
        ref  = db.collection("partidos").document(c["id"])
        data = {}
        if "equipo_local" in c and "equipo_visitante" in c:
            data["equipo_local"]     = str(c["equipo_local"]).strip()
            data["equipo_visitante"] = str(c["equipo_visitante"]).strip()
        if "marcador_real" in c:
            data["marcador_real"] = c["marcador_real"]
        if data:
            batch.update(ref, data)
            escritos += 1
    if escritos:
        batch.commit()
        get_partidos.clear()
        get_todos_pronosticos.clear()
    return escritos


def toggle_bloqueo_partido(partido_id: str, bloqueado: bool):
    """(Admin) Cambia el estado de bloqueo de un partido individual."""
    db = get_db()
    db.collection("partidos").document(partido_id).update({"bloqueado": bloqueado})
    get_partidos.clear()


def actualizar_equipos_partido(partido_id: str, equipo_local: str, equipo_visitante: str):
    """(Admin) Actualiza los nombres de los equipos de un partido (útil en eliminatorias)."""
    db = get_db()
    db.collection("partidos").document(partido_id).update({
        "equipo_local":     equipo_local.strip(),
        "equipo_visitante": equipo_visitante.strip(),
    })
    get_partidos.clear()


def toggle_bloqueo_grupo(grupo: str, bloqueado: bool):
    """(Admin) Bloquea o desbloquea todos los partidos de un grupo específico."""
    db = get_db()
    docs = db.collection("partidos").where(
        filter=FieldFilter("grupo", "==", grupo)
    ).stream()
    batch = db.batch()
    for doc in docs:
        batch.update(doc.reference, {"bloqueado": bloqueado})
    batch.commit()
    get_partidos.clear()


def toggle_bloqueo_jornada(jornada: int, bloqueado: bool):
    """
    (Admin) Bloquea o desbloquea todos los partidos de Grupos de una jornada.
    Filtra la jornada en memoria para no requerir un índice compuesto en Firestore.
    """
    db = get_db()
    docs = db.collection("partidos").where(
        filter=FieldFilter("fase", "==", "Grupos")
    ).stream()
    batch = db.batch()
    for doc in docs:
        if doc.to_dict().get("jornada") == jornada:
            batch.update(doc.reference, {"bloqueado": bloqueado})
    batch.commit()
    get_partidos.clear()


def toggle_bloqueo_fase(fase: str, bloqueado: bool):
    """
    (Admin) Bloquea o desbloquea TODOS los partidos de una fase de una vez.
    Usa batch write para eficiencia.
    """
    db = get_db()
    docs = db.collection("partidos").where(
        filter=FieldFilter("fase", "==", fase)
    ).stream()

    batch = db.batch()
    for doc in docs:
        batch.update(doc.reference, {"bloqueado": bloqueado})
    batch.commit()

    get_partidos.clear()


# ─── Pronósticos (esquema: 1 documento por usuario) ──────────────────────────
#
#   pronosticos/{uid} = {
#       "usuario_uid": uid,
#       "marcadores":  { partido_id: {"local": int, "visitante": int}, ... },
#       "ultima_actualizacion": iso,
#   }
#
# Antes había 1 documento por (usuario, partido): leer el ranking escaneaba
# MILES de documentos (1 lectura c/u). Ahora es 1 documento por usuario, así que
# leer todos los pronósticos cuesta ~1 lectura por participante (reducción ~98%).


def _doc_a_marcadores(data: dict) -> dict:
    """
    Extrae el mapa {partido_id: marcador} de un documento, soportando tanto el
    esquema NUEVO (campo 'marcadores') como el VIEJO (1 doc por partido).
    """
    if "marcadores" in data:                      # esquema nuevo
        return data.get("marcadores") or {}
    if "partido_id" in data:                      # esquema viejo (compatibilidad)
        return {data["partido_id"]: data.get("marcador", {})}
    return {}


@st.cache_data(ttl=300)
def get_pronosticos_usuario(uid: str) -> dict[str, dict]:
    """
    Pronósticos de un usuario: {partido_id: {"local","visitante"}}.
    Lee UN SOLO documento (pronosticos/{uid}) → 1 lectura.
    """
    db = get_db()
    doc = db.collection("pronosticos").document(uid).get()
    _marca(1, f"get_pronosticos_usuario({uid})")
    if doc.exists:
        return _doc_a_marcadores(doc.to_dict())
    return {}


@st.cache_data(ttl=300)
def get_todos_pronosticos() -> list[dict]:
    """
    TODOS los pronósticos en formato plano para el scoring:
        [{"usuario_uid", "partido_id", "marcador"}].

    Con el esquema de 1 doc por usuario, cuesta ~1 lectura por participante.
    Soporta también documentos del esquema viejo durante la transición.
    """
    db = get_db()
    docs = list(db.collection("pronosticos").stream())
    _marca(len(docs), "get_todos_pronosticos")

    # Dedup por (usuario, partido): si coexisten esquema viejo y nuevo durante
    # la migración, evita contar el mismo pronóstico dos veces. El doc NUEVO
    # (id == uid, sin '_') tiene prioridad sobre los viejos.
    por_clave: dict[tuple, dict] = {}
    for doc in docs:
        data = doc.to_dict()
        uid = data.get("usuario_uid", doc.id)
        es_nuevo = "marcadores" in data
        for pid, marcador in _doc_a_marcadores(data).items():
            clave = (uid, pid)
            if clave not in por_clave or es_nuevo:
                por_clave[clave] = {"usuario_uid": uid, "partido_id": pid, "marcador": marcador}
    return list(por_clave.values())


def guardar_pronostico(uid: str, partido_id: str, local: int, visitante: int):
    """
    Guarda/actualiza UN pronóstico dentro del documento único del usuario.
    Usa merge=True para no tocar los demás marcadores ya guardados.
    """
    db = get_db()
    db.collection("pronosticos").document(uid).set({
        "usuario_uid":          uid,
        "marcadores":           {partido_id: {"local": int(local), "visitante": int(visitante)}},
        "ultima_actualizacion": datetime.now().isoformat(),
    }, merge=True)

    get_pronosticos_usuario.clear()
    get_todos_pronosticos.clear()


def guardar_pronosticos_batch(uid: str, predicciones: list[tuple]):
    """
    Guarda en LOTE varios pronósticos en UNA SOLA escritura (documento único).

    Args:
        uid:          identificador del usuario.
        predicciones: lista de tuplas (partido_id, local, visitante).

    Returns:
        int: cuántos marcadores se escribieron.
    """
    if not predicciones:
        return 0

    db = get_db()
    marcadores = {
        pid: {"local": int(local), "visitante": int(visitante)}
        for pid, local, visitante in predicciones
    }
    db.collection("pronosticos").document(uid).set({
        "usuario_uid":          uid,
        "marcadores":           marcadores,
        "ultima_actualizacion": datetime.now().isoformat(),
    }, merge=True)

    get_pronosticos_usuario.clear()
    get_todos_pronosticos.clear()
    return len(marcadores)


def migrar_pronosticos_a_documento_unico() -> dict:
    """
    (Admin, una sola vez) Migra el esquema VIEJO (1 doc por usuario+partido) al
    NUEVO (1 doc por usuario con mapa 'marcadores'), y borra los documentos viejos.

    Returns:
        dict con {usuarios, leidos, borrados}.
    """
    db = get_db()
    docs = list(db.collection("pronosticos").stream())

    por_uid: dict[str, dict] = {}     # uid -> {pid: marcador}
    refs_viejos = []                  # documentos del esquema viejo a borrar

    for doc in docs:
        data = doc.to_dict()
        if "partido_id" in data:                       # documento viejo
            uid = data.get("usuario_uid")
            if not uid:
                continue
            por_uid.setdefault(uid, {})[data["partido_id"]] = data.get("marcador", {})
            refs_viejos.append(doc.reference)

    # Escribir documentos consolidados (merge para no perder lo ya migrado)
    for uid, marcadores in por_uid.items():
        db.collection("pronosticos").document(uid).set({
            "usuario_uid":          uid,
            "marcadores":           marcadores,
            "ultima_actualizacion": datetime.now().isoformat(),
        }, merge=True)

    # Borrar documentos viejos en lotes (máx 500 por batch de Firestore)
    borrados = 0
    batch = db.batch()
    n = 0
    for ref in refs_viejos:
        if ref.id in por_uid:        # nunca borrar un doc nuevo (id == uid)
            continue
        batch.delete(ref)
        n += 1
        borrados += 1
        if n >= 450:
            batch.commit()
            batch = db.batch()
            n = 0
    if n:
        batch.commit()

    get_pronosticos_usuario.clear()
    get_todos_pronosticos.clear()
    return {"usuarios": len(por_uid), "leidos": len(docs), "borrados": borrados}
