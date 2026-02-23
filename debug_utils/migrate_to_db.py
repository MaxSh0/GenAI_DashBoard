import os
import yaml
from sqlalchemy.orm import Session
from modules.db_manager import engine, SessionLocal, init_db
# Импортируем НОВЫЕ модели (Workspace и ETLHandler)
from modules.models import User, Page, Chart, DataSource, Workspace, ETLHandler
from modules.utils import load_json
from modules.settings import CONFIG_FOLDER


def migrate():
    # 1. Инициализируем таблицы в Postgres
    print("🏗️ Создаем таблицы в PostgreSQL...")
    init_db()

    db = SessionLocal()

    try:
        # 2. Миграция пользователей из config/users.yaml
        users_yaml_path = os.path.join('../config', 'users.yaml')
        if os.path.exists(users_yaml_path):
            with open(users_yaml_path, 'r') as f:
                users_data = yaml.safe_load(f)

            for username, data in users_data['credentials']['usernames'].items():
                # Проверяем, нет ли уже такого юзера
                existing_user = db.query(User).filter(User.username == username).first()
                if not existing_user:
                    user = User(
                        username=username,
                        password_hash=data['password'],
                        name=data['name'],
                        email=data.get('email', '')
                    )
                    db.add(user)
                    db.flush()  # Получаем ID юзера для связей
                    print(f"✅ Перенесен пользователь: {username}")

                    # --- НОВОЕ: СОЗДАЕМ ЛИЧНОЕ ПРОСТРАНСТВО (WORKSPACE) ---
                    ws = Workspace(name=f"Личное ({username})", owner_id=user.id)
                    ws.users.append(user)
                    db.add(ws)
                    db.flush()  # Получаем ID воркспейса для привязки данных
                    print(f"   🏢 Создано пространство: {ws.name}")

                    # 3. Для каждого пользователя ищем его конфиги

                    # Словарь для восстановления связей ETL
                    handlers_map = {}

                    # Миграция Источников (sources)
                    sources_path = os.path.join(CONFIG_FOLDER, f"{username}_sources.json")
                    old_sources = load_json(sources_path, {}).get("sources", [])
                    for s in old_sources:
                        # Восстанавливаем обработчики
                        old_handler_name = s.get("handler")
                        h_id = None

                        if old_handler_name and old_handler_name != "None":
                            if old_handler_name not in handlers_map:
                                # Создаем запись в БД для старого скрипта
                                pretty_name = old_handler_name.replace(".py", "").replace(f"{username}_", "")
                                new_h = ETLHandler(
                                    workspace_id=ws.id,
                                    name=pretty_name.capitalize(),
                                    technical_name=old_handler_name
                                )
                                db.add(new_h)
                                db.flush()
                                handlers_map[old_handler_name] = new_h.id
                            h_id = handlers_map[old_handler_name]

                        ds = DataSource(
                            workspace_id=ws.id,  # <-- ТЕПЕРЬ ПРИВЯЗКА К WORKSPACE
                            connector_id=s.get("connector_id", "base"),
                            filename=s.get("filename"),
                            config_json=s.get("config"),
                            active=s.get("active", True),
                            handler_id=h_id  # <-- ТЕПЕРЬ ССЫЛАЕМСЯ ПО ID
                        )
                        db.add(ds)

                    # Миграция Графиков и их названий
                    titles_path = os.path.join(CONFIG_FOLDER, f"{username}_titles.json")
                    old_titles = load_json(titles_path, {})

                    chart_map = {}  # Для связи со страницами
                    for tech_name, disp_name in old_titles.items():
                        if tech_name == "app_title": continue
                        ch = Chart(
                            workspace_id=ws.id,  # <-- ТЕПЕРЬ ПРИВЯЗКА К WORKSPACE
                            technical_name=tech_name,
                            display_name=disp_name
                        )
                        db.add(ch)
                        db.flush()
                        chart_map[tech_name] = ch

                    # Миграция Страниц
                    pages_path = os.path.join(CONFIG_FOLDER, f"{username}_pages.json")
                    old_pages = load_json(pages_path, {})
                    for p_name, chart_list in old_pages.items():
                        pg = Page(workspace_id=ws.id, name=p_name)  # <-- ТЕПЕРЬ ПРИВЯЗКА К WORKSPACE
                        for ch_tech_name in chart_list:
                            if ch_tech_name in chart_map:
                                pg.charts.append(chart_map[ch_tech_name])
                        db.add(pg)

        db.commit()
        print("\n🎉 Миграция успешно завершена! База наполнена.")
    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка миграции: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()