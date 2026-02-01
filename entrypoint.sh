#!/bin/bash

# Определяем пути
CONFIG_DIR="/app/config_store"
SECRET_FILE="$CONFIG_DIR/client_secret.json"
TOKEN_FILE="$CONFIG_DIR/user_token.json"
EXAMPLE_SECRET="/app/client_secret.example.json" # Мы скопируем его сюда в Dockerfile

echo "⚙️  Checking configuration..."

# 1. Проверяем client_secret.json
if [ ! -f "$SECRET_FILE" ]; then
    echo "⚠️  $SECRET_FILE not found. Creating from example..."
    if [ -f "$EXAMPLE_SECRET" ]; then
        cp "$EXAMPLE_SECRET" "$SECRET_FILE"
    else
        echo "{}" > "$SECRET_FILE"
    fi
else
    echo "✅  $SECRET_FILE exists."
fi

# 2. Проверяем user_token.json
if [ ! -f "$TOKEN_FILE" ]; then
    echo "⚠️  $TOKEN_FILE not found. Creating empty token file..."
    echo "{}" > "$TOKEN_FILE"
else
    echo "✅  $TOKEN_FILE exists."
fi

# 3. Запускаем основное приложение (передаем управление команде из CMD)
echo "🚀 Starting Streamlit..."
exec "$@"