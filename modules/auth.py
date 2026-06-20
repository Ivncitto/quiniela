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
"""

import streamlit as st


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
    from modules.firestore_db import get_usuario_por_uid, crear_usuario_si_no_existe

    # ── Paso 1: Buscar usuario en secrets ─────────────────────────────────────
    clave, config = _encontrar_usuario(nombre_usuario)

    if clave is None:
        return False, f"El usuario '{nombre_usuario}' no existe."

    # ── Paso 2: Verificar contraseña ──────────────────────────────────────────
    password_correcta = str(config.get("password", ""))
    if password != password_correcta:
        return False, "Contraseña incorrecta."

    rol = str(config.get("rol", "familiar"))

    # ── Paso 3: Crear/cargar perfil en Firestore ──────────────────────────────
    # Usamos el nombre (clave exacta de secrets) como identificador en Firestore
    uid = clave   # Ej: "Ivan", "Julio", "DavidV"

    perfil = get_usuario_por_uid(uid)
    if perfil is None:
        perfil = crear_usuario_si_no_existe(uid, clave)

    # ── Paso 4: Guardar sesión en session_state ───────────────────────────────
    st.session_state["autenticado"] = True
    st.session_state["uid"]         = uid
    st.session_state["nombre"]      = perfil.get("nombre", clave)
    st.session_state["rol"]         = rol

    return True, ""


def logout():
    """Cierra la sesión y limpia caché + session_state."""
    st.cache_data.clear()
    for clave in ["autenticado", "uid", "nombre", "rol"]:
        st.session_state.pop(clave, None)


# ─── Helpers de estado ────────────────────────────────────────────────────────

def esta_autenticado() -> bool:
    """Retorna True si hay una sesión activa."""
    return st.session_state.get("autenticado", False)


def es_admin() -> bool:
    """Retorna True si el usuario actual es administrador."""
    return st.session_state.get("rol") == "admin"
