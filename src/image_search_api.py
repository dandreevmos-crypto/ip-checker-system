# -*- coding: utf-8 -*-
"""
Модуль автоматического поиска изображений в интернете
Поддерживает: SerpAPI (Google/Yandex), TinEye API, прямой поиск
"""

import os
import io
import base64
import hashlib
import urllib.parse
import json
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
import requests
from PIL import Image

from config import API_KEYS, IMAGE_SEARCH_RESOURCES
from models import ImageSearchResult, RiskLevel


class SerpAPIImageSearch:
    """
    Поиск изображений через SerpAPI (Google Reverse Image Search, Yandex Images)
    Бесплатно: 100 запросов/месяц
    https://serpapi.com/
    """

    BASE_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or API_KEYS.get("serpapi", os.environ.get("SERPAPI_KEY", ""))
        self.session = requests.Session()

    def search_google_reverse(self, image_path: str) -> ImageSearchResult:
        """Обратный поиск через Google Lens"""
        result = ImageSearchResult(
            resource_name="Google Images (SerpAPI)",
            resource_url="https://images.google.com"
        )

        if not self.api_key:
            result.notes = "SerpAPI ключ не настроен. Получите бесплатный ключ на serpapi.com"
            result.status = RiskLevel.YELLOW
            return result

        try:
            # Загружаем изображение и кодируем в base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            # Определяем MIME-тип
            ext = Path(image_path).suffix.lower()
            mime_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            mime_type = mime_types.get(ext, 'image/jpeg')

            # Формируем data URL
            image_url = f"data:{mime_type};base64,{image_data}"

            params = {
                "engine": "google_reverse_image",
                "image_url": image_url,
                "api_key": self.api_key
            }

            response = self.session.get(self.BASE_URL, params=params, timeout=60)

            if response.status_code == 200:
                data = response.json()
                self._parse_google_results(result, data)
            else:
                result.notes = f"Ошибка API: {response.status_code}"
                result.status = RiskLevel.YELLOW

        except Exception as e:
            result.notes = f"Ошибка поиска: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result

    def _parse_google_results(self, result: ImageSearchResult, data: Dict):
        """Парсинг результатов Google"""
        # Проверяем визуальные совпадения
        visual_matches = data.get("image_results", [])
        inline_images = data.get("inline_images", [])

        result.total_results = len(visual_matches) + len(inline_images)

        # Собираем похожие изображения
        for match in visual_matches[:10]:
            result.similar_images.append({
                "title": match.get("title", ""),
                "link": match.get("link", ""),
                "source": match.get("source", ""),
                "thumbnail": match.get("thumbnail", "")
            })

        # Проверяем точные совпадения
        if "image_sources" in data:
            result.exact_matches = len(data["image_sources"])
            for source in data["image_sources"][:5]:
                result.known_sources.append(source.get("source", ""))

        # Определяем статус
        if result.exact_matches > 0:
            result.status = RiskLevel.RED
            result.notes = f"Найдено {result.exact_matches} точных источников изображения!"
        elif result.total_results > 10:
            result.status = RiskLevel.YELLOW
            result.notes = f"Найдено {result.total_results} похожих изображений. Требуется проверка."
        elif result.total_results > 0:
            result.status = RiskLevel.YELLOW
            result.notes = f"Найдено {result.total_results} похожих изображений."
        else:
            result.status = RiskLevel.GREEN
            result.notes = "Похожих изображений не найдено."

    def search_yandex(self, image_path: str) -> ImageSearchResult:
        """Поиск через Яндекс.Картинки (SerpAPI)"""
        result = ImageSearchResult(
            resource_name="Яндекс.Картинки (SerpAPI)",
            resource_url="https://ya.ru/images"
        )

        if not self.api_key:
            result.notes = "SerpAPI ключ не настроен"
            result.status = RiskLevel.YELLOW
            return result

        try:
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            ext = Path(image_path).suffix.lower()
            mime_types = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
            mime_type = mime_types.get(ext, 'image/jpeg')
            image_url = f"data:{mime_type};base64,{image_data}"

            params = {
                "engine": "yandex_images",
                "url": image_url,
                "api_key": self.api_key
            }

            response = self.session.get(self.BASE_URL, params=params, timeout=60)

            if response.status_code == 200:
                data = response.json()
                self._parse_yandex_results(result, data)
            else:
                result.notes = f"Ошибка API: {response.status_code}"
                result.status = RiskLevel.YELLOW

        except Exception as e:
            result.notes = f"Ошибка: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result

    def _parse_yandex_results(self, result: ImageSearchResult, data: Dict):
        """Парсинг результатов Яндекса"""
        images = data.get("images_results", [])
        result.total_results = len(images)

        for img in images[:10]:
            result.similar_images.append({
                "title": img.get("title", ""),
                "link": img.get("link", ""),
                "source": img.get("source", ""),
                "thumbnail": img.get("thumbnail", "")
            })

        if result.total_results > 10:
            result.status = RiskLevel.YELLOW
            result.notes = f"Найдено {result.total_results} результатов в Яндексе"
        elif result.total_results > 0:
            result.status = RiskLevel.YELLOW
            result.notes = f"Найдено {result.total_results} результатов"
        else:
            result.status = RiskLevel.GREEN
            result.notes = "Совпадений не найдено"


