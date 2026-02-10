#!/bin/bash

# IP Checker - Быстрая публикация
# Запускает сервер и создаёт публичную ссылку

echo "🚀 Публикация IP Checker..."

# Останавливаем старые процессы
pkill -f "python.*app.py" 2>/dev/null
pkill cloudflared 2>/dev/null
sleep 1

# Запускаем сервер
cd "$(dirname "$0")/src"
python3 app.py > /tmp/ipchecker_server.log 2>&1 &
sleep 5

# Проверяем сервер
if ! curl -s http://localhost:5001 > /dev/null; then
    echo "❌ Ошибка запуска сервера"
    exit 1
fi

echo "✅ Сервер запущен"

# Создаём туннель
/usr/local/opt/cloudflared/bin/cloudflared tunnel --url http://localhost:5001 > /tmp/cloudflared.log 2>&1 &
echo "⏳ Создание публичной ссылки..."
sleep 8

# Получаем URL
PUBLIC_URL=$(grep -o "https://.*trycloudflare.com" /tmp/cloudflared.log | tail -1)

if [ -n "$PUBLIC_URL" ]; then
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "✅ СИСТЕМА ОПУБЛИКОВАНА!"
    echo ""
    echo "🌐 ССЫЛКА ДЛЯ ПОЛЬЗОВАТЕЛЕЙ:"
    echo ""
    echo "   $PUBLIC_URL"
    echo ""
    echo "📜 История: $PUBLIC_URL/history"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "Для остановки: ./stop.sh"
else
    echo "❌ Не удалось получить ссылку. Проверьте /tmp/cloudflared.log"
fi
