import os
import glob
from modules.settings import CHARTS_FOLDER, HANDLERS_FOLDER, DATA_FOLDER
from modules.s3_storage import s3_client
from modules.db_manager import SessionLocal
from modules.models import User, Page, Chart, DataSource


def migrate_all():
    print("🚀 Запуск глобальной миграции файлов в S3 и синхронизации с БД...")
    db = SessionLocal()
    users = db.query(User).all()

    if not users:
        print("❌ В базе нет пользователей. Сначала зарегистрируйтесь.")
        return

    # Инициализация бакетов
    s3_client.init_buckets(["charts", "handlers", "data-sources"])

    # ==========================================
    # 1. МИГРАЦИЯ ГРАФИКОВ (CHARTS)
    # ==========================================
    print("\n📊 1. Миграция графиков (CHARTS)...")
    local_charts = [f for f in os.listdir(CHARTS_FOLDER) if f.endswith('.py') and f != '__init__.py']

    for user in users:
        print(f"\n👤 Обработка пользователя: {user.username}")

        # Получаем или создаем главную страницу для пользователя
        main_page = db.query(Page).filter(Page.user_id == user.id, Page.name == "Главная страница").first()
        if not main_page:
            main_page = Page(user_id=user.id, name="Главная страница")
            db.add(main_page);
            db.commit();
            db.refresh(main_page)

        for chart_file in local_charts:
            # Защита от дублирования: если файл уже имеет префикс ДРУГОГО пользователя - пропускаем
            if "_" in chart_file:
                prefix = chart_file.split("_")[0]
                if prefix != user.username and prefix in [u.username for u in users]:
                    continue

            # Формируем целевое имя (добавляем префикс юзера, если его нет)
            if chart_file.startswith(f"{user.username}_"):
                target_name = chart_file
                display_name = chart_file.replace(f"{user.username}_", "").replace(".py", "").capitalize()
            else:
                target_name = f"{user.username}_{chart_file}"
                display_name = chart_file.replace(".py", "").capitalize()

            local_path = os.path.join(CHARTS_FOLDER, chart_file)

            # 1.1 Загружаем в S3
            try:
                s3_client.upload_file(local_path, "charts", target_name)
            except Exception as e:
                print(f"    ❌ Ошибка загрузки {target_name} в S3: {e}")

            # 1.2 Создаем/обновляем запись в БД
            chart_db = db.query(Chart).filter(Chart.user_id == user.id, Chart.technical_name == target_name).first()
            if not chart_db:
                chart_db = Chart(user_id=user.id, technical_name=target_name, display_name=display_name)
                db.add(chart_db);
                db.commit();
                db.refresh(chart_db)

            # 1.3 Привязываем к странице
            if chart_db not in main_page.charts:
                main_page.charts.append(chart_db)
                db.commit()

            print(f"    ✅ График: {target_name} (S3 + БД)")

    # ==========================================
    # 2. МИГРАЦИЯ ДАННЫХ (DATA SOURCES)
    # ==========================================
    print("\n☁️ 2. Миграция файлов данных (DATA)...")
    data_files = []
    for ext in ["*.csv", "*.xlsx", "*.xls"]:
        data_files.extend(glob.glob(os.path.join(DATA_FOLDER, ext)))

    for user in users:
        for f_path in data_files:
            f_name = os.path.basename(f_path)

            # Защита от чужих файлов
            if "_" in f_name:
                prefix = f_name.split("_")[0]
                if prefix != user.username and prefix in [u.username for u in users]:
                    continue

            target_name = f_name if f_name.startswith(f"{user.username}_") else f"{user.username}_{f_name}"

            # 2.1 В S3
            try:
                s3_client.upload_file(f_path, "data-sources", target_name)
            except Exception as e:
                pass  # Если уже есть, ничего страшного

            # 2.2 В Базу Данных
            src_db = db.query(DataSource).filter(DataSource.user_id == user.id,
                                                 DataSource.filename == target_name).first()
            if not src_db:
                src_db = DataSource(
                    user_id=user.id,
                    connector_id="base",  # Локальный файл по умолчанию
                    filename=target_name,
                    active=True
                )
                db.add(src_db);
                db.commit()

            print(f"    ✅ Файл: {target_name} (S3 + БД)")

    # ==========================================
    # 3. МИГРАЦИЯ ОБРАБОТЧИКОВ (HANDLERS)
    # ==========================================
    print("\n🛠️ 3. Миграция обработчиков (HANDLERS)...")
    handlers = [f for f in os.listdir(HANDLERS_FOLDER) if f.endswith('.py') and f != '__init__.py']
    for h_file in handlers:
        h_path = os.path.join(HANDLERS_FOLDER, h_file)
        try:
            s3_client.upload_file(h_path, "handlers", h_file)
            print(f"    ✅ Скрипт {h_file} загружен в S3.")
        except Exception as e:
            print(f"    ❌ Ошибка S3 для {h_file}: {e}")

    print("\n✨ МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА! ✨")
    db.close()


if __name__ == "__main__":
    migrate_all()