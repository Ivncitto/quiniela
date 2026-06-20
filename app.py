"""
Quiniela - Mundial 2026
=====================================
Aplicación principal de Streamlit.

Punto de entrada: ejecutar con `streamlit run app.py`

Arquitectura:
  app.py              → Router principal + CSS global + gestión de session_state
  modules/auth.py     → Firebase Auth REST API
  modules/firestore_db.py → CRUD con Firestore + estrategia de caché
  modules/scoring.py  → Lógica de puntuación (3/1/0 pts)
  modules/ui_*.py     → Componentes de interfaz por sección
"""

import streamlit as st

# ─── Configuración de página (DEBE ser lo primero en el script) ───────────────
st.set_page_config(
    page_title="Quiniela | Mundial 2026",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help":     None,
        "Report a bug": None,
        "About":        "🏆 Quiniela - Mundial 2026",
    },
)

# ─── Importaciones de módulos propios ─────────────────────────────────────────
from modules.auth import esta_autenticado, es_admin, logout, restaurar_sesion
from modules.ui_login import mostrar_login
from modules.ui_tabla_general import mostrar_tabla_general
from modules.ui_puntos_grupos import mostrar_puntos_grupos
from modules.ui_tablero import mostrar_tablero
from modules.ui_admin import mostrar_panel_admin


