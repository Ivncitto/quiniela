"""
Módulo de interfaz: Pantalla de inicio de sesión.
Usa nombres de usuario simples (sin correos) para el login.
"""

import streamlit as st
from modules.auth import login, get_nombres_usuarios


def mostrar_login():
    """Renderiza la pantalla de login con selector de nombre de usuario."""

    st.markdown("""
    <style>
        .login-wrap {
            max-width: 400px;
            margin: 3.5rem auto 0;
            padding: 2.5rem;
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid rgba(76, 175, 80, 0.22);
            border-radius: 20px;
            backdrop-filter: blur(18px);
            box-shadow: 0 24px 64px rgba(0,0,0,0.55),
                        0 0 50px rgba(76,175,80,0.04);
        }
        .login-ball   { font-size: 4rem; text-align: center; line-height: 1; }
        .login-title  {
            text-align: center;
            font-size: 1.75rem;
            font-weight: 800;
            background: linear-gradient(135deg, #81C784, #FFD700, #4CAF50);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin: 0.4rem 0 0.1rem;
        }
        .login-sub {
            text-align: center;
            color: rgba(200,230,200,0.45);
            font-size: 0.85rem;
            margin-bottom: 2rem;
        }
        .login-foot {
            text-align: center;
            color: rgba(200,230,200,0.3);
            font-size: 0.72rem;
            margin-top: 1.5rem;
            line-height: 1.6;
        }
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])

    with col:
        st.markdown("""
        <div class="login-wrap">
            <div class="login-ball">⚽</div>
            <div class="login-title">Quiniela</div>
            <div class="login-sub">Mundial 2026 · Selecciona tu nombre</div>
        </div>
        """, unsafe_allow_html=True)

        # ── Formulario ────────────────────────────────────────────────────────
        nombres = get_nombres_usuarios()

        with st.form("form_login", clear_on_submit=False):

            if nombres:
                # Selector desplegable si hay nombres registrados en secrets
                nombre_usuario = st.selectbox(
                    "👤 ¿Quién eres?",
                    options=nombres,
                    key="select_usuario_login",
                )
            else:
                # Fallback a texto libre si aún no hay usuarios en secrets
                nombre_usuario = st.text_input(
                    "👤 Tu nombre de usuario",
                    placeholder="Ej: Juan",
                    key="input_usuario_login",
                )

            password = st.text_input(
                "🔑 Contraseña",
                type="password",
                placeholder="••••••••",
                key="input_password_login",
            )

            st.markdown("<br>", unsafe_allow_html=True)
            submitted = st.form_submit_button(
                "🚀 Entrar a la Quiniela",
                use_container_width=True,
                type="primary",
            )

        # ── Manejo del submit ─────────────────────────────────────────────────
        if submitted:
            if not nombre_usuario or not password:
                st.error("⚠️ Selecciona tu nombre e ingresa tu contraseña.")
                return

            with st.spinner("Verificando..."):
                exito, mensaje_error = login(nombre_usuario, password)

            if exito:
                st.success(f"✅ ¡Bienvenido, {nombre_usuario}!")
                st.rerun()
            else:
                st.error(f"❌ {mensaje_error}")

        st.markdown("""
        <div class="login-foot">
            ¿No aparece tu nombre?<br>
            Pídele al administrador que te agregue.
        </div>
        """, unsafe_allow_html=True)
