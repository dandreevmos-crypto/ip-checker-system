# 🚀 Быстрый старт - IP Checker System

## Запуск приложения

### 1. Запуск сервера

```bash
cd /Users/olgaandreeva/Documents/Claude/Search\ trademarks\ and\ picture/ip_checker_system/src
source ../venv/bin/activate
python app.py
```

Сервер будет доступен: http://localhost:5001

### 2. Публикация в интернет

```bash
cloudflared tunnel --url http://localhost:5001
```

Скопируйте URL из вывода (вида `https://xxx-xxx.trycloudflare.com`)

### 3. Запуск всего в фоне (одной командой)

```bash
cd /Users/olgaandreeva/Documents/Claude/Search\ trademarks\ and\ picture/ip_checker_system

# Запуск сервера
nohup /Users/olgaandreeva/Documents/Claude/Search\ trademarks\ and\ picture/ip_checker_system/venv/bin/python src/app.py > server.log 2>&1 &

# Запуск туннеля
nohup cloudflared tunnel --url http://localhost:5001 > cloudflared.log 2>&1 &

# Получить публичный URL через 5 секунд
sleep 5 && grep -o "https://.*trycloudflare.com" cloudflared.log | tail -1
```

## Остановка

```bash
# Остановить туннель
pkill cloudflared

# Остановить сервер
pkill -f "python.*app.py"
```

## Проверка статуса

```bash
# Сервер работает?
curl -s http://localhost:5001 > /dev/null && echo "✅ Сервер работает" || echo "❌ Сервер не работает"

# Туннель работает?
ps aux | grep cloudflared | grep -v grep && echo "✅ Туннель активен"

# Текущий публичный URL
grep -o "https://.*trycloudflare.com" cloudflared.log | tail -1
```

## Полезные ссылки

- **Главная страница:** http://localhost:5001
- **История проверок:** http://localhost:5001/history
- **Serper API (для ключа):** https://serper.dev/

## Структура файлов

```
ip_checker_system/
├── src/app.py          # Главное приложение
├── src/config.py       # Настройки и API ключи
├── templates/          # HTML шаблоны
├── uploads/            # Загруженные изображения
├── ip_checker.db       # База данных
├── server.log          # Лог сервера
└── cloudflared.log     # Лог туннеля (содержит URL)
```
