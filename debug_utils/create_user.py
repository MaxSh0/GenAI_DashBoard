import streamlit_authenticator as stauth

# 1. Создаем словарь в том же формате, что и в файле users.yaml
credentials = {
    'usernames': {
        'user1': {
            'password': 'max' # Пишем открытый пароль
        },
        'user2': {
            'password': 'dasha'
        }
    }
}

# 2. Метод хэширует пароли прямо внутри словаря
stauth.Hasher.hash_passwords(credentials)

# 3. Выводим готовые хэши, чтобы скопировать их в конфиг
print("Ваши хэши для users.yaml:\n")
for username, user_data in credentials['usernames'].items():
    print(f"Пользователь: {username}")
    print(f"Хэш: {user_data['password']}\n")