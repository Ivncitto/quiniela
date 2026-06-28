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

import copy
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


# ─── Partidos (esquema: 1 documento agregado) ────────────────────────────────
#
#   meta/partidos = {"lista": [ {…partido con id…}, ... ], "actualizado": iso}
#
# Antes había 1 documento por partido (104) → cada lectura costaba 104. Ahora se
# lee UN SOLO documento (1 lectura). Las escrituras del admin modifican la lista
# en memoria (desde caché, 0 lecturas extra) y reescriben ese único documento.

_META_COL = "meta"
_META_PARTIDOS_DOC = "partidos"


def _escribir_lista_partidos(lista: list[dict]) -> None:
    """Reescribe el documento agregado de partidos e invalida la caché."""
    db = get_db()
    db.collection(_META_COL).document(_META_PARTIDOS_DOC).set({
        "lista":       lista,
        "actualizado": datetime.now().isoformat(),
    })
    get_partidos.clear()


@st.cache_data(ttl=600)
def get_partidos() -> list[dict]:
    """
    Lista de partidos ordenada por fecha, leída del documento agregado (1 lectura).

    Si el agregado aún no existe (primera vez tras sembrar datos), lo reconstruye
    desde la colección 'partidos' una sola vez y lo guarda.
    """
    db = get_db()
    doc = db.collection(_META_COL).document(_META_PARTIDOS_DOC).get()
    _marca(1, "get_partidos (agregado)")

    if doc.exists and isinstance(doc.to_dict().get("lista"), list):
        lista = doc.to_dict()["lista"]
    else:
        # Migración perezosa desde la colección individual
        docs = list(db.collection("partidos").order_by("fecha").stream())
        _marca(len(docs), "get_partidos (reconstrucción desde colección)")
        lista = []
        for d in docs:
            p = d.to_dict()
            p["id"] = d.id
            lista.append(p)
        if lista:
            _escribir_lista_partidos(lista)

    return sorted(lista, key=lambda p: p.get("fecha", ""))


def _modificar_partidos(fn) -> int:
    """
    Aplica fn(partido)->bool a cada partido (sobre una COPIA de la lista cacheada)
    y reescribe el agregado si hubo cambios. 0 lecturas extra (usa caché).
    Devuelve cuántos partidos cambiaron.
    """
    lista = copy.deepcopy(get_partidos())
    cambiados = 0
    for p in lista:
        if fn(p):
            cambiados += 1
    if cambiados:
        _escribir_lista_partidos(lista)
    return cambiados


def actualizar_marcador_real(partido_id: str, local: int, visitante: int, penales: str | None = None):
    """
    (Admin) Actualiza el marcador real de un partido en el agregado.

    `penales` ("L"/"V"/None) indica quién ganó la tanda de penales; solo aplica
    en eliminatorias con empate. Se guarda siempre (None lo limpia).
    """
    def _f(p):
        if p.get("id") == partido_id:
            p["marcador_real"] = {"local": local, "visitante": visitante, "penales": penales}
            return True
        return False
    _modificar_partidos(_f)


def guardar_partidos_batch(cambios: list[dict]):
    """
    (Admin) Guarda en LOTE nombres y/o marcadores de varios partidos en UNA sola
    escritura del documento agregado.

    Args:
        cambios: lista de dicts con "id" y opcionalmente
                 "equipo_local"+"equipo_visitante" y/o "marcador_real".
    """
    por_id = {c["id"]: c for c in cambios}

    def _f(p):
        c = por_id.get(p.get("id"))
        if not c:
            return False
        tocado = False
        if "equipo_local" in c and "equipo_visitante" in c:
            p["equipo_local"]     = str(c["equipo_local"]).strip()
            p["equipo_visitante"] = str(c["equipo_visitante"]).strip()
            tocado = True
        if "marcador_real" in c:
            p["marcador_real"] = c["marcador_real"]
            tocado = True
        return tocado

    return _modificar_partidos(_f)


def toggle_bloqueo_partido(partido_id: str, bloqueado: bool):
    """(Admin) Cambia el estado de bloqueo de un partido individual."""
    def _f(p):
        if p.get("id") == partido_id:
            p["bloqueado"] = bloqueado
            return True
        return False
    _modificar_partidos(_f)


def actualizar_equipos_partido(partido_id: str, equipo_local: str, equipo_visitante: str):
    """(Admin) Actualiza los nombres de los equipos de un partido."""
    def _f(p):
        if p.get("id") == partido_id:
            p["equipo_local"]     = equipo_local.strip()
            p["equipo_visitante"] = equipo_visitante.strip()
            return True
        return False
    _modificar_partidos(_f)


def toggle_bloqueo_grupo(grupo: str, bloqueado: bool):
    """(Admin) Bloquea o desbloquea todos los partidos de un grupo."""
    def _f(p):
        if p.get("grupo") == grupo:
            p["bloqueado"] = bloqueado
            return True
        return False
    _modificar_partidos(_f)


