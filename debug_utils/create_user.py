import streamlit_authenticator as stauth
from modules.db_manager import SessionLocal
from modules.models import User, Workspace


def create_user():
    print("\n" + "=" * 40)
    print("👤 ДОБАВЛЕНИЕ НОВОГО ПОЛЬЗОВАТЕЛЯ")
    print("=" * 40)

    # 1. Запрашиваем данные у админа
    username = input("Логин (username): ").strip()
    if not username:
        print("❌ Логин не может быть пустым!")
        return

    name = input("Полное Имя (например, Иван Иванов): ").strip()
    email = input("Email: ").strip()
    password = input("Пароль: ").strip()

    if not password:
        print("❌ Пароль не может быть пустым!")
        return

    # 2. Хешируем пароль тем же методом, что и раньше
    credentials = {'usernames': {username: {'password': password}}}
    stauth.Hasher.hash_passwords(credentials)
    hashed_password = credentials['usernames'][username]['password']

    # 3. Работаем с базой данных
    db = SessionLocal()
    try:
        # Проверяем, нет ли уже такого логина
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            print(f"\n⚠️ Ошибка: Пользователь с логином '{username}' уже существует!")
            return

        # Создаем пользователя
        new_user = User(
            username=username,
            name=name,
            email=email,
            password_hash=hashed_password
        )
        db.add(new_user)
        db.flush()  # Получаем ID пользователя до коммита

        # Создаем Личное Пространство
        ws = Workspace(name=f"Личное ({username})", owner_id=new_user.id)
        ws.users.append(new_user)
        db.add(ws)

        # Сохраняем всё в БД
        db.commit()

        print("\n" + "=" * 40)
        print(f"✅ УСПЕХ! Пользователь '{name}' (@{username}) добавлен.")
        print(f"🏢 Создано личное пространство: {ws.name}")
        print("=" * 40 + "\n")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Ошибка базы данных: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    create_user()