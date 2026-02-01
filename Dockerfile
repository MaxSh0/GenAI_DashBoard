# Используем ту же версию, что и у вас на Mac
FROM python:3.13-slim

# Отключаем буферизацию (логи сразу в консоль) и pyc файлы
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Устанавливаем системные зависимости (нужны для сборки некоторых библиотек на 3.13)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Сначала копируем зависимости (для кэширования)
COPY requirements.txt .

# Устанавливаем библиотеки
# --no-cache-dir уменьшает размер образа
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Порт
EXPOSE 8501

# Проверка здоровья
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Запуск
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]