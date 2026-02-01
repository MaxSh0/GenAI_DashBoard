import os

# --- БАЗОВЫЕ ПУТИ ---
BASE_DIR = os.getcwd()

# 1. ПАПКИ (Определяем пути к папкам)
CHARTS_FOLDER = os.path.join(BASE_DIR, "charts")
HANDLERS_FOLDER = os.path.join(BASE_DIR, "handlers")
CONFIG_FOLDER = os.path.join(BASE_DIR, "config")  # <--- ВОТ ЭТОЙ ПЕРЕМЕННОЙ НЕ ХВАТАЛО

# Папки для данных
RAW_DATA_FOLDER = os.path.join(BASE_DIR, "data", "raw")
DATA_FOLDER = os.path.join(BASE_DIR, "data_sources")

# 2. ФАЙЛЫ КОНФИГУРАЦИИ (Все кладем в папку config)
# Если ваши файлы лежат в корне, ПЕРЕМЕСТИТЕ их в папку 'config'
CONFIG_FILE = os.path.join(CONFIG_FOLDER, "charts_config.json")
SOURCES_CONFIG_FILE = os.path.join(CONFIG_FOLDER, "sources_config.json")
PAGES_CONFIG_FILE = os.path.join(CONFIG_FOLDER, "pages_config.json")
TITLES_CONFIG_FILE = os.path.join(CONFIG_FOLDER, "titles_config.json")
LLM_PROVIDERS_FILE = os.path.join(CONFIG_FOLDER, "llm_providers.json")

# !!! НОВОЕ: Файл с темами !!!
THEMES_CONFIG_FILE = os.path.join(CONFIG_FOLDER, "themes.json")

# Файлы авторизации
CLIENT_SECRET_FILE = os.path.join(CONFIG_FOLDER, "client_secret.json")
USER_TOKEN_FILE = os.path.join(CONFIG_FOLDER, "user_token.json")

# Ссылки
GUIDE_URL = "https://docs.google.com/document/d/1xCy8bnTMZTShal60hxKWTWmXCnN5OAB46gd9Ad0kowg/edit?usp=sharing"

# Права Google
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

def init_project_structure():
    """Создает все необходимые папки при старте."""
    # Добавили CONFIG_FOLDER в список
    for folder in [DATA_FOLDER, CHARTS_FOLDER, HANDLERS_FOLDER, RAW_DATA_FOLDER, CONFIG_FOLDER]:
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

    init_file = os.path.join(HANDLERS_FOLDER, "__init__.py")
    if not os.path.exists(init_file):
        with open(init_file, "w") as f: f.write("")