class TinEyeAPISearch:
    """
    Поиск через TinEye API
    https://tineye.com/
    """

    API_URL = "https://api.tineye.com/rest/search/"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or API_KEYS.get("tineye", "")
        self.session = requests.Session()

    def search(self, image_path: str) -> ImageSearchResult:
        """Поиск изображения через TinEye"""
        result = ImageSearchResult(
            resource_name="TinEye",
            resource_url="https://tineye.com"
        )

        if not self.api_key:
            # Попробуем бесплатный веб-поиск
            return self._search_web(image_path)

        try:
            with open(image_path, 'rb') as f:
                files = {'image': f}
                headers = {'Authorization': f'Basic {self.api_key}'}

                response = self.session.post(
                    self.API_URL,
                    files=files,
                    headers=headers,
                    timeout=60
                )

                if response.status_code == 200:
                    data = response.json()
                    self._parse_results(result, data)
                else:
                    result.notes = f"Ошибка API: {response.status_code}"
                    result.status = RiskLevel.YELLOW

        except Exception as e:
            result.notes = f"Ошибка: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result

    def _search_web(self, image_path: str) -> ImageSearchResult:
        """Поиск через веб-интерфейс TinEye (без API)"""
        result = ImageSearchResult(
            resource_name="TinEye",
            resource_url="https://tineye.com"
        )

        try:
            with open(image_path, 'rb') as f:
                files = {'image': ('image.jpg', f, 'image/jpeg')}

                response = self.session.post(
                    'https://tineye.com/search',
                    files=files,
                    timeout=60,
                    allow_redirects=True
                )

                if response.status_code == 200:
                    # Парсим HTML для получения результатов
                    html = response.text

                    # Ищем количество результатов
                    import re
                    match = re.search(r'(\d+)\s+results?', html, re.IGNORECASE)
                    if match:
                        result.total_results = int(match.group(1))

                    if result.total_results > 0:
                        result.status = RiskLevel.YELLOW
                        result.notes = f"TinEye нашёл {result.total_results} совпадений. Проверьте источники."
                    else:
                        result.status = RiskLevel.GREEN
                        result.notes = "TinEye не нашёл совпадений"
                else:
                    result.notes = "Рекомендуется ручная проверка на tineye.com"
                    result.status = RiskLevel.YELLOW

        except Exception as e:
            result.notes = f"Не удалось проверить через TinEye: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result

    def _parse_results(self, result: ImageSearchResult, data: Dict):
        """Парсинг результатов TinEye API"""
        matches = data.get("matches", [])
        result.total_results = data.get("total_results", len(matches))

        for match in matches[:10]:
            result.similar_images.append({
                "link": match.get("backlinks", [{}])[0].get("url", ""),
                "source": match.get("domain", ""),
                "crawl_date": match.get("crawl_date", "")
            })

            # Добавляем источники
            for backlink in match.get("backlinks", []):
                if backlink.get("url"):
                    result.known_sources.append(backlink["url"])

        if result.total_results > 0:
            result.exact_matches = result.total_results
            result.status = RiskLevel.RED if result.total_results > 5 else RiskLevel.YELLOW
            result.notes = f"Найдено {result.total_results} точных совпадений изображения"
        else:
            result.status = RiskLevel.GREEN
            result.notes = "Совпадений не найдено"


