from modules.db_manager import SessionLocal
from modules.models import User, Page, Chart, DataSource
from modules.s3_storage import s3_client


def sync_environments():
    print("🔄 Начинаю двустороннюю синхронизацию S3 ↔ PostgreSQL...\n")
    db = SessionLocal()

    # Получаем всех пользователей для маппинга (username -> User Object)
    users_dict = {u.username: u for u in db.query(User).all()}

    if not users_dict:
        print("❌ В базе нет пользователей.")
        return

    # ==========================================
    # 1. СИНХРОНИЗАЦИЯ ГРАФИКОВ (CHARTS)
    # ==========================================
    print("📊 Проверка графиков...")
    s3_charts = s3_client.list_files("charts")
    db_charts = db.query(Chart).all()
    db_chart_names = [c.technical_name for c in db_charts]

    # Шаг 1.1: Ищем неучтенные файлы в S3 и добавляем их в БД
    for fname in s3_charts:
        if fname not in db_chart_names:
            # Пытаемся вытащить логин из названия (например, m.shakurov_chart.py)
            parts = fname.split('_', 1)
            if len(parts) == 2 and parts[0] in users_dict:
                user = users_dict[parts[0]]
                display_name = parts[1].replace('.py', '').capitalize()

                print(f"  ➕ Найден новый файл в S3: {fname}. Добавляю в БД...")
                new_chart = Chart(
                    user_id=user.id,
                    technical_name=fname,
                    display_name=display_name
                )
                db.add(new_chart)
                db.commit()
                db.refresh(new_chart)

                # Привязываем к Главной странице, чтобы юзер его увидел
                main_page = db.query(Page).filter(Page.user_id == user.id, Page.name == "Главная страница").first()
                if main_page and new_chart not in main_page.charts:
                    main_page.charts.append(new_chart)
                    db.commit()
            else:
                print(f"  ⚠️ Файл {fname} в S3 не имеет правильного префикса пользователя. Игнорирую.")

        # Шаг 1.2: Ищем "мертвые" записи в БД (нет файла в S3) и удаляем их
        for chart in db_charts:
            if chart.technical_name not in s3_charts:
                print(f"  🧹 Удаляю 'мертвую' запись из БД: {chart.technical_name}")

                # 1. Отвязываем график от всех страниц (решает ForeignKeyViolation)
                linked_pages = db.query(Page).filter(Page.charts.contains(chart)).all()
                for p in linked_pages:
                    p.charts.remove(chart)

                # 2. Отвязываем от источников данных (чтобы очистить chart_source_link)
                chart.data_sources = []

                # 3. Теперь базу ничего не держит, безопасно удаляем сам график
                db.delete(chart)

        db.commit()  # Сохраняем изменения

    # ==========================================
    # 2. СИНХРОНИЗАЦИЯ ДАННЫХ (DATA SOURCES)
    # ==========================================
    print("\n☁️ Проверка источников данных...")
    s3_sources = s3_client.list_files("data-sources")
    db_sources = db.query(DataSource).all()
    db_source_names = [s.filename for s in db_sources]

    # Шаг 2.1: Новые файлы из S3 -> в БД
    for fname in s3_sources:
        if fname not in db_source_names:
            parts = fname.split('_', 1)
            if len(parts) == 2 and parts[0] in users_dict:
                user = users_dict[parts[0]]
                print(f"  ➕ Найден новый файл данных в S3: {fname}. Добавляю в БД...")
                new_src = DataSource(
                    user_id=user.id,
                    connector_id="base",  # Считаем загруженный вручную файл базовым
                    filename=fname,
                    active=True
                )
                db.add(new_src)
            else:
                print(f"  ⚠️ Файл данных {fname} не имеет префикса пользователя. Игнорирую.")
    db.commit()

    # Шаг 2.2: Проверка потерянных файлов
    # (Мы не удаляем источники из БД, так как Google Sheets/YTsaurus могут еще не иметь
    # кэш-файла в S3 до первой синхронизации. Просто выводим предупреждение)
    for src in db_sources:
        if src.filename not in s3_sources:
            if src.connector_id == "base":
                print(f"  ⚠️ ВНИМАНИЕ: Локальный файл {src.filename} есть в БД, но отсутствует в S3!")
            else:
                print(f"  ℹ️ Облачный источник {src.filename} ({src.connector_id}) ждет первой синхронизации.")

    db.close()
    print("\n✨ Синхронизация успешно завершена!")


if __name__ == "__main__":
    sync_environments()