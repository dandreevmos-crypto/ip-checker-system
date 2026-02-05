#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Запуск системы проверки интеллектуальной собственности
"""

import os
import sys
import webbrowser
from pathlib import Path
from time import sleep

# Добавляем путь к src
sys.path.insert(0, str(Path(__file__).parent / 'src'))

def main():
    """Главная функция запуска"""
    print("=" * 70)
    print("   СИСТЕМА ПРОВЕРКИ ИНТЕЛЛЕКТУАЛЬНОЙ СОБСТВЕННОСТИ")
    print("   IP Checker System v1.0")
    print("=" * 70)
    print()
    print("Функции системы:")
    print("  - Проверка обозначений на товарные знаки (ФИПС, WIPO, Linkmark)")
    print("  - Обратный поиск изображений (Яндекс, Google, TinEye)")
    print("  - Распознавание текста на изображениях (OCR)")
    print("  - Оценка рисков по принципу светофора")
    print("  - Экспорт результатов в Excel, CSV, HTML, JSON")
    print()
    print("-" * 70)

    # Проверка зависимостей
    try:
        from flask import Flask
        print("[OK] Flask установлен")
    except ImportError:
        print("[!] Flask не установлен. Выполните: pip install flask")
        return

    try:
        import pandas
        print("[OK] Pandas установлен")
    except ImportError:
        print("[!] Pandas не установлен. Выполните: pip install pandas openpyxl")
        return

    print()
    print("-" * 70)

    # Импорт и запуск приложения
    from config import APP_CONFIG
    port = APP_CONFIG['port']
    url = f"http://localhost:{port}"

    print(f"Запуск веб-сервера на {url}")
    print("Для остановки нажмите Ctrl+C")
    print("-" * 70)
    print()

    # Открываем браузер через 2 секунды
    def open_browser():
        sleep(2)
        webbrowser.open(url)

    import threading
    browser_thread = threading.Thread(target=open_browser)
    browser_thread.daemon = True
    browser_thread.start()

    # Запускаем Flask
    from app import app
    app.run(
        host=APP_CONFIG['host'],
        port=port,
        debug=APP_CONFIG['debug']
    )


if __name__ == '__main__':
    main()