class DirectImageSearch:
    """
    Прямой поиск через открытые API и веб-скрейпинг
    Работает без API ключей
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def generate_search_urls(self, image_path: str) -> Dict[str, str]:
        """Генерация URL для ручного поиска"""

        # Получаем хеш изображения для некоторых сервисов
        with open(image_path, 'rb') as f:
            img_hash = hashlib.md5(f.read()).hexdigest()

        return {
            "Яндекс.Картинки": "https://ya.ru/images",
            "Google Images": "https://images.google.com",
            "TinEye": "https://tineye.com",
            "Bing Visual Search": "https://www.bing.com/visualsearch",
            "Baidu": "https://image.baidu.com",
            "Pinterest": "https://pinterest.com"
        }

    def check_image_uniqueness(self, image_path: str) -> Dict[str, Any]:
        """
        Проверка уникальности изображения
        Возвращает оценку вероятности того, что изображение уникально
        """
        result = {
            "is_likely_unique": True,
            "confidence": 0.5,
            "checks_performed": [],
            "recommendations": []
        }

        try:
            # Проверяем метаданные изображения
            with Image.open(image_path) as img:
                exif = img._getexif() if hasattr(img, '_getexif') else None

                if exif:
                    result["checks_performed"].append("EXIF данные найдены")
                    # Если есть EXIF - вероятно оригинальное фото
                    result["confidence"] += 0.2
                else:
                    result["checks_performed"].append("EXIF данные отсутствуют")
                    result["recommendations"].append("Отсутствие EXIF может указывать на скачанное изображение")

                # Проверяем размер
                width, height = img.size
                if width >= 1920 or height >= 1080:
                    result["checks_performed"].append(f"Высокое разрешение: {width}x{height}")
                    result["confidence"] += 0.1
                else:
                    result["checks_performed"].append(f"Низкое разрешение: {width}x{height}")
                    result["recommendations"].append("Низкое разрешение может указывать на сжатое/скачанное изображение")

        except Exception as e:
            result["checks_performed"].append(f"Ошибка анализа: {str(e)}")

        result["is_likely_unique"] = result["confidence"] > 0.6

        return result


class ComprehensiveImageSearcher:
    """
    Комплексный поиск изображений по всем доступным источникам
    """

    def __init__(self, serpapi_key: str = None, tineye_key: str = None):
        self.serpapi = SerpAPIImageSearch(serpapi_key) if serpapi_key or API_KEYS.get("serpapi") else None
        self.tineye = TinEyeAPISearch(tineye_key)
        self.direct = DirectImageSearch()

    def search_all(self, image_path: str, use_api: bool = True) -> List[ImageSearchResult]:
        """
        Поиск по всем доступным источникам

        Args:
            image_path: Путь к изображению
            use_api: Использовать ли платные API

        Returns:
            Список результатов поиска
        """
        results = []

        # 1. SerpAPI (Google + Yandex)
        if use_api and self.serpapi and self.serpapi.api_key:
            try:
                google_result = self.serpapi.search_google_reverse(image_path)
                results.append(google_result)
            except Exception as e:
                results.append(ImageSearchResult(
                    resource_name="Google Images",
                    resource_url="https://images.google.com",
                    status=RiskLevel.YELLOW,
                    notes=f"Ошибка поиска: {str(e)}"
                ))

            try:
                yandex_result = self.serpapi.search_yandex(image_path)
                results.append(yandex_result)
            except Exception as e:
                results.append(ImageSearchResult(
                    resource_name="Яндекс.Картинки",
                    resource_url="https://ya.ru/images",
                    status=RiskLevel.YELLOW,
                    notes=f"Ошибка поиска: {str(e)}"
                ))

        # 2. TinEye
        try:
            tineye_result = self.tineye.search(image_path)
            results.append(tineye_result)
        except Exception as e:
            results.append(ImageSearchResult(
                resource_name="TinEye",
                resource_url="https://tineye.com",
                status=RiskLevel.YELLOW,
                notes=f"Ошибка: {str(e)}"
            ))

        # 3. Если API не настроены, добавляем результаты для ручной проверки
        if not results or all(r.status == RiskLevel.YELLOW and "не настроен" in r.notes for r in results):
            search_urls = self.direct.generate_search_urls(image_path)

            for name, url in search_urls.items():
                if not any(r.resource_name == name for r in results):
                    results.append(ImageSearchResult(
                        resource_name=name,
                        resource_url=url,
                        status=RiskLevel.YELLOW,
                        notes=f"Требуется ручная проверка. Перейдите на {url} и загрузите изображение."
                    ))

        # 4. Проверка уникальности
        uniqueness = self.direct.check_image_uniqueness(image_path)

        # Добавляем результат анализа уникальности
        uniqueness_result = ImageSearchResult(
            resource_name="Анализ метаданных",
            resource_url="",
            status=RiskLevel.GREEN if uniqueness["is_likely_unique"] else RiskLevel.YELLOW,
            notes="; ".join(uniqueness["checks_performed"])
        )
        results.append(uniqueness_result)

        return results

    def get_overall_status(self, results: List[ImageSearchResult]) -> Tuple[RiskLevel, str]:
        """
        Определение общего статуса на основе всех результатов поиска
        """
        # Если есть хоть один RED - общий статус RED
        red_results = [r for r in results if r.status == RiskLevel.RED]
        if red_results:
            notes = "; ".join([r.notes for r in red_results])
            return RiskLevel.RED, f"ВНИМАНИЕ! {notes}"

        # Если есть YELLOW - общий статус YELLOW
        yellow_results = [r for r in results if r.status == RiskLevel.YELLOW]
        if yellow_results:
            total_matches = sum(r.total_results for r in results if r.total_results > 0)
            if total_matches > 0:
                return RiskLevel.YELLOW, f"Найдено {total_matches} похожих изображений. Требуется проверка."
            else:
                return RiskLevel.YELLOW, "Требуется дополнительная проверка"

        return RiskLevel.GREEN, "Автоматическая проверка не выявила совпадений"


# Экспорт для использования в других модулях
__all__ = [
    'SerpAPIImageSearch',
    'TinEyeAPISearch',
    'DirectImageSearch',
    'ComprehensiveImageSearcher'
]


if __name__ == "__main__":
    # Тест
    searcher = ComprehensiveImageSearcher()
    print("Модуль поиска изображений готов к работе")
    print("\nДля автоматического поиска настройте API ключи:")
    print("  - SerpAPI: https://serpapi.com/ (100 бесплатных запросов/месяц)")
    print("  - TinEye: https://tineye.com/")
