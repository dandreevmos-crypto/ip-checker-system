#!/bin/bash

# IP Checker System - Скрипт запуска
# Запускает сервер и публикует приложение через Cloudflare Tunnel

PROJECT_DIR="/Users/olgaandreeva/Documents/Claude/Search trademarks and picture/ip_checker_system"
cd "$PROJECT_DIR"

echo "🚀 Запуск IP Checker System..."

# Проверяем, не запущен ли уже сервер
if lsof -i :5001 > /dev/null 2>&1; then
    echo "⚠️  Порт 5001 уже занят. Останавливаем старый процесс..."
    pkill -f "python.*app.py"
    sleep 2
fi

# Останавливаем старый туннель если есть
pkill cloudflared 2>/dev/null

# Запускаем сервер Flask
echo "📦 Запуск Flask сервера..."
nohup "$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/src/app.py" > "$PROJECT_DIR/server.log" 2>&1 &
SERVER_PID=$!

# Ждём запуска сервера
sleep 3

# Проверяем что сервер запустился
if curl -s http://localhost:5001 > /dev/null; then
    echo "✅ Сервер запущен на http://localhost:5001"
else
    echo "❌ Ошибка запуска сервера. Проверьте server.log"
    exit 1
fi

# Запускаем Cloudflare Tunnel
echo "🌐 Создание публичного туннеля..."
nohup cloudflared tunnel --url http://localhost:5001 > "$PROJECT_DIR/cloudflared.log" 2>&1 &
TUNNEL_PID=$!

# Ждём создания туннеля
echo "⏳ Ожидание URL туннеля..."
sleep 8

# Получаем URL
PUBLIC_URL=$(grep -o "https://.*trycloudflare.com" "$PROJECT_DIR/cloudflared.log" | tail -1)

if [ -n "$PUBLIC_URL" ]; then
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "✅ ПРИЛОЖЕНИЕ ОПУБЛИКОВАНО!"
    echo ""
    echo "🏠 Локальный URL:   http://localhost:5001"
    echo "🌐 Публичный URL:   $PUBLIC_URL"
    echo ""
    echo "📜 История:         $PUBLIC_URL/history"
    echo "════════════════════════════════════════════════════════════"
    echo ""
    echo "Для остановки выполните: ./stop.sh"
else
    echo "⚠️  Не удалось получить публичный URL. Проверьте cloudflared.log"
    echo "🏠 Локальный URL: http://localhost:5001"
fi
