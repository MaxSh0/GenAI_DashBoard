from modules.db_manager import SessionLocal, init_db
from modules.models import User, Workspace

# Твои данные пользователей
USERS_DATA = {
    "mshakurov": {
        "email": "user1@example.com",
        "name": "Максим Шакуров",
        "password": "$2b$12$OWKG7GbRBqgJfKoDxIbmM.70WVvHkdQYmPxc3eo9DQYoOa60JdTnm"
    },
    "dmarkarova": {
        "email": "user2@example.com",
        "name": "Дарья Маркарова",
        "password": "$2b$12$HI/N/pWAL9lSj1au1NpxjeRHqlAbGS0bazwGrmpvMr0H50OMC7UVS"
    }
}


def seed():
    print("🏗️ Проверка таблиц БД...")
    init_db()
    db = SessionLocal()

    try:
        for username, data in USERS_DATA.items():
            existing_user = db.query(User).filter(User.username == username).first()

            if not existing_user:
                # 1. Создаем пользователя
                user = User(
                    username=username,
                    password_hash=data['password'],
                    name=data['name'],
                    email=data['email']
                )
                db.add(user)
                db.flush()  # Получаем ID пользователя до коммита

                # 2. Создаем Личное Пространство (Workspace)
                ws = Workspace(name=f"Личное ({username})", owner_id=user.id)
                ws.users.append(user)
                db.add(ws)

                print(f"✅ Создан пользователь: {data['name']} (@{username}) + Личное пространство")
            else:
                print(f"⚠️ Пользователь @{username} уже существует. Пропускаем.")

        db.commit()
        print("\n🎉 База успешно наполнена пользователями!")

    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка БД: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()