def toggle_bloqueo_jornada(jornada: int, bloqueado: bool):
    """(Admin) Bloquea o desbloquea todos los partidos de Grupos de una jornada."""
    def _f(p):
        if p.get("fase") == "Grupos" and p.get("jornada") == jornada:
            p["bloqueado"] = bloqueado
            return True
        return False
    _modificar_partidos(_f)


def toggle_bloqueo_fase(fase: str, bloqueado: bool):
    """(Admin) Bloquea o desbloquea TODOS los partidos de una fase."""
    def _f(p):
        if p.get("fase") == fase:
            p["bloqueado"] = bloqueado
            return True
        return False
    _modificar_partidos(_f)


def reconstruir_agregado_partidos() -> int:
    """
    (Admin) Reconstruye meta/partidos desde la colección 'partidos'.
    Úsalo si volviste a sembrar datos (seed) y el agregado quedó desactualizado.
    """
    db = get_db()
    docs = list(db.collection("partidos").order_by("fecha").stream())
    _marca(len(docs), "reconstruir_agregado_partidos")
    lista = []
    for d in docs:
        p = d.to_dict()
        p["id"] = d.id
        lista.append(p)
    _escribir_lista_partidos(lista)
    return len(lista)


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

    Fallback: si el documento único aún no existe (datos sin migrar), lee el
    esquema viejo (1 doc por partido) para que los datos sigan cargando.
    """
    db = get_db()
    doc = db.collection("pronosticos").document(uid).get()
    _marca(1, f"get_pronosticos_usuario({uid})")
    if doc.exists:
        marcadores = _doc_a_marcadores(doc.to_dict())
        if marcadores:
            return marcadores

    # ── Fallback al esquema viejo (sólo antes de migrar) ──────────────────────
    viejos = list(db.collection("pronosticos").where(
        filter=FieldFilter("usuario_uid", "==", uid)
    ).stream())
    if viejos:
        _marca(len(viejos), f"get_pronosticos_usuario fallback viejo({uid})")
        resultado: dict[str, dict] = {}
        for d in viejos:
            data = d.to_dict()
            if "partido_id" in data:
                resultado[data["partido_id"]] = data.get("marcador", {})
        return resultado

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
        predicciones: lista de tuplas (partido_id, local, visitante) o
                      (partido_id, local, visitante, penales). `penales` es
                      "L"/"V"/None (ganador de penales en empates de eliminatoria).

    Returns:
        int: cuántos marcadores se escribieron.
    """
    if not predicciones:
        return 0

    db = get_db()
    marcadores = {}
    for item in predicciones:
        pid, local, visitante = item[0], item[1], item[2]
        penales = item[3] if len(item) > 3 else None
        marcadores[pid] = {
            "local": int(local),
            "visitante": int(visitante),
            "penales": penales,
        }
    db.collection("pronosticos").document(uid).set({
        "usuario_uid":          uid,
        "marcadores":           marcadores,
        "ultima_actualizacion": datetime.now().isoformat(),
    }, merge=True)

    get_pronosticos_usuario.clear()
    get_todos_pronosticos.clear()
    return len(marcadores)


def exportar_backup() -> dict:
    """
    (Admin) Lee TODO una vez y arma un backup consolidado para descargar como JSON:

      {
        "exportado": iso,
        "meta_partidos": [ {…partido…}, ... ],
        "pronosticos": {
            uid: {
                "nombre": str,
                "marcadores": { partido_id: {"local","visitante"} | null, ... }  ← TODOS los partidos
            }, ...
        }
      }

    Cada usuario incluye TODOS los partidos (formato de meta-partidos); los
    partidos sin pronóstico quedan en null. Es 1 "json por persona" dentro del
    objeto 'pronosticos'.
    """
    partidos = get_partidos()                  # 1 lectura (agregado)
    usuarios = get_todos_los_usuarios()        # cacheado
    todos    = get_todos_pronosticos()         # consolidado (o fallback viejo)

    # Indexar pronósticos por usuario
    por_uid: dict[str, dict] = {}
    for pr in todos:
        por_uid.setdefault(pr["usuario_uid"], {})[pr["partido_id"]] = pr.get("marcador", {})

    ids_partidos   = [p["id"] for p in partidos]
    nombre_por_uid = {u.get("uid", ""): u.get("nombre", u.get("uid", "")) for u in usuarios}

    pronosticos_export: dict[str, dict] = {}
    uids = set(nombre_por_uid) | set(por_uid)
    for uid in sorted(uids):
        if not uid:
            continue
        marc_usuario = por_uid.get(uid, {})
        completo = {pid: marc_usuario.get(pid) for pid in ids_partidos}   # None si falta
        pronosticos_export[uid] = {
            "nombre":     nombre_por_uid.get(uid, uid),
            "marcadores": completo,
        }

    return {
        "exportado":     datetime.now().isoformat(),
        "meta_partidos": partidos,
        "pronosticos":   pronosticos_export,
    }


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
