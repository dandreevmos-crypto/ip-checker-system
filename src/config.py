# -*- coding: utf-8 -*-
"""
Конфигурация системы проверки интеллектуальной собственности
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List

# Базовые пути
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Создание директорий при необходимости
for dir_path in [DATA_DIR, OUTPUT_DIR]:
    dir_path.mkdir(exist_ok=True)

# API ключи для внешних сервисов
API_KEYS = {
    "rospatent": os.environ.get("ROSPATENT_API_KEY", "0deb6def77394a5fbb0dd1af0571c336"),
    "tineye": os.environ.get("TINEYE_API_KEY", ""),
    "serpapi": os.environ.get("SERPAPI_KEY", ""),
}


@dataclass
class TrafficLightStatus:
    """Статусы по принципу светофора"""
    RED = "red"           # Запрещено использовать
    YELLOW = "yellow"     # Требуется дополнительная проверка
    GREEN = "green"       # Можно использовать

    LABELS = {
        "red": "ЗАПРЕЩЕНО - Нельзя использовать",
        "yellow": "ВНИМАНИЕ - Требуется дополнительная проверка",
        "green": "РАЗРЕШЕНО - Можно использовать"
    }

    DESCRIPTIONS = {
        "red": [
            "Найден зарегистрированный тождественный/сходный товарный знак",
            "Имеется поданная заявка на такой товарный знак",
            "Изображение принадлежит конкретному автору без согласия",
            "Используется известный персонаж/бренд без разрешения",
            "Скопирован дизайн товара/товар идентичен"
        ],
        "yellow": [
            "Найдено частичное сходство с существующими ТЗ",
            "Изображение найдено в интернете (источник неясен)",
            "Требуется проверка по дополнительным базам",
            "Необходимо уточнить права на использование"
        ],
        "green": [
            "Проверка не выявила нарушений",
            "Имеются документы на права использования",
            "Изображение создано штатным дизайнером с передачей прав",
            "Использована свободная лицензия (подтверждено)"
        ]
    }


# Ресурсы для проверки товарных знаков
TRADEMARK_RESOURCES = {
    "fips": {
        "name": "ФИПС / Роспатент",
        "url": "https://www1.fips.ru/registers-web/",
        "search_url": "https://www1.fips.ru/registers-web/action?acName=clickRegister&regName=RUTM",
        "bulletins_url": "https://www1.fips.ru/publication-web/bulletins/UsrTM",
        "description": "Официальный государственный ресурс",
        "free": True,
        "limitations": "Бесплатная проверка только по регистрационным номерам"
    },
    "rospatent_platform": {
        "name": "Платформа Роспатента",
        "url": "https://searchplatform.rospatent.gov.ru/trademarks",
        "description": "Поиск по словам, изображениям и классам МКТУ",
        "free": True,
        "limitations": "Ограниченное количество результатов, обновление через сутки"
    },
    "linkmark": {
        "name": "Проверка товарного знака",
        "url": "https://linkmark.ru/",
        "description": "Поиск по зарегистрированным словесным/комбинированным обозначениям РФ",
        "free": True,
        "limitations": "Данные из базы ФИПС/Роспатента"
    },
    "wipo": {
        "name": "WIPO Global Brand Database",
        "url": "https://branddb.wipo.int/",
        "search_url": "https://branddb.wipo.int/en/similarname",
        "description": "Международная база товарных знаков",
        "free": True,
        "limitations": None
    },
    "euipo": {
        "name": "EUIPO",
        "url": "https://euipo.europa.eu/",
        "description": "База товарных знаков ЕС (если товар доступен за рубежом)",
        "free": True,
        "limitations": "Только для товаров, доступных в ЕС"
    }
}

# Ресурсы для обратного поиска изображений
IMAGE_SEARCH_RESOURCES = {
    "yandex": {
        "name": "Яндекс.Картинки",
        "url": "https://ya.ru/images",
        "description": "Поиск по картинке",
        "priority": 1
    },
    "google": {
        "name": "Google Images",
        "url": "https://images.google.ru/",
        "description": "Reverse image search",
        "priority": 2
    },
    "tineye": {
        "name": "TinEye",
        "url": "https://tineye.com/",
        "description": "Специализированный сервис обратного поиска изображений",
        "priority": 3
    },
    "bing": {
        "name": "Bing Visual Search",
        "url": "https://www.bing.com/visualsearch",
        "description": "Визуальный поиск Microsoft",
        "priority": 4
    },
    "pinterest": {
        "name": "Pinterest",
        "url": "https://ru.pinterest.com/",
        "description": "Платформа для публикации графических материалов",
        "priority": 5
    }
}

# Дополнительные ресурсы для проверки авторских прав
COPYRIGHT_RESOURCES = {
    "behance": {
        "name": "Behance",
        "url": "https://www.behance.net/",
        "description": "Портфолио дизайнеров и художников"
    },
    "illustrators": {
        "name": "Illustrators.ru",
        "url": "https://illustrators.ru/",
        "description": "Российское сообщество иллюстраторов"
    },
    "vk": {
        "name": "ВКонтакте",
        "url": "https://vk.com/",
        "description": "Социальная сеть с графическим контентом"
    },
    "telegram": {
        "name": "Telegram",
        "url": "https://telegram.org/",
        "description": "Мессенджер с каналами и графикой"
    }
}

# Классы МКТУ (Международная классификация товаров и услуг)
MKTU_CLASSES = {
    1: "Химические продукты",
    2: "Краски, лаки, покрытия",
    3: "Косметика, моющие средства",
    4: "Масла, топливо, смазки",
    5: "Фармацевтика, медицина",
    6: "Металлы, металлические изделия",
    7: "Машины, станки",
    8: "Ручные инструменты",
    9: "Электроника, IT-оборудование",
    10: "Медицинские приборы",
    11: "Освещение, отопление",
    12: "Транспортные средства",
    13: "Оружие, боеприпасы",
    14: "Ювелирные изделия, часы",
    15: "Музыкальные инструменты",
    16: "Бумага, канцтовары",
    17: "Каучук, пластмассы",
    18: "Кожа, сумки, зонты",
    19: "Строительные материалы",
    20: "Мебель",
    21: "Домашняя утварь",
    22: "Веревки, канаты, сети",
    23: "Нити для текстиля",
    24: "Ткани, текстиль",
    25: "Одежда, обувь",
    26: "Галантерея",
    27: "Ковры, покрытия",
    28: "Игры, спорттовары",
    29: "Продукты питания (мясо, рыба)",
    30: "Продукты питания (мука, кофе)",
    31: "Сельхозпродукция",
    32: "Напитки безалкогольные",
    33: "Алкоголь",
    34: "Табак",
    35: "Реклама, бизнес-услуги",
    36: "Финансы, страхование",
    37: "Строительство, ремонт",
    38: "Телекоммуникации",
    39: "Транспорт, логистика",
    40: "Обработка материалов",
    41: "Образование, развлечения",
    42: "Научные, IT-услуги",
    43: "Общепит, гостиницы",
    44: "Медицинские услуги",
    45: "Юридические услуги"
}

# Настройки приложения
APP_CONFIG = {
    "debug": True,
    "host": "0.0.0.0",
    "port": 5001,
    "max_file_size_mb": 50,
    "allowed_extensions": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"},
    "allowed_data_extensions": {".xlsx", ".xls", ".csv"},
    "tesseract_lang": "rus+eng",
    "similarity_threshold": 0.7,  # Порог схожести изображений
    "text_similarity_threshold": 0.8  # Порог схожести текста
}

# Типы источников изображений
IMAGE_SOURCES = {
    "internal_designer": {
        "name": "Штатный дизайнер",
        "risk_level": "low",
        "documents_required": ["Трудовой договор", "Должностная инструкция"]
    },
    "contractor": {
        "name": "Подрядчик",
        "risk_level": "medium",
        "documents_required": ["Договор отчуждения исключительных прав", "Акт приема-передачи"]
    },
    "ai_generated": {
        "name": "AI-генерация",
        "risk_level": "medium",
        "documents_required": ["Условия использования сервиса AI"]
    },
    "stock_free": {
        "name": "Бесплатные стоки",
        "risk_level": "medium",
        "documents_required": ["Лицензионное соглашение", "Скриншот лицензии"]
    },
    "stock_paid": {
        "name": "Платные стоки",
        "risk_level": "low",
        "documents_required": ["Лицензия", "Чек об оплате"]
    },
    "unknown": {
        "name": "Неизвестно / Поставщик не предоставил информацию",
        "risk_level": "high",
        "documents_required": ["Требуется выяснение источника"]
    }
}
