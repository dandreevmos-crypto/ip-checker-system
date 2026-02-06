#!/bin/bash

# IP Checker System - Скрипт остановки

echo "🛑 Остановка IP Checker System..."

# Остановка туннеля
if pkill cloudflared 2>/dev/null; then
    echo "✅ Cloudflare Tunnel остановлен"
else
    echo "ℹ️  Туннель не был запущен"
fi

# Остановка сервера
if pkill -f "python.*app.py" 2>/dev/null; then
    echo "✅ Flask сервер остановлен"
else
    echo "ℹ️  Сервер не был запущен"
fi

echo ""
echo "🏁 Приложение остановлено"
