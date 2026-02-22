import os
import yaml
from sqlalchemy.orm import Session
from modules.db_manager import engine, SessionLocal, init_db
from modules.models import User, Page, Chart, DataSource
from modules.utils import load_json
from modules.settings import CONFIG_FOLDER


def migrate():
    # 1. Инициализируем таблицы в Postgres
    print("🏗️ Создаем таблицы в PostgreSQL...")
    init_db()

    db = SessionLocal()

    try:
        # 2. Миграция пользователей из config/users.yaml
        users_yaml_path = os.path.join('config', 'users.yaml')
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
                        email=data['email']
                    )
                    db.add(user)
                    db.flush()  # Получаем ID юзера для связей
                    print(f"✅ Перенесен пользователь: {username}")

                    # 3. Для каждого пользователя ищем его конфиги
                    # Миграция Источников (sources)
                    sources_path = os.path.join(CONFIG_FOLDER, f"{username}_sources.json")
                    old_sources = load_json(sources_path, {}).get("sources", [])
                    for s in old_sources:
                        ds = DataSource(
                            user_id=user.id,
                            connector_id=s.get("connector_id"),
                            filename=s.get("filename"),
                            config_json=s.get("config"),
                            handler_name=s.get("handler"),
                            active=s.get("active", True)
                        )
                        db.add(ds)

                    # Миграция Графиков и их названий
                    titles_path = os.path.join(CONFIG_FOLDER, f"{username}_titles.json")
                    old_titles = load_json(titles_path, {})

                    chart_map = {}  # Для связи со страницами
                    for tech_name, disp_name in old_titles.items():
                        if tech_name == "app_title": continue
                        ch = Chart(
                            user_id=user.id,
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
                        pg = Page(user_id=user.id, name=p_name)
                        for ch_tech_name in chart_list:
                            if ch_tech_name in chart_map:
                                pg.charts.append(chart_map[ch_tech_name])
                        db.add(pg)

        db.commit()
        print("\n🎉 Миграция успешно завершена!")
    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка миграции: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()