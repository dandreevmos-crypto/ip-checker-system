# История изменений IP Checker System

## Версия 1.1.0 (2026-02-04)

### Проверка товарных знаков

#### Изменения в `src/config.py`:
1. **Переименован ресурс Linkmark** → "Проверка товарного знака"
   ```python
   "linkmark": {
       "name": "Проверка товарного знака",  # было: "Linkmark"
       "description": "Поиск по зарегистрированным словесным/комбинированным обозначениям РФ",
       "limitations": "Данные из базы ФИПС/Роспатента"
   }
   ```

2. **Добавлен API ключ Роспатента**:
   ```python
   API_KEYS = {
       "rospatent": "0deb6def77394a5fbb0dd1af0571c336",
       ...
   }
   ```

#### Изменения в `src/trademark_checker.py`:

1. **Убран Роспатент из активных проверок** (оставлен только для ссылок):
   ```python
   # Было:
   self.checkers = {
       "rospatent": RospatentPlatformChecker(),
       "linkmark": LinkmarkChecker(),
       "wipo": WIPOChecker()
   }

   # Стало:
   self.checkers = {
       "linkmark": LinkmarkChecker(),
       "wipo": WIPOChecker()
   }
   ```

2. **Упрощена логика проверки российских баз**:
   ```python
   # Было:
   for checker_name in ["rospatent", "linkmark"]:
       checker = self.checkers[checker_name]
       result = checker.check_trademark(text, mktu_classes)
       results.append(result)
       time.sleep(1)

   # Стало:
   linkmark_result = self.checkers["linkmark"].check_trademark(text, mktu_classes)
   results.append(linkmark_result)
   ```

3. **Обновлены текстовые сообщения**:
   - `"Совпадений в базе Linkmark не найдено"` → `"Совпадений в базе ТЗ РФ не найдено"`
   - `"Ошибка подключения к Linkmark"` → `"Ошибка подключения"`
   - `links["Linkmark"]` → `links["Проверка ТЗ РФ"]`

---

### Проверка изображений

#### Новый API endpoint в `src/app.py`:

**`POST /api/check/image`** - Полная проверка изображения

Параметры (multipart/form-data):
- `file` - изображение (обязательно)
- `text` - текст для проверки вручную (опционально)
- `mktu_classes` - классы МКТУ (опционально)

Возвращает JSON:
```json
{
    "filename": "image.png",
    "filepath": "/path/to/image.png",
    "image_url": "/uploads/abc123/image.png",
    "recognized_texts": [
        {"text": "NIKE", "confidence": 95.5}
    ],
    "trademark_results": [
        {
            "text": "Nike",
            "resource": "Проверка товарного знака",
            "status": "red",
            "exact_match": true,
            "similarity_score": 1.0,
            "notes": "Найден тождественный ТЗ!",
            "matches": [...]
        }
    ],
    "image_search_links": {
        "yandex": {"name": "Яндекс.Картинки", "url": "...", "instruction": "..."},
        "google": {"name": "Google Images", "url": "...", "instruction": "..."},
        "tineye": {"name": "TinEye", "url": "...", "instruction": "..."},
        "bing": {"name": "Bing Visual Search", "url": "...", "instruction": "..."}
    },
    "trademark_links": {
        "ФИПС (реестр)": "...",
        "Проверка ТЗ РФ": "...",
        "WIPO Global Brand": "...",
        "EUIPO": "..."
    },
    "overall_status": "red|yellow|green",
    "risk_factors": [
        {"type": "trademark", "severity": "red", "message": "..."}
    ],
    "recommendations": ["..."],
    "summary": {
        "texts_found": 0,
        "texts_checked": 1,
        "tm_checks": 2,
        "risk_factors_count": 1
    }
}
```

**`GET /uploads/<path:filename>`** - Отдача загруженных изображений

#### Логика работы:
1. Сохранение изображения в `data/uploads/<uuid>/`
2. Попытка OCR (распознавание текста)
3. Проверка найденных брендов/персонажей
4. Поиск по товарным знакам (Linkmark + WIPO)
5. Генерация ссылок для обратного поиска
6. Формирование рекомендаций
7. Определение общего статуса

---

### Обновление интерфейса `templates/index.html`

#### Блок загрузки изображения:
- Добавлен предпросмотр изображения
- Добавлено поле для ввода текста вручную
- Добавлен выбор класса МКТУ
- Кнопка "Проверить изображение"

```html
<div id="imagePreviewArea">
    <img id="imagePreview" src="">
    <input type="text" id="imageManualText" placeholder="Текст для проверки">
    <select id="imageMktuClass">...</select>
    <button onclick="checkSingleImage()">Проверить изображение</button>
</div>
```

#### Блок результатов проверки изображения:
Новый блок `#imageCheckResults` с вкладками:
1. **Товарные знаки** - таблица найденных совпадений
2. **Распознанный текст** - список OCR результатов
3. **Поиск в интернете** - кнопки для открытия поисковиков
4. **Рекомендации** - список рекомендаций и факторов риска

#### JavaScript функции:
- `previewImage(file)` - предпросмотр изображения
- `checkSingleImage()` - отправка на проверку
- `displayImageCheckResults(data)` - отображение результатов
- `closeImageResults()` - закрытие результатов

---

## Структура проекта

```
ip_checker_system/
├── run.py                 # Запуск приложения
├── src/
│   ├── app.py            # Flask приложение + API endpoints
│   ├── config.py         # Конфигурация, API ключи, ресурсы
│   ├── models.py         # Модели данных
│   ├── trademark_checker.py  # Проверка товарных знаков
│   ├── image_checker.py  # Проверка изображений, OCR
│   ├── risk_evaluator.py # Оценка рисков (светофор)
│   ├── data_loader.py    # Загрузка данных из Excel
│   └── export_manager.py # Экспорт результатов
├── templates/
│   └── index.html        # Веб-интерфейс
├── data/
│   └── uploads/          # Загруженные файлы
├── output/               # Экспортированные отчёты
└── venv/                 # Виртуальное окружение
```

---

## Запуск

```bash
cd ip_checker_system
./venv/bin/python run.py
```

Открыть в браузере: http://127.0.0.1:5001

---

## API Endpoints

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/` | Главная страница |
| POST | `/api/check/single` | Проверка текста на ТЗ |
| POST | `/api/check/image` | **НОВОЕ** Проверка изображения |
| POST | `/api/upload/excel` | Загрузка Excel файла |
| POST | `/api/upload/images` | Массовая загрузка изображений |
| POST | `/api/check/session/<id>` | Запуск проверки сессии |
| GET | `/api/session/<id>` | Получение данных сессии |
| GET | `/api/export/<id>/<format>` | Экспорт (excel/csv/html/json) |
| GET | `/api/template` | Скачать шаблон Excel |
| GET | `/api/resources` | Список ресурсов |
| POST | `/api/check/links` | Получить ссылки для проверки |
| GET | `/uploads/<path>` | **НОВОЕ** Отдача загруженных файлов |

---

## Зависимости

Установленные:
- Flask, Flask-CORS
- requests, BeautifulSoup4
- Pillow, imagehash
- pandas, openpyxl
- Levenshtein
- transliterate

Опциональные (для OCR):
- pytesseract (+ Tesseract OCR)
- easyocr
