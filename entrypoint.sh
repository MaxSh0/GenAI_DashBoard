#!/bin/bash
# Останавливать скрипт при ошибках
set -e

echo "⚙️ Проверка конфигурации..."

# 1. Создаем папку config, если её нет (внутри контейнера)
mkdir -p /app/config

# 2. Проверяем файл секретов Google
if [ ! -f /app/config/client_secret.json ]; then
    echo "⚠️ client_secret.json не найден. Создаем пустой шаблон..."
    if [ -f /app/client_secret.example.json ]; then
        cp /app/client_secret.example.json /app/config/client_secret.json
    else
        echo '{"web":{}}' > /app/config/client_secret.json
    fi
fi

# 3. Проверяем файл пользователей (нужен для миграции в БД)
if [ ! -f /app/config/users.yaml ]; then
    echo "⚠️ users.yaml не найден. Создаем пустой..."
    echo "credentials: {usernames: {}}" > /app/config/users.yaml
fi

# ВАЖНО: exec "$@" запускает команду, переданную в CMD (из docker-compose или Dockerfile)
# Это позволит запускать и 'streamlit run...', и 'celery -A modules.tasks worker...'
echo "🚀 Запуск команды: $@"
exec "$@"