# ─── CSS Global ───────────────────────────────────────────────────────────────
def _cargar_css():
    """Inyecta el CSS personalizado para el diseño de la aplicación."""
    st.markdown("""
    <style>
        /* ── Fuente personalizada ─────────────────────────────────────────── */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap');

        /* ── Variables de color ───────────────────────────────────────────── */
        :root {
            --verde-principal: #4CAF50;
            --verde-oscuro:    #2E7D32;
            --verde-claro:     #81C784;
            --dorado:          #FFD700;
            --dorado-oscuro:   #FFA000;
            --bg-card:         rgba(255, 255, 255, 0.04);
            --borde-verde:     rgba(76, 175, 80, 0.22);
            --texto-principal: #E8F5E9;
            --texto-secundario:rgba(232, 245, 233, 0.55);
        }

        /* ── Fondo general ────────────────────────────────────────────────── */
        .stApp {
            background: radial-gradient(
                ellipse 120% 80% at 10% 10%,
                #071a07 0%,
                #030f03 45%,
                #000000 100%
            );
            font-family: 'Inter', sans-serif;
        }

        /* ── Sidebar — ancho compacto ─────────────────────────────────── */
        section[data-testid="stSidebar"] {
            width: 215px !important;
            min-width: 215px !important;
            background: linear-gradient(180deg, #061006 0%, #0b190b 100%) !important;
            border-right: 1px solid var(--borde-verde) !important;
        }
        /* Padding interno reducido */
        section[data-testid="stSidebar"] > div:first-child {
            padding: 0.5rem 0.6rem !important;
        }
        [data-testid="stSidebar"] * {
            font-family: 'Inter', sans-serif !important;
        }
        [data-testid="stSidebar"] .stRadio > div > label {
            color: var(--texto-principal) !important;
            padding: 5px 8px;
            border-radius: 7px;
            font-size: 0.85rem;
            transition: background 0.2s;
        }
        [data-testid="stSidebar"] .stRadio > div > label:hover {
            background: rgba(76, 175, 80, 0.1) !important;
        }

        /* ── Móvil: sidebar ocultable con hamburger ───────────────────── */
        @media (max-width: 768px) {
            section[data-testid="stSidebar"] {
                width: 200px !important;
                min-width: 200px !important;
            }
            /* Contenido principal: sin margen excesivo en móvil */
            .main .block-container {
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
                padding-top: 1rem !important;
            }
            /* Columnas en móvil: stack vertical */
            [data-testid="stHorizontalBlock"] {
                flex-wrap: wrap;
            }
            /* Métricas más pequeñas */
            [data-testid="stMetricValue"] {
                font-size: 1.2rem !important;
            }
        }

        /* ── Títulos y textos ─────────────────────────────────────────────── */
        h1, h2, h3, h4 {
            color: var(--texto-principal) !important;
            font-family: 'Inter', sans-serif !important;
        }
        p, span, div, label {
            font-family: 'Inter', sans-serif !important;
        }

        /* ── Iconos Material de Streamlit ─────────────────────────────────── */
        /* IMPORTANTE: el override de fuente de arriba (span/*) rompe las
           ligaduras de los iconos y los muestra como texto
           ("keyboard_double_arrow_right", etc.). Aquí restauramos la fuente
           de iconos para las flechas del sidebar, chevrons de expanders, etc. */
        span[data-testid="stIconMaterial"],
        [data-testid="stSidebar"] span[data-testid="stIconMaterial"],
        [data-testid="stExpander"] span[data-testid="stIconMaterial"] {
            font-family: 'Material Symbols Rounded' !important;
        }
        .material-icons          { font-family: 'Material Icons' !important; }
        .material-symbols-rounded  { font-family: 'Material Symbols Rounded' !important; }
        .material-symbols-outlined { font-family: 'Material Symbols Outlined' !important; }

        /* ── Botones principales ──────────────────────────────────────────── */
        .stButton > button {
            background: linear-gradient(135deg, #1B5E20, #2E7D32) !important;
            color: #E8F5E9 !important;
            border: 1px solid rgba(76, 175, 80, 0.35) !important;
            border-radius: 8px !important;
            font-family: 'Inter', sans-serif !important;
            font-weight: 600 !important;
            letter-spacing: 0.3px;
            transition: all 0.25s ease !important;
        }
        .stButton > button:hover {
            background: linear-gradient(135deg, #2E7D32, #43A047) !important;
            box-shadow: 0 6px 24px rgba(76, 175, 80, 0.35) !important;
            transform: translateY(-1px) !important;
        }
        .stButton > button:active {
            transform: translateY(0) !important;
        }
        /* Botón primario (type="primary") */
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #2E7D32, #4CAF50) !important;
            box-shadow: 0 4px 20px rgba(76, 175, 80, 0.25) !important;
        }

        /* ── Inputs de texto y número ─────────────────────────────────────── */
        .stTextInput input,
        .stNumberInput input {
            background: rgba(255, 255, 255, 0.05) !important;
            border: 1px solid var(--borde-verde) !important;
            border-radius: 8px !important;
            color: var(--texto-principal) !important;
            font-family: 'Inter', sans-serif !important;
            transition: border-color 0.2s;
        }
        .stTextInput input:focus,
        .stNumberInput input:focus {
            border-color: var(--verde-claro) !important;
            box-shadow: 0 0 0 2px rgba(76, 175, 80, 0.15) !important;
        }
        .stTextInput input:disabled,
        .stNumberInput input:disabled {
            background: rgba(255, 255, 255, 0.02) !important;
            color: rgba(200, 230, 200, 0.3) !important;
            cursor: not-allowed !important;
        }

        /* ── Selectbox ────────────────────────────────────────────────────── */
        .stSelectbox [data-baseweb="select"] > div {
            background: rgba(255, 255, 255, 0.05) !important;
            border: 1px solid var(--borde-verde) !important;
            border-radius: 8px !important;
            color: var(--texto-principal) !important;
        }

        /* ── Métricas ─────────────────────────────────────────────────────── */
        [data-testid="stMetricValue"] {
            color: var(--verde-claro) !important;
            font-weight: 800 !important;
        }
        [data-testid="stMetricLabel"] {
            color: var(--texto-secundario) !important;
        }

        /* ── DataFrame / Tabla ────────────────────────────────────────────── */
        /* El color de celdas/texto lo controla el tema dark de .streamlit/config.toml
           (el grid se dibuja sobre <canvas> y no responde al CSS). Aquí solo
           damos el borde y dejamos que el fondo oscuro nativo se vea sin velos. */
        [data-testid="stDataFrameResizable"] {
            border: 1px solid var(--borde-verde) !important;
            border-radius: 10px !important;
            overflow: hidden;
        }

        /* ── Alerts ───────────────────────────────────────────────────────── */
        .stAlert {
            border-radius: 10px !important;
            border: 1px solid var(--borde-verde) !important;
        }

        /* ── Expanders ────────────────────────────────────────────────────── */
        [data-testid="stExpander"] {
            background: var(--bg-card) !important;
            border: 1px solid var(--borde-verde) !important;
            border-radius: 10px !important;
            margin-bottom: 0.5rem;
        }
        [data-testid="stExpander"] summary {
            color: var(--verde-claro) !important;
            font-weight: 600 !important;
        }

        /* ── Spinner ──────────────────────────────────────────────────────── */
        .stSpinner > div {
            border-color: var(--verde-principal) transparent transparent transparent !important;
        }

        /* ── Badges de estado ─────────────────────────────────────────────── */
        .badge-abierto {
            background: linear-gradient(135deg, #1B5E20, #2E7D32);
            color: #A5D6A7;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        .badge-cerrado {
            background: linear-gradient(135deg, #7F0000, #B71C1C);
            color: #FFCDD2;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.5px;
        }

        /* ── Dividers ─────────────────────────────────────────────────────── */
        hr {
            border-color: var(--borde-verde) !important;
            opacity: 0.5;
        }

        /* ── Scrollbar personalizada ──────────────────────────────────────── */
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb {
            background: rgba(76, 175, 80, 0.4);
            border-radius: 3px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(76, 175, 80, 0.7);
        }
    </style>
    """, unsafe_allow_html=True)


# ─── Sidebar de navegación ────────────────────────────────────────────────────
def _renderizar_sidebar() -> str:
    """
    Renderiza la barra lateral con el perfil del usuario y las opciones
    de navegación filtradas según el rol.

    Returns:
        str: El nombre de la página seleccionada.
    """
    with st.sidebar:
        # Logo compacto
        st.markdown("""
        <div style="text-align:center; padding: 0.6rem 0 0.3rem;">
            <div style="font-size: 2.4rem; line-height: 1;">⚽</div>
            <div style="font-size: 1rem; font-weight: 800;
                        color: #81C784; margin-top: 0.2rem; line-height: 1.2;">
                Quiniela<br>
            </div>
            <div style="font-size: 0.65rem; color: rgba(200,230,200,0.4);
                        letter-spacing: 1px; text-transform: uppercase; margin-top: 2px;">
                Mundial 2026
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        # Tarjeta del usuario — compacta
        nombre    = st.session_state.get("nombre", "Usuario")
        rol       = st.session_state.get("rol", "familiar")
        emoji     = "👑" if rol == "admin" else "👤"
        label_rol = "Admin" if rol == "admin" else "Participante"

        st.markdown(f"""
        <div style="
            padding: 0.5rem 0.4rem;
            background: rgba(76,175,80,0.07);
            border: 1px solid rgba(76,175,80,0.18);
            border-radius: 9px;
            text-align: center;
            margin-bottom: 0.7rem;
        ">
            <div style="font-size: 1.3rem; line-height: 1;">{emoji}</div>
            <div style="font-weight: 700; color: #81C784; font-size: 0.9rem;
                        margin-top: 0.15rem; overflow: hidden;
                        text-overflow: ellipsis; white-space: nowrap;">
                {nombre}
            </div>
            <div style="font-size: 0.62rem; color: rgba(200,230,200,0.4);
                        text-transform: uppercase; letter-spacing: 0.8px;">
                {label_rol}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Menú de navegación
        opciones = [
            "🏆 Tabla General",
            "📊 Puntos por Fase",
            "📋 Mi Tablero",
        ]
        if es_admin():
            opciones.append("⚙️ Panel Admin")

        pagina = st.radio(
            "Navegacion",
            opciones,
            label_visibility="collapsed",
            key="nav_radio",
        )

        st.divider()

        if st.button("Salir", use_container_width=True, key="btn_logout"):
            logout()
            st.rerun()

        st.markdown("""
        <div style="text-align:center; color:rgba(200,230,200,0.15);
                    font-size:0.6rem; margin-top:1rem;">
            Quiniela v1.0
        </div>
        """, unsafe_allow_html=True)

    return pagina


# ─── Router principal ─────────────────────────────────────────────────────────
def main():
    """Función principal: carga CSS, verifica auth y renderiza la página."""
    _cargar_css()

    # Reabrir la sesión desde la cookie del dispositivo (si existe y es válida).
    # Debe ir antes de comprobar la autenticación.
    restaurar_sesion()

    # Si no está autenticado, mostrar pantalla de login
    if not esta_autenticado():
        mostrar_login()
        return

    # Renderizar sidebar y obtener página seleccionada
    pagina = _renderizar_sidebar()

    # Enrutar a la vista correspondiente
    if pagina == "🏆 Tabla General":
        mostrar_tabla_general()

    elif pagina == "📊 Puntos por Fase":
        mostrar_puntos_grupos()

    elif pagina == "📋 Mi Tablero":
        mostrar_tablero()

    elif pagina == "⚙️ Panel Admin":
        # Doble verificación: solo admin puede acceder
        if es_admin():
            mostrar_panel_admin()
        else:
            st.error("🚫 Acceso denegado.")


# ─── Punto de entrada ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
