import streamlit as st
import os
import json
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from modules.settings import CLIENT_SECRET_FILE
from modules.db_manager import SessionLocal
from modules.models import User

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly"
]
REDIRECT_URI = "http://localhost:8501"


def get_flow():
    """Create and return a Google OAuth flow instance.

    Returns:
        Flow: A configured Google OAuth flow object, or None if the
            client secret file does not exist.
    """
    if not os.path.exists(CLIENT_SECRET_FILE):
        return None
    return Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )


def is_authenticated():
    """Check authentication: first in session memory, then in the database.

    If credentials exist and are valid, they are loaded into the session.
    Expired credentials are refreshed automatically if a refresh token
    is available.

    Returns:
        bool: True if the user has valid Google credentials, False
            otherwise.
    """
    if 'google_creds' in st.session_state:
        creds = st.session_state.google_creds
        if creds and creds.valid:
            return True
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                st.session_state.google_creds = creds
                save_token_to_db(creds)
                return True
            except Exception:
                pass

    if "username" not in st.session_state:
        return False

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == st.session_state["username"]).first()
        if user and user.google_token:
            creds_dict = json.loads(user.google_token)
            creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                save_token_to_db(creds)

            if creds.valid:
                st.session_state.google_creds = creds
                return True
    except Exception as e:
        print(f"Ошибка чтения токена из БД: {e}")
    finally:
        db.close()

    return False


def save_token_to_db(creds):
    """Save Google OAuth credentials to the database for the current user.

    Args:
        creds: A google.oauth2.credentials.Credentials object to
            serialize and store.
    """
    if "username" not in st.session_state:
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == st.session_state["username"]).first()
        if user:
            user.google_token = creds.to_json()
            db.commit()
    except Exception as e:
        print(f"Ошибка сохранения токена в БД: {e}")
        db.rollback()
    finally:
        db.close()


def logout_user():
    """Remove session from memory and erase Google token from the database.

    Clears query parameters and reruns the Streamlit app after logout.
    """
    if 'google_creds' in st.session_state:
        del st.session_state.google_creds

    if "username" in st.session_state:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == st.session_state["username"]).first()
            if user:
                user.google_token = None
                db.commit()
        except Exception as e:
            print(f"Ошибка логаута в БД: {e}")
        finally:
            db.close()

    st.query_params.clear()
    st.rerun()


@st.dialog("⚙️ Мастер настройки Google Auth", width="large")
def setup_google_auth_dialog():
    """Display a step-by-step Google Cloud setup wizard dialog.

    The dialog provides four tabs covering JSON key creation, API
    enablement, test user configuration, and file upload for the
    client secret.
    """
    st.write("Настройка подключения к Google Cloud (шаг за шагом).")

    t1, t2, t3, t4 = st.tabs([
        "1. Ключи (JSON)",
        "2. Включить API",
        "3. Тестеры (Ошибка 403)",
        "4. Загрузка"
    ])

    with t1:
        st.markdown(f"""
        ### Шаг 1: Создаем проект и ключи
        1. Зайдите в [Google Cloud Console](https://console.cloud.google.com/).
        2. Выберите или создайте проект.
        3. Перейдите в меню: **APIs & Services** -> **Credentials**.
        4. Нажмите **+ CREATE CREDENTIALS** -> **OAuth client ID**.
        5. **Application type**: `Web application`.
        6. **Authorized redirect URIs** (Обязательно!):
           * Нажмите `+ ADD URI`
           * Вставьте: `{REDIRECT_URI}`
        7. Нажмите **CREATE** и скачайте JSON-файл.
        """)

    with t2:
        st.warning("Без этого шага таблицы не откроются!", icon="⚠️")
        st.markdown("""
        ### Шаг 2: Включаем библиотеки
        1. В меню слева выберите **APIs & Services** -> **Library** (Библиотека).
        2. В поиске напишите `Google Sheets API`.
        3. Нажмите на карточку и кнопку **ENABLE** (Включить).
        4. Вернитесь в поиск и найдите `Google Drive API`.
        5. Тоже нажмите **ENABLE**.

        *Подождите 30 секунд после включения.*
        """)

    with t3:
        st.markdown("""
        ### Шаг 3: Добавляем себя (Ошибка 403)
        Если вы видите `Access blocked: app has not completed the
        Google verification process`, значит вы не добавили себя в
        тестеры.

        1. Перейдите в **APIs & Services** -> **OAuth consent screen**
           (или Audience).
        2. Найдите раздел **Test users**.
        3. Нажмите кнопку **+ ADD USERS**.
        4. Введите свой email.
        5. Нажмите **SAVE**.
        """)

    with t4:
        st.info("Вставьте содержимое JSON. "
                "Файл будет сохранен как конфигурация системы.")
        json_content = st.text_area(
            "client_secret.json", height=200,
            placeholder='{"web":{"client_id":"...","project_id":"..."}}'
        )

        if st.button("💾 Сохранить и перезапустить", type="primary"):
            if not json_content.strip():
                st.error("Поле пустое!")
                return

            try:
                parsed = json.loads(json_content)
                if "web" not in parsed and "installed" not in parsed:
                    st.error("Неверный формат JSON (нет ключа 'web')")
                    return

                with open(CLIENT_SECRET_FILE, "w") as f:
                    f.write(json_content)

                st.success("Отлично! Перезагружаемся...")
                st.rerun()
            except json.JSONDecodeError:
                st.error("Это не валидный JSON.")


def login_redirect():
    """Render the Google OAuth login page with a sign-in button.

    Displays a styled button linking to Google's OAuth consent screen.
    Falls back to the setup wizard if the client secret file is missing
    or the flow configuration fails.
    """
    if not os.path.exists(CLIENT_SECRET_FILE):
        if st.button("⚙️ Настроить Google", use_container_width=True):
            setup_google_auth_dialog()
        return

    try:
        flow = get_flow()
        auth_url, _ = flow.authorization_url(
            prompt='consent', access_type='offline')

        st.markdown(f'''
            <a href="{auth_url}" target="_self"
               style="text-decoration:none;">
                <button style="
                    width: 100%;
                    background-color: #FF4B4B;
                    color: white;
                    padding: 8px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-weight: bold;
                    margin-bottom: 8px;
                ">
                    🔑 Войти через Google
                </button>
            </a>
        ''', unsafe_allow_html=True)

        if st.button("❓ Инструкция / Ошибки", type="secondary",
                     use_container_width=True):
            setup_google_auth_dialog()

    except Exception:
        st.error("Ошибка чтения настроек")
        if st.button("⚙️ Сброс настроек"):
            setup_google_auth_dialog()


def check_auth_code():
    """Process the OAuth authorization code from query parameters.

    Extracts the code from URL query params, exchanges it for
    credentials, stores them in both session state and database,
    then clears the query params.
    """
    code = st.query_params.get("code")
    if code:
        try:
            flow = get_flow()
            flow.fetch_token(code=code)
            creds = flow.credentials

            st.session_state.google_creds = creds
            save_token_to_db(creds)

            st.query_params.clear()
            st.toast("✅ Вход выполнен и токен сохранен в БД!")
        except Exception as e:
            st.error(f"Ошибка входа: {e}")
