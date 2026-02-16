FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    libglib2.0-0 \
    libgl1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем проект
COPY . .

# Создаём необходимые директории
RUN mkdir -p data/uploads data/history output

# Переменные окружения
ENV PORT=10000
ENV PYTHONUNBUFFERED=1

# Запуск
CMD gunicorn --chdir src app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1
