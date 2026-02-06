# -*- coding: utf-8 -*-
"""
Модуль автоматического поиска изображений в интернете
Поддерживает: Serper.dev (рекомендуется), SerpAPI (Google/Yandex), TinEye API, прямой поиск

Рекомендуемый API: Serper.dev
- 2500 бесплатных запросов при регистрации
- $0.30 за 1000 запросов (в 10 раз дешевле SerpAPI)
- Поддержка Google Reverse Image Search
- https://serper.dev/
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


class SerperImageSearch:
    """
    Поиск изображений через Serper.dev API (РЕКОМЕНДУЕТСЯ)

    Преимущества:
    - 2500 бесплатных запросов при регистрации
    - $0.30 за 1000 запросов (в 10 раз дешевле SerpAPI)
    - Быстрый и надёжный API

    Регистрация: https://serper.dev/
    """

    API_URL = "https://google.serper.dev/images"
    LENS_URL = "https://google.serper.dev/lens"

    # Бесплатные сервисы для временной загрузки изображений
    IMGBB_API_URL = "https://api.imgbb.com/1/upload"
    IMGBB_API_KEY = "f09dbf205b2bdfc41aef51fce3ef8291"  # Бесплатный публичный ключ

    def __init__(self, api_key: str = None):
        self.api_key = api_key or API_KEYS.get("serper", os.environ.get("SERPER_API_KEY", ""))
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json"
            })

    def _upload_to_temp_hosting(self, image_path: str) -> Optional[str]:
        """
        Загружает изображение на временный хостинг и возвращает URL
        Пробует несколько сервисов по очереди
        """
        # Список сервисов для загрузки (в порядке приоритета)
        upload_services = [
            self._upload_to_imgbb,  # ImgBB - надёжный и бесплатный
            self._upload_to_freeimage,
            self._upload_to_0x0,
        ]

        for upload_func in upload_services:
            try:
                url = upload_func(image_path)
                if url:
                    return url
            except Exception as e:
                print(f"[Serper] Сервис загрузки не доступен: {e}")
                continue

        return None

    def _upload_to_imgbb(self, image_path: str) -> Optional[str]:
        """Загрузка на imgbb.com (надёжный бесплатный хостинг)"""
        try:
            import base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            response = requests.post(
                self.IMGBB_API_URL,
                data={
                    'key': self.IMGBB_API_KEY,
                    'image': image_data,
                    'expiration': 600  # Истекает через 10 минут
                },
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    url = result['data']['url']
                    print(f"[Serper] Загружено на imgbb: {url[:60]}...")
                    return url

            return None
        except Exception as e:
            print(f"[Serper] imgbb error: {e}")
            return None

    def _upload_to_freeimage(self, image_path: str) -> Optional[str]:
        """Загрузка на freeimage.host (бесплатно)"""
        try:
            with open(image_path, 'rb') as f:
                files = {'source': f}
                data = {'type': 'file', 'action': 'upload'}

                response = requests.post(
                    'https://freeimage.host/api/1/upload',
                    data={'key': '6d207e02198a847aa98d0a2a901485a5', **data},
                    files=files,
                    timeout=30
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get('status_code') == 200:
                        url = result['image']['url']
                        print(f"[Serper] Загружено на freeimage: {url[:60]}...")
                        return url

            return None
        except Exception as e:
            print(f"[Serper] freeimage error: {e}")
            return None

    def _upload_to_0x0(self, image_path: str) -> Optional[str]:
        """Загрузка на 0x0.st (минималистичный хостинг)"""
        try:
            with open(image_path, 'rb') as f:
                response = requests.post(
                    'https://0x0.st',
                    files={'file': f},
                    timeout=30
                )

                if response.status_code == 200:
                    url = response.text.strip()
                    if url.startswith('http'):
                        print(f"[Serper] Загружено на 0x0.st: {url}")
                        return url

            return None
        except Exception as e:
            print(f"[Serper] 0x0.st error: {e}")
            return None

    def search_by_image(self, image_path: str) -> ImageSearchResult:
        """
        Обратный поиск изображения через Google Lens (Serper)
        Использует временный хостинг изображений для загрузки
        """
        result = ImageSearchResult(
            resource_name="Google Images (Serper.dev)",
            resource_url="https://images.google.com"
        )

        if not self.api_key:
            result.notes = "Serper API ключ не настроен. Получите бесплатный ключ на https://serper.dev/"
            result.status = RiskLevel.YELLOW
            return result

        try:
            # Загружаем изображение на временный хостинг (imgbb.com - бесплатный)
            image_url = self._upload_to_temp_hosting(image_path)

            if not image_url:
                # Альтернатива: попробуем через поиск по тексту из OCR
                result.notes = "Не удалось загрузить изображение для поиска. Используйте ручную проверку."
                result.status = RiskLevel.YELLOW
                return result

            # Запрос к Serper Lens API
            payload = {
                "url": image_url,
                "gl": "ru",  # Регион - Россия
                "hl": "ru"   # Язык - русский
            }

            response = self.session.post(
                self.LENS_URL,
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                data = response.json()
                self._parse_lens_results(result, data)
            elif response.status_code == 401:
                result.notes = "Неверный API ключ Serper. Проверьте ключ на https://serper.dev/"
                result.status = RiskLevel.YELLOW
            elif response.status_code == 429:
                result.notes = "Превышен лимит запросов Serper API. Попробуйте позже."
                result.status = RiskLevel.YELLOW
            else:
                result.notes = f"Ошибка Serper API: {response.status_code} - {response.text[:200]}"
                result.status = RiskLevel.YELLOW

        except requests.exceptions.Timeout:
            result.notes = "Таймаут запроса к Serper API"
            result.status = RiskLevel.YELLOW
        except Exception as e:
            result.notes = f"Ошибка поиска: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result

    def _parse_lens_results(self, result: ImageSearchResult, data: Dict):
        """Парсинг результатов Google Lens через Serper"""

        print(f"[Serper] Получен ответ API, ключи: {list(data.keys())}")

        # Serper Lens API возвращает результаты в разных полях в зависимости от версии
        organic_results = data.get("organic", [])
        visual_matches = data.get("visual_matches", [])
        image_sources = data.get("image_sources", [])
        reverse_image_search = data.get("reverse_image_search", [])

        # Объединяем все источники результатов
        all_results = organic_results + visual_matches + image_sources + reverse_image_search

        # Точные совпадения изображения
        exact_matches = data.get("exact_matches", [])
        # Похожие изображения
        similar_images = data.get("similar_images", [])
        # Источники знаний (бренды, продукты)
        knowledge_graph = data.get("knowledgeGraph", {})

        print(f"[Serper] Найдено: organic={len(organic_results)}, visual={len(visual_matches)}, "
              f"image_sources={len(image_sources)}, reverse={len(reverse_image_search)}")

        result.total_results = len(all_results) + len(exact_matches) + len(similar_images)
        visual_matches = all_results  # Используем объединённые результаты
        result.exact_matches = len(exact_matches)

        # Собираем все найденные источники
        for match in exact_matches[:5]:
            source_url = match.get("link", match.get("url", ""))
            if source_url:
                result.known_sources.append(source_url)
            result.similar_images.append({
                "title": match.get("title", ""),
                "link": source_url,
                "source": match.get("source", match.get("domain", "")),
                "thumbnail": match.get("thumbnail", match.get("imageUrl", ""))
            })

        for match in visual_matches[:10]:
            result.similar_images.append({
                "title": match.get("title", ""),
                "link": match.get("link", ""),
                "source": match.get("source", ""),
                "thumbnail": match.get("thumbnail", match.get("thumbnailUrl", match.get("imageUrl", ""))),
                "position": match.get("position", 0)
            })

        # Проверяем Knowledge Graph и organic результаты на известные бренды
        detected_brands = []

        # Список известных брендов для проверки
        brand_keywords = [
            'nike', 'adidas', 'puma', 'gucci', 'chanel', 'louis vuitton',
            'supreme', 'versace', 'prada', 'dior', 'balenciaga', 'hermes',
            'burberry', 'fendi', 'off-white', 'givenchy', 'valentino',
            'armani', 'dolce', 'gabbana', 'yves saint laurent', 'cartier',
            'rolex', 'omega', 'tissot', 'lacoste', 'tommy hilfiger', 'calvin klein',
            'ralph lauren', 'hugo boss', 'michael kors', 'coach', 'kate spade'
        ]

        # Проверяем Knowledge Graph
        if knowledge_graph:
            title = knowledge_graph.get("title", "").lower()
            description = knowledge_graph.get("description", "").lower()
            for brand in brand_keywords:
                if brand in title or brand in description:
                    detected_brands.append(brand.upper())

        # Проверяем organic результаты на упоминание брендов
        all_text = ""
        for match in visual_matches[:20]:
            all_text += " " + match.get("title", "").lower()
            all_text += " " + match.get("source", "").lower()

        for brand in brand_keywords:
            if brand in all_text and brand.upper() not in detected_brands:
                # Считаем сколько раз упоминается бренд
                count = all_text.count(brand)
                if count >= 2:  # Если упоминается минимум 2 раза - это вероятно бренд
                    detected_brands.append(brand.upper())

        # Определяем статус
        # КРАСНЫЙ: бренды, много совпадений (>5), или точные совпадения
        # ЖЁЛТЫЙ: мало совпадений (1-5)
        # ЗЕЛЁНЫЙ: нет совпадений

        if detected_brands:
            result.status = RiskLevel.RED
            result.notes = f"⚠️ Обнаружены известные бренды: {', '.join(detected_brands)}"
            if len(visual_matches) > 0:
                result.notes += f" Найдено {len(visual_matches)} похожих товаров."
        elif result.exact_matches > 0:
            result.status = RiskLevel.RED
            result.notes = f"⚠️ ВНИМАНИЕ! Найдено {result.exact_matches} точных совпадений изображения в интернете!"
        elif len(visual_matches) > 5:
            # Много похожих изображений = высокий риск (изображение уже используется)
            result.status = RiskLevel.RED
            result.notes = f"⚠️ ВНИМАНИЕ! Найдено {len(visual_matches)} похожих изображений в интернете. Изображение не уникально!"
        elif len(visual_matches) > 0:
            # Мало совпадений - требуется проверка
            result.status = RiskLevel.YELLOW
            result.notes = f"Найдено {len(visual_matches)} похожих изображений. Проверьте источники."
        else:
            result.status = RiskLevel.GREEN
            result.notes = "Похожих изображений не найдено в Google."

        # Добавляем информацию о knowledge graph
        if knowledge_graph.get("title"):
            result.notes += f" [Распознано: {knowledge_graph.get('title')}]"

    def search_by_text(self, query: str, num_results: int = 10) -> ImageSearchResult:
        """
        Поиск изображений по текстовому запросу
        """
        result = ImageSearchResult(
            resource_name="Google Images (text search)",
            resource_url=f"https://images.google.com/search?q={urllib.parse.quote(query)}"
        )

        if not self.api_key:
            result.notes = "Serper API ключ не настроен"
            result.status = RiskLevel.YELLOW
            return result

        try:
            payload = {
                "q": query,
                "gl": "ru",
                "hl": "ru",
                "num": num_results
            }

            response = self.session.post(
                self.API_URL,
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                images = data.get("images", [])
                result.total_results = len(images)

                for img in images[:10]:
                    result.similar_images.append({
                        "title": img.get("title", ""),
                        "link": img.get("link", ""),
                        "source": img.get("source", ""),
                        "thumbnail": img.get("imageUrl", "")
                    })

                result.status = RiskLevel.GREEN
                result.notes = f"Найдено {result.total_results} изображений по запросу '{query}'"
            else:
                result.notes = f"Ошибка API: {response.status_code}"
                result.status = RiskLevel.YELLOW

        except Exception as e:
            result.notes = f"Ошибка: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result


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

    Порядок приоритета API:
    1. Serper.dev (рекомендуется) - 2500 бесплатных, $0.30/1000
    2. SerpAPI - 100 бесплатных/месяц, дороже
    3. TinEye - для точных совпадений
    4. Ручная проверка - если API не настроены
    """

    def __init__(self, serper_key: str = None, serpapi_key: str = None, tineye_key: str = None):
        # Serper.dev - приоритетный API
        self.serper = SerperImageSearch(serper_key) if serper_key or API_KEYS.get("serper") or os.environ.get("SERPER_API_KEY") else None

        # SerpAPI - резервный
        self.serpapi = SerpAPIImageSearch(serpapi_key) if serpapi_key or API_KEYS.get("serpapi") else None

        # TinEye
        self.tineye = TinEyeAPISearch(tineye_key)

        # Прямой поиск (без API)
        self.direct = DirectImageSearch()

        # Логируем доступные API
        available = []
        if self.serper and self.serper.api_key:
            available.append("Serper.dev")
        if self.serpapi and self.serpapi.api_key:
            available.append("SerpAPI")
        if self.tineye.api_key:
            available.append("TinEye API")

        if available:
            print(f"[OK] Доступные API поиска изображений: {', '.join(available)}")
        else:
            print("[!] API поиска изображений не настроены. Используется ручной режим.")
            print("    Рекомендуется: Serper.dev - https://serper.dev/ (2500 бесплатных запросов)")

    def search_all(self, image_path: str, use_api: bool = True) -> List[ImageSearchResult]:
        """
        Поиск по всем доступным источникам

        Args:
            image_path: Путь к изображению
            use_api: Использовать ли API (рекомендуется True)

        Returns:
            Список результатов поиска
        """
        results = []
        api_used = False

        # 1. ПРИОРИТЕТ: Serper.dev (Google Lens) - лучшее соотношение цена/качество
        if use_api and self.serper and self.serper.api_key:
            try:
                serper_result = self.serper.search_by_image(image_path)
                results.append(serper_result)
                api_used = True
                print(f"[Serper] Поиск выполнен: {serper_result.total_results} результатов")
            except Exception as e:
                print(f"[Serper] Ошибка: {e}")
                results.append(ImageSearchResult(
                    resource_name="Google Images (Serper.dev)",
                    resource_url="https://images.google.com",
                    status=RiskLevel.YELLOW,
                    notes=f"Ошибка Serper API: {str(e)}"
                ))

        # 2. SerpAPI (резервный вариант, если Serper не настроен)
        elif use_api and self.serpapi and self.serpapi.api_key:
            try:
                google_result = self.serpapi.search_google_reverse(image_path)
                results.append(google_result)
                api_used = True
            except Exception as e:
                results.append(ImageSearchResult(
                    resource_name="Google Images (SerpAPI)",
                    resource_url="https://images.google.com",
                    status=RiskLevel.YELLOW,
                    notes=f"Ошибка SerpAPI: {str(e)}"
                ))

            try:
                yandex_result = self.serpapi.search_yandex(image_path)
                results.append(yandex_result)
            except Exception as e:
                results.append(ImageSearchResult(
                    resource_name="Яндекс.Картинки (SerpAPI)",
                    resource_url="https://ya.ru/images",
                    status=RiskLevel.YELLOW,
                    notes=f"Ошибка: {str(e)}"
                ))

        # 3. Если API не использовались - добавляем ссылки для ручной проверки
        if not api_used:
            search_urls = self.direct.generate_search_urls(image_path)

            # Добавляем информацию о необходимости настройки API
            setup_info = ImageSearchResult(
                resource_name="⚙️ Настройка автопоиска",
                resource_url="https://serper.dev/",
                status=RiskLevel.YELLOW,
                notes="Для автоматического поиска настройте Serper API (2500 бесплатных запросов). "
                      "Добавьте SERPER_API_KEY в переменные окружения или config.py"
            )
            results.insert(0, setup_info)

            for name, url in search_urls.items():
                if not any(name in r.resource_name for r in results):
                    results.append(ImageSearchResult(
                        resource_name=name,
                        resource_url=url,
                        status=RiskLevel.YELLOW,
                        notes=f"Требуется ручная проверка. Перейдите на {url} и загрузите изображение."
                    ))

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
    'SerperImageSearch',
    'SerpAPIImageSearch',
    'TinEyeAPISearch',
    'DirectImageSearch',
    'ComprehensiveImageSearcher'
]


if __name__ == "__main__":
    # Тест
    print("=" * 60)
    print("  Модуль поиска изображений IP Checker")
    print("=" * 60)

    searcher = ComprehensiveImageSearcher()

    print("\n📋 Для автоматического поиска настройте API ключи:\n")
    print("  🌟 РЕКОМЕНДУЕТСЯ: Serper.dev")
    print("     URL: https://serper.dev/")
    print("     Бесплатно: 2500 запросов")
    print("     Цена: $0.30 за 1000 запросов")
    print("     Переменная: SERPER_API_KEY")
    print()
    print("  📌 Альтернатива: SerpAPI")
    print("     URL: https://serpapi.com/")
    print("     Бесплатно: 100 запросов/месяц")
    print("     Цена: $75 за 5000 запросов")
    print("     Переменная: SERPAPI_KEY")
    print()
    print("  🔍 TinEye (для точных совпадений)")
    print("     URL: https://tineye.com/")
    print("     Переменная: TINEYE_API_KEY")
    print()
    print("Для настройки добавьте ключи в переменные окружения или config.py")
