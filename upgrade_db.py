from sqlalchemy import text
from modules.db_manager import engine

def upgrade():
    print("🛠️ Обновляю структуру базы данных...")
    try:
        with engine.connect() as conn:
            # Добавляем колонку, если её нет
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_token TEXT;"))
            conn.commit()
        print("✅ Колонка 'google_token' успешно добавлена в таблицу 'users'!")
    except Exception as e:
        print(f"⚠️ Ошибка (возможно колонка уже существует): {e}")

if __name__ == "__main__":
    upgrade()