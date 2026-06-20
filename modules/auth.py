"""
Módulo de autenticación LOCAL — sin Firebase Auth.

Sistema:
  - Las credenciales (usuario + contraseña + rol) viven en secrets.toml.
  - NO se usa Firebase Authentication ni ninguna API REST externa.
  - Firestore sigue usándose solo para almacenar datos (pronósticos, partidos).
  - El nombre de usuario es el identificador único en Firestore (en lugar del UID).

Flujo de login:
  1. Usuario selecciona su nombre en el dropdown y escribe su contraseña.
  2. Se busca en st.secrets["usuarios"][nombre] y se compara la contraseña.
  3. Si coincide, se crea/actualiza su perfil en Firestore y se inicia sesión.

Persistencia de sesión:
  - Al iniciar sesión se guarda una cookie firmada (HMAC) en el dispositivo.
  - Al recargar la página o volver más tarde, `restaurar_sesion()` lee esa
    cookie y reabre la sesión sin pedir la contraseña de nuevo.
  - El rol SIEMPRE se vuelve a leer de secrets.toml al restaurar (la cookie no
    decide el rol), así nadie puede auto-promoverse a admin editando la cookie.
"""

import hmac
import hashlib
from datetime import datetime, timedelta

import streamlit as st
import extra_streamlit_components as stx


# ─── Configuración de cookie ──────────────────────────────────────────────────
_COOKIE_NOMBRE = "quiniela_auth"
_COOKIE_DIAS   = 30  # cuánto tiempo permanece abierta la sesión


def _cookie_secret() -> str:
    """
    Secreto del servidor para firmar la cookie. Idealmente definido en
    secrets.toml como:

        [auth]
        cookie_secret = "una-cadena-larga-y-aleatoria"

    Si no existe, usa un valor por defecto (suficiente para una quiniela
    familiar, pero conviene establecer uno propio).
    """
    return str(st.secrets.get("auth", {}).get("cookie_secret", "quiniela-mundial-2026"))


def _firma(uid: str) -> str:
    """HMAC-SHA256 del uid con el secreto del servidor."""
    return hmac.new(_cookie_secret().encode(), uid.encode(), hashlib.sha256).hexdigest()


def _crear_token(uid: str) -> str:
    """Token = uid|firma. La firma impide falsificar/alterar el uid."""
    return f"{uid}|{_firma(uid)}"


def _validar_token(token: str) -> str | None:
    """Devuelve el uid si el token es válido y no ha sido alterado, si no None."""
    try:
        uid, firma = token.rsplit("|", 1)
    except (ValueError, AttributeError):
        return None
    if hmac.compare_digest(firma, _firma(uid)):
        return uid
    return None


def _cookie_manager() -> stx.CookieManager:
    """
    Instancia única del gestor de cookies POR EJECUCIÓN del script.
    Debe instanciarse exactamente una vez por run (lo hace `restaurar_sesion`)
    para evitar errores de widget duplicado; login/logout reutilizan la
    instancia guardada en session_state.
    """
    return st.session_state.get("_cookie_mgr")


# ─── Funciones de consulta ────────────────────────────────────────────────────

def get_nombres_usuarios() -> list[str]:
    """
    Retorna la lista de nombres de usuario definidos en secrets.toml.
    Ordena alfabéticamente para el dropdown de login.
    """
    mapa = st.secrets.get("usuarios", {})
    return sorted(mapa.keys())


def _encontrar_usuario(nombre_ingresado: str) -> tuple[str | None, dict | None]:
    """
    Busca un usuario en secrets.toml de forma insensible a mayúsculas.

    Returns:
        (clave_real, config_dict) si se encontró, (None, None) si no.
    """
    mapa = st.secrets.get("usuarios", {})
    nombre_lower = nombre_ingresado.lower().strip()

    for clave, config in mapa.items():
        if clave.lower() == nombre_lower:
            return clave, dict(config)

    return None, None


# ─── Sesión ───────────────────────────────────────────────────────────────────

def _iniciar_sesion(uid: str, rol: str) -> None:
    """Carga/crea el perfil en Firestore y rellena session_state."""
    from modules.firestore_db import get_usuario_por_uid, crear_usuario_si_no_existe

    perfil = get_usuario_por_uid(uid)
    if perfil is None:
        perfil = crear_usuario_si_no_existe(uid, uid)

    st.session_state["autenticado"] = True
    st.session_state["uid"]         = uid
    st.session_state["nombre"]      = perfil.get("nombre", uid)
    st.session_state["rol"]         = rol


def restaurar_sesion() -> None:
    """
    Instancia el gestor de cookies (una vez por run) y, si hay una cookie de
    sesión válida y aún no estamos autenticados, reabre la sesión.

    Debe llamarse al inicio de `main()`, antes de comprobar la autenticación.
    """
    cm = stx.CookieManager(key="quiniela_cookie_mgr")
    st.session_state["_cookie_mgr"] = cm

    if st.session_state.get("autenticado"):
        return

    token = cm.get(_COOKIE_NOMBRE)
    if not token:
        return

    uid = _validar_token(token)
    if uid is None:
        return

    # El rol SIEMPRE se recalcula desde secrets, nunca desde la cookie.
    clave, config = _encontrar_usuario(uid)
    if clave is None:
        return

    rol = str(config.get("rol", "familiar"))
    _iniciar_sesion(clave, rol)


# ─── Login / Logout ───────────────────────────────────────────────────────────

def login(nombre_usuario: str, password: str) -> tuple[bool, str]:
    """
    Autentica al usuario verificando contra secrets.toml.

    Args:
        nombre_usuario: Nombre del familiar (ej: "Ivan", "Julio").
        password:       Contraseña del usuario.

    Returns:
        (True, "")               si el login es correcto.
        (False, "mensaje error") si falla.
    """
    # ── Paso 1: Buscar usuario en secrets ─────────────────────────────────────
    clave, config = _encontrar_usuario(nombre_usuario)

    if clave is None:
        return False, f"El usuario '{nombre_usuario}' no existe."

    # ── Paso 2: Verificar contraseña ──────────────────────────────────────────
    password_correcta = str(config.get("password", ""))
    if password != password_correcta:
        return False, "Contraseña incorrecta."

    rol = str(config.get("rol", "familiar"))

    # ── Paso 3: Iniciar sesión (perfil Firestore + session_state) ─────────────
    _iniciar_sesion(clave, rol)

    # ── Paso 4: Guardar cookie firmada en el dispositivo ──────────────────────
    cm = _cookie_manager()
    if cm is not None:
        cm.set(
            _COOKIE_NOMBRE,
            _crear_token(clave),
            expires_at=datetime.now() + timedelta(days=_COOKIE_DIAS),
            key="set_auth_cookie",
        )

    return True, ""


def logout():
    """Cierra la sesión: borra la cookie, la caché y session_state."""
    st.cache_data.clear()

    cm = _cookie_manager()
    if cm is not None:
        try:
            cm.delete(_COOKIE_NOMBRE, key="del_auth_cookie")
        except Exception:
            pass

    for clave in ["autenticado", "uid", "nombre", "rol"]:
        st.session_state.pop(clave, None)


# ─── Helpers de estado ────────────────────────────────────────────────────────

def esta_autenticado() -> bool:
    """Retorna True si hay una sesión activa."""
    return st.session_state.get("autenticado", False)


def es_admin() -> bool:
    """Retorna True si el usuario actual es administrador."""
    return st.session_state.get("rol") == "admin"
