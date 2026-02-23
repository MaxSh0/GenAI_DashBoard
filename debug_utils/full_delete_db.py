import os
import shutil
from sqlalchemy.orm import Session
# Импортируем всё необходимое из твоего приложения
from modules.db_manager import engine, Base
from modules.models import *  # Важно импортировать все модели, чтобы Base.metadata их видела
from modules.s3_storage import s3_client
from modules.settings import DATA_FOLDER, CHARTS_FOLDER, HANDLERS_FOLDER
from sqlalchemy import text  # ДОБАВЬ ЭТОТ ИМПОРТ НАВЕРХУ ФАЙЛА


def reset_database():
    print("🗑️  Удаление всех таблиц из PostgreSQL (CASCADE)...")
    try:
        # Жесткое удаление схемы вместе со всеми связями
        with engine.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE;"))
            conn.execute(text("CREATE SCHEMA public;"))
            conn.commit()  # Обязательно для SQLAlchemy 2.0+

        print("🏗️  Создание чистых таблиц...")
        Base.metadata.create_all(bind=engine)
        print("✅ База данных девственно чиста!")
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")


def reset_s3():
    buckets = ["charts", "handlers", "data-sources"]
    for bucket in buckets:
        print(f"☁️  Очистка S3 корзины: '{bucket}'...")
        try:
            # Получаем список файлов в корзине
            files = s3_client.list_files(bucket)
            if not files:
                print(f"   Корзина '{bucket}' уже пуста.")
                continue

            count = 0
            for f in files:
                s3_client.delete_file(bucket, f)
                count += 1
            print(f"✅ Удалено файлов из '{bucket}': {count}")
        except Exception as e:
            print(f"❌ Ошибка при очистке S3 ({bucket}): {e}")


def reset_local_cache():
    folders = [DATA_FOLDER, CHARTS_FOLDER, HANDLERS_FOLDER]
    for folder in folders:
        if not os.path.exists(folder):
            continue

        print(f"📁 Очистка локальной папки: '{folder}'...")
        count = 0
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            try:
                # Оставляем __init__.py, если он нужен для импортов
                if filename == "__init__.py":
                    continue

                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                    count += 1
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    count += 1
            except Exception as e:
                print(f"❌ Ошибка при удалении {file_path}: {e}")
        print(f"✅ Удалено файлов/папок из '{folder}': {count}")


if __name__ == "__main__":
    print("=====================================================")
    print("⚠️  ВНИМАНИЕ: ВЫ ЗАПУСКАЕТЕ ПОЛНУЮ ОЧИСТКУ ПЛАТФОРМЫ ⚠️")
    print("=====================================================")
    print("Это действие УДАЛИТ ВСЕ:")
    print(" - Пользователей и Воркспейсы")
    print(" - Настройки графиков и дашбордов")
    print(" - Файлы данных (CSV, Excel) в S3 и локально")
    print(" - Написанные скрипты ETL и код графиков")
    print("=====================================================")

    confirm = input("Вы абсолютно уверены? Введите 'YES' большими буквами для продолжения: ")

    if confirm == "YES":
        print("\n🚀 Начинаем зачистку...\n")
        reset_database()
        print("-" * 30)
        reset_s3()
        print("-" * 30)
        reset_local_cache()
        print("\n🎉 ОЧИСТКА ЗАВЕРШЕНА!")
        print("💡 Теперь вы можете запустить `python migrate.py`, чтобы загрузить базовых пользователей.")
    else:
        print("\n🛑 Отмена. Ваши данные в безопасности.")