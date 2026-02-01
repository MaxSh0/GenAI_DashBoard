import streamlit as st
import os
import json
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# --- ИЗМЕНЕНИЕ 1: Импортируем правильные пути из settings ---
from modules.settings import CLIENT_SECRET_FILE, USER_TOKEN_FILE

# --- ИЗМЕНЕНИЕ 2: Удаляем старые определения (они теперь в settings) ---
# CLIENT_SECRETS_FILE = "client_secret.json"  <-- УДАЛЕНО
# USER_TOKEN_FILE = "user_token.json"         <-- УДАЛЕНО

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly"
]
REDIRECT_URI = "http://localhost:8501"

def get_flow():
    # --- ИЗМЕНЕНИЕ 3: Используем CLIENT_SECRET_FILE (из settings) ---
    if not os.path.exists(CLIENT_SECRET_FILE):
        return None
    return Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )

def is_authenticated():
    """Проверяет авторизацию: сначала в памяти, потом на диске."""
    
    # 1. Если уже есть в сессии (памяти)
    if 'google_creds' in st.session_state:
        creds = st.session_state.google_creds
        if creds and creds.valid:
            return True
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                st.session_state.google_creds = creds
                save_token_to_disk(creds) # Обновляем файл тоже
                return True
            except:
                pass

    # 2. Если нет в памяти, ищем файл на диске ("Запомнить меня")
    # Используем переменную из settings.py
    if os.path.exists(USER_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(USER_TOKEN_FILE, SCOPES)
            
            # Если токен протух, но есть refresh_token — обновляем
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                save_token_to_disk(creds) # Пересохраняем свежий
            
            # Если всё ок — загружаем в сессию
            if creds.valid:
                st.session_state.google_creds = creds
                return True
        except Exception as e:
            # Если файл битый — "удаляем" его (очищаем)
            if os.path.exists(USER_TOKEN_FILE):
                with open(USER_TOKEN_FILE, 'w') as f:
                    f.write("{}")

            
    return False

def save_token_to_disk(creds):
    """Сохраняет токен в файл (Запомнить меня)."""
    # Используем переменную из settings.py
    with open(USER_TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())

def logout_user():
    """Удаляет сессию из памяти И файл с диска."""
    if 'google_creds' in st.session_state:
        del st.session_state.google_creds
    
    # Используем переменную из settings.py
    if os.path.exists(USER_TOKEN_FILE):
        with open(USER_TOKEN_FILE, 'w') as f:
            f.write("{}")
        
    st.query_params.clear()
    st.rerun()

# --- UI: ПОДРОБНАЯ ИНСТРУКЦИЯ ---
@st.dialog("⚙️ Мастер настройки Google Auth", width="large")
def setup_google_auth_dialog():
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
        Если вы видите `Access blocked: app has not completed the Google verification process`, значит вы не добавили себя в тестеры.
        
        1. Перейдите в **APIs & Services** -> **OAuth consent screen** (или Audience).
        2. Найдите раздел **Test users**.
        3. Нажмите кнопку **+ ADD USERS**.
        4. Введите свой email.
        5. Нажмите **SAVE**.
        """)

    with t4:
        st.info(f"Вставьте содержимое JSON. Файл будет сохранен как: `{CLIENT_SECRET_FILE}`")
        json_content = st.text_area("client_secret.json", height=200, placeholder='{"web":{"client_id":"...","project_id":"..."}}')
        
        if st.button("💾 Сохранить и перезапустить", type="primary"):
            if not json_content.strip():
                st.error("Поле пустое!")
                return
                
            try:
                parsed = json.loads(json_content)
                if "web" not in parsed and "installed" not in parsed:
                    st.error("Неверный формат JSON (нет ключа 'web')")
                    return
                    
                # Используем переменную из settings.py
                with open(CLIENT_SECRET_FILE, "w") as f:
                    f.write(json_content)
                    
                st.success("Отлично! Перезагружаемся...")
                st.rerun()
            except json.JSONDecodeError:
                st.error("Это не валидный JSON.")

def login_redirect():
    # 1. Если файла настроек нет вообще (проверяем по пути из settings)
    if not os.path.exists(CLIENT_SECRET_FILE):
        if st.button("⚙️ Настроить Google", use_container_width=True): 
            setup_google_auth_dialog()
        return

    # 2. Файл есть, показываем кнопки
    try:
        flow = get_flow()
        auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
        
        st.markdown(f'''
            <a href="{auth_url}" target="_self" style="text-decoration:none;">
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
        
        if st.button("❓ Инструкция / Ошибки", type="secondary", use_container_width=True):
             setup_google_auth_dialog()
        
    except Exception:
        st.error("Ошибка чтения настроек")
        if st.button("⚙️ Сброс настроек"): setup_google_auth_dialog()

def check_auth_code():
    code = st.query_params.get("code")
    if code:
        try:
            flow = get_flow()
            flow.fetch_token(code=code)
            creds = flow.credentials
            
            # 1. Память
            st.session_state.google_creds = creds
            # 2. Диск
            save_token_to_disk(creds)
            
            st.query_params.clear()
            st.toast("✅ Вход выполнен и запомнен!")
        except Exception as e:
            st.error(f"Ошибка входа: {e}")