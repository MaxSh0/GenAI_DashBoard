FROM python:3.13-slim

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем пример конфига отдельно (чтобы он был источником правды)
COPY client_secret.example.json /app/client_secret.example.json

# Копируем скрипт инициализации
COPY entrypoint.sh /app/entrypoint.sh

# Копируем весь код
COPY . .

RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# ВАЖНО: Указываем entrypoint
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]

# Команда запуска остается прежней
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]