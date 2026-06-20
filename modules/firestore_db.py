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

def get_usuario_por_uid(uid: str) -> dict | None:
    """Obtiene el perfil de un usuario por su UID. Sin caché (uso en login)."""
    db = get_db()
    doc = db.collection("usuarios").document(uid).get()
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

    # Invalidar caché de usuarios
    get_todos_los_usuarios.clear()
    return perfil


@st.cache_data(ttl=300)
def get_todos_los_usuarios() -> list[dict]:
    """
    Retorna todos los usuarios registrados.
    Cacheado 5 minutos (cambia poco frecuentemente).
    """
    db = get_db()
    docs = db.collection("usuarios").stream()
    return [doc.to_dict() for doc in docs]


def actualizar_nombre_usuario(uid: str, nuevo_nombre: str):
    """Actualiza el nombre de un usuario en Firestore."""
    db = get_db()
    db.collection("usuarios").document(uid).update({"nombre": nuevo_nombre})
    get_todos_los_usuarios.clear()


# ─── Partidos ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_partidos() -> list[dict]:
    """
    Retorna todos los partidos ordenados por fecha.
    Cacheado 60 segundos para reducir lecturas a Firestore.
    Se invalida al actualizar marcadores o bloqueos.
    """
    db = get_db()
    docs = db.collection("partidos").order_by("fecha").stream()
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


# ─── Pronósticos ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def get_pronosticos_usuario(uid: str) -> dict[str, dict]:
    """
    Retorna los pronósticos de un usuario específico como un dict.
    Cacheado 30 segundos por uid.

    Returns:
        {partido_id: {"local": int, "visitante": int}}
    """
    db = get_db()
    docs = db.collection("pronosticos").where(
        filter=FieldFilter("usuario_uid", "==", uid)
    ).stream()

    resultado: dict[str, dict] = {}
    for doc in docs:
        data = doc.to_dict()
        resultado[data["partido_id"]] = data.get("marcador", {})

    return resultado


@st.cache_data(ttl=30)
def get_todos_pronosticos() -> list[dict]:
    """
    Retorna TODOS los pronósticos de todos los usuarios.
    Cacheado 30 segundos. Usado para calcular rankings.
    """
    db = get_db()
    docs = db.collection("pronosticos").stream()
    return [doc.to_dict() for doc in docs]


def guardar_pronostico(uid: str, partido_id: str, local: int, visitante: int):
    """
    Guarda o actualiza el pronóstico de un usuario para un partido.
    Usa ID compuesto {uid}_{partido_id} para evitar duplicados.
    Solo funciona si el partido está desbloqueado (validación en UI).
    """
    db = get_db()
    doc_id = f"{uid}_{partido_id}"

    db.collection("pronosticos").document(doc_id).set({
        "usuario_uid":         uid,
        "partido_id":          partido_id,
        "marcador":            {"local": local, "visitante": visitante},
        "ultima_actualizacion": datetime.now().isoformat(),
    })

    # Invalidar caché del usuario y ranking global
    get_pronosticos_usuario.clear()
    get_todos_pronosticos.clear()


def guardar_pronosticos_batch(uid: str, predicciones: list[tuple]):
    """
    Guarda/actualiza en LOTE varios pronósticos de un usuario.

    Args:
        uid:          identificador del usuario.
        predicciones: lista de tuplas (partido_id, local, visitante).

    Returns:
        int: cuántos pronósticos se escribieron.
    """
    db = get_db()
    batch = db.batch()
    escritos = 0
    for partido_id, local, visitante in predicciones:
        doc_id = f"{uid}_{partido_id}"
        batch.set(db.collection("pronosticos").document(doc_id), {
            "usuario_uid":          uid,
            "partido_id":           partido_id,
            "marcador":             {"local": int(local), "visitante": int(visitante)},
            "ultima_actualizacion": datetime.now().isoformat(),
        })
        escritos += 1

    if escritos:
        batch.commit()
        get_pronosticos_usuario.clear()
        get_todos_pronosticos.clear()
    return escritos
