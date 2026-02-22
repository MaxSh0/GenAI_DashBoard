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
# !!! НОВОЕ: Файл с темами !!!
THEMES_CONFIG_FILE = os.path.join(CONFIG_FOLDER, "themes.json")

# Файлы авторизации
CLIENT_SECRET_FILE = os.path.join(CONFIG_FOLDER, "client_secret.json")
USER_TOKEN_FILE = os.path.join(CONFIG_FOLDER, "user_token.json")

# Ссылки
GUIDE_URL = "https://docs.google.com/document/d/1xCy8bnTMZTShal60hxKWTWmXCnN5OAB46gd9Ad0kowg/edit?usp=sharing"
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", b"XLCAruJo-b3yWmCM4blsrBmDBgU5z5SF0Ni1C18zN4o=")
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


# --- S3 / MinIO Настройки ---
raw_endpoint = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")

# Автоматически добавляем http://, если протокол забыли указать
if not raw_endpoint.startswith("http://") and not raw_endpoint.startswith("https://"):
    S3_ENDPOINT = f"http://{raw_endpoint}"
else:
    S3_ENDPOINT = raw_endpoint

S3_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
S3_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "supersecretpassword")

# Названия бакетов (корневых папок) в S3
S3_BUCKET_CHARTS = "charts"
S3_BUCKET_HANDLERS = "handlers"
S3_BUCKET_DATA = "data-sources"