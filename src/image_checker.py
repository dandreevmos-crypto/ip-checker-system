# -*- coding: utf-8 -*-
"""
Модуль проверки изображений:
- Обратный поиск изображений
- Распознавание текста (OCR)
- Анализ содержимого изображений
"""

import os
import io
import ssl
import base64
import hashlib
import urllib.parse
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
import requests
from PIL import Image

# Исправление SSL для скачивания моделей EasyOCR
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
    # Создаем контекст SSL без верификации как fallback
    ssl._create_default_https_context = ssl._create_unverified_context
except:
    pass

# Проверка imagehash
try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    IMAGEHASH_AVAILABLE = False

# Проверка Tesseract
TESSERACT_AVAILABLE = False
TESSERACT_CMD = None
try:
    import pytesseract
    # Проверяем, что tesseract установлен в системе
    result = subprocess.run(['which', 'tesseract'], capture_output=True, text=True)
    if result.returncode == 0:
        TESSERACT_CMD = result.stdout.strip()
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
        TESSERACT_AVAILABLE = True
        print(f"[OK] Tesseract найден: {TESSERACT_CMD}")
except ImportError:
    print("[!] pytesseract не установлен")
except Exception as e:
    print(f"[!] Ошибка инициализации Tesseract: {e}")

# Проверка EasyOCR
EASYOCR_AVAILABLE = False
try:
    import easyocr
    EASYOCR_AVAILABLE = True
    print("[OK] EasyOCR доступен")
except ImportError:
    print("[!] EasyOCR не установлен")

from config import IMAGE_SEARCH_RESOURCES, COPYRIGHT_RESOURCES, APP_CONFIG
from models import ImageSearchResult, TextOnImage, CopyrightCheckResult, RiskLevel

# Импорт нового модуля поиска изображений
try:
    from image_search_api import ComprehensiveImageSearcher
    IMAGE_SEARCH_API_AVAILABLE = True
    print("[OK] Модуль поиска изображений загружен")
except ImportError:
    IMAGE_SEARCH_API_AVAILABLE = False
    print("[!] Модуль image_search_api не найден")


class ImageProcessor:
    """Обработка и подготовка изображений"""

    @staticmethod
    def load_image(image_path: str) -> Image.Image:
        """Загрузка изображения"""
        return Image.open(image_path)

    @staticmethod
    def resize_for_search(image: Image.Image, max_size: int = 1024) -> Image.Image:
        """Изменение размера для поиска"""
        if max(image.size) > max_size:
            ratio = max_size / max(image.size)
            new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
            return image.resize(new_size, Image.Resampling.LANCZOS)
        return image

    @staticmethod
    def to_base64(image: Image.Image, format: str = "PNG") -> str:
        """Конвертация в base64"""
        buffer = io.BytesIO()
        image.save(buffer, format=format)
        return base64.b64encode(buffer.getvalue()).decode()

    @staticmethod
    def get_image_hash(image_path: str) -> str:
        """Получение перцептивного хеша изображения"""
        if not IMAGEHASH_AVAILABLE:
            return ""
        img = Image.open(image_path)
        return str(imagehash.phash(img))

    @staticmethod
    def compare_images(hash1: str, hash2: str) -> float:
        """Сравнение двух изображений по хешам (0-1, где 1 = идентичны)"""
        if not IMAGEHASH_AVAILABLE or not hash1 or not hash2:
            return 0.0
        h1 = imagehash.hex_to_hash(hash1)
        h2 = imagehash.hex_to_hash(hash2)
        # Максимальное различие для phash = 64 бита
        difference = h1 - h2
        similarity = 1 - (difference / 64)
        return max(0, similarity)


class OCRProcessor:
    """Распознавание текста на изображениях"""

    _easyocr_reader = None  # Кэш для EasyOCR reader (долго инициализируется)

    def __init__(self, languages: List[str] = None):
        self.languages = languages or ['ru', 'en']
        self.reader = None
        self.ocr_method = None

        # Пробуем инициализировать OCR движки
        if EASYOCR_AVAILABLE:
            try:
                # Используем кэшированный reader если есть
                if OCRProcessor._easyocr_reader is None:
                    print("Инициализация EasyOCR (первый запуск может занять время)...")
                    OCRProcessor._easyocr_reader = easyocr.Reader(self.languages, gpu=False, verbose=False)
                self.reader = OCRProcessor._easyocr_reader
                self.ocr_method = "easyocr"
                print(f"[OK] OCR инициализирован: EasyOCR")
            except Exception as e:
                print(f"Ошибка инициализации EasyOCR: {e}")

        if self.reader is None and TESSERACT_AVAILABLE:
            self.ocr_method = "tesseract"
            print(f"[OK] OCR инициализирован: Tesseract")

        if self.ocr_method is None:
            print("[!] ВНИМАНИЕ: OCR не доступен! Установите easyocr или tesseract.")

    def extract_text_easyocr(self, image_path: str) -> List[TextOnImage]:
        """Извлечение текста с помощью EasyOCR"""
        if not self.reader:
            return []

        results = []
        found_texts = set()

        try:
            # Пробуем на оригинале и предобработанных вариантах
            variants = self._preprocess_image(image_path)

            for img_variant in variants[:4]:  # Максимум 4 варианта
                try:
                    # EasyOCR может принимать PIL Image или путь
                    import numpy as np
                    img_array = np.array(img_variant)
                    detections = self.reader.readtext(img_array)

                    for detection in detections:
                        bbox, text, confidence = detection
                        text_clean = text.strip()
                        text_lower = text_clean.lower()

                        # Дедупликация
                        if text_lower in found_texts:
                            continue

                        if confidence > 0.15 and len(text_clean) > 1:  # Снижен порог
                            found_texts.add(text_lower)
                            # bbox = [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                            x1, y1 = bbox[0]
                            x2, y2 = bbox[2]

                            results.append(TextOnImage(
                                text=text_clean,
                                confidence=confidence,
                                position={
                                    "x": int(x1),
                                    "y": int(y1),
                                    "width": int(x2 - x1),
                                    "height": int(y2 - y1)
                                },
                                language=self._detect_language(text_clean)
                            ))
                except Exception as e:
                    print(f"Ошибка EasyOCR для варианта: {e}")
                    continue

        except Exception as e:
            print(f"Ошибка EasyOCR: {e}")

        # Сортируем по уверенности
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results

    def _preprocess_image(self, image_path: str) -> List[Image.Image]:
        """
        Предобработка изображения для улучшения OCR
        Возвращает список вариантов изображения для распознавания
        """
        img = Image.open(image_path)
        variants = [img]  # Оригинал

        try:
            # Конвертируем в RGB если нужно
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Вариант 1: Оттенки серого
            gray = img.convert('L')
            variants.append(gray)

            # Вариант 2: Увеличение контраста
            from PIL import ImageEnhance, ImageFilter
            enhancer = ImageEnhance.Contrast(img)
            high_contrast = enhancer.enhance(2.0)
            variants.append(high_contrast)

            # Вариант 3: Инверсия (для светлого текста на тёмном фоне)
            from PIL import ImageOps
            inverted = ImageOps.invert(img.convert('RGB'))
            variants.append(inverted)

            # Вариант 4: Бинаризация серого
            threshold = 128
            binary = gray.point(lambda x: 255 if x > threshold else 0, '1')
            variants.append(binary.convert('L'))

            # Вариант 5: Резкость
            sharp = img.filter(ImageFilter.SHARPEN)
            variants.append(sharp)

            # Вариант 6: Увеличение размера (для мелкого текста)
            width, height = img.size
            if width < 1000:
                scale = 2
                resized = img.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
                variants.append(resized)

        except Exception as e:
            print(f"Ошибка предобработки изображения: {e}")

        return variants

    def extract_text_tesseract(self, image_path: str) -> List[TextOnImage]:
        """Извлечение текста с помощью Tesseract с предобработкой"""
        if not TESSERACT_AVAILABLE:
            return []

        results = []
        found_texts = set()  # Для дедупликации

        try:
            # Получаем варианты изображения
            variants = self._preprocess_image(image_path)

            for idx, img in enumerate(variants):
                try:
                    # Пробуем разные конфигурации Tesseract
                    configs = [
                        '--oem 3 --psm 6',   # Assume uniform block of text
                        '--oem 3 --psm 11',  # Sparse text
                        '--oem 3 --psm 3',   # Fully automatic
                    ]

                    for config in configs:
                        data = pytesseract.image_to_data(
                            img,
                            lang=APP_CONFIG.get("tesseract_lang", "rus+eng"),
                            output_type=pytesseract.Output.DICT,
                            config=config
                        )

                        for i in range(len(data['text'])):
                            text = data['text'][i].strip()
                            conf = float(data['conf'][i])

                            # Фильтр: текст > 2 символов, уверенность > 20%
                            if text and len(text) > 2 and conf > 20:
                                # Дедупликация
                                text_lower = text.lower()
                                if text_lower not in found_texts:
                                    found_texts.add(text_lower)
                                    results.append(TextOnImage(
                                        text=text,
                                        confidence=conf / 100,
                                        position={
                                            "x": data['left'][i],
                                            "y": data['top'][i],
                                            "width": data['width'][i],
                                            "height": data['height'][i]
                                        },
                                        language=self._detect_language(text)
                                    ))

                except Exception as e:
                    print(f"Ошибка Tesseract для варианта {idx}: {e}")
                    continue

        except Exception as e:
            print(f"Ошибка Tesseract: {e}")

        # Сортируем по уверенности
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results

    def extract_text_tesseract_old(self, image_path: str) -> List[TextOnImage]:
        """Старый метод извлечения текста с помощью Tesseract"""
        if not TESSERACT_AVAILABLE:
            return []

        results = []
        try:
            img = Image.open(image_path)
            # Получаем данные с координатами
            data = pytesseract.image_to_data(
                img,
                lang=APP_CONFIG.get("tesseract_lang", "rus+eng"),
                output_type=pytesseract.Output.DICT
            )

            for i in range(len(data['text'])):
                text = data['text'][i].strip()
                conf = float(data['conf'][i])

                if text and conf > 30:  # Фильтр по уверенности
                    results.append(TextOnImage(
                        text=text,
                        confidence=conf / 100,
                        position={
                            "x": data['left'][i],
                            "y": data['top'][i],
                            "width": data['width'][i],
                            "height": data['height'][i]
                        },
                        language=self._detect_language(text)
                    ))

        except Exception as e:
            print(f"Ошибка Tesseract: {e}")

        return results

    def extract_text(self, image_path: str) -> List[TextOnImage]:
        """Извлечение текста (использует доступный OCR движок)"""
        # Пробуем EasyOCR (обычно лучше для разных шрифтов)
        results = self.extract_text_easyocr(image_path)

        # Если EasyOCR не работает, пробуем Tesseract
        if not results:
            results = self.extract_text_tesseract(image_path)

        # Объединяем близко расположенный текст
        return self._merge_nearby_text(results)

    def _detect_language(self, text: str) -> str:
        """Определение языка текста"""
        cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
        latin = sum(1 for c in text if 'A' <= c.upper() <= 'Z')

        if cyrillic > latin:
            return "ru"
        elif latin > 0:
            return "en"
        return "unknown"

    def _merge_nearby_text(self, texts: List[TextOnImage],
                           distance_threshold: int = 20) -> List[TextOnImage]:
        """Объединение близко расположенного текста"""
        if len(texts) <= 1:
            return texts

        # Сортируем по позиции (сверху вниз, слева направо)
        texts = sorted(texts, key=lambda t: (t.position.get('y', 0), t.position.get('x', 0)))

        merged = []
        current = None

        for text in texts:
            if current is None:
                current = text
            else:
                # Проверяем, находятся ли тексты на одной линии
                y_diff = abs(text.position.get('y', 0) - current.position.get('y', 0))
                x_gap = text.position.get('x', 0) - (
                    current.position.get('x', 0) + current.position.get('width', 0)
                )

                if y_diff < distance_threshold and x_gap < distance_threshold * 3:
                    # Объединяем
                    current = TextOnImage(
                        text=f"{current.text} {text.text}",
                        confidence=min(current.confidence, text.confidence),
                        position={
                            "x": current.position.get('x', 0),
                            "y": min(current.position.get('y', 0), text.position.get('y', 0)),
                            "width": (text.position.get('x', 0) + text.position.get('width', 0) -
                                      current.position.get('x', 0)),
                            "height": max(current.position.get('height', 0),
                                          text.position.get('height', 0))
                        },
                        language=current.language
                    )
                else:
                    merged.append(current)
                    current = text

        if current:
            merged.append(current)

        return merged


class ReverseImageSearcher:
    """Обратный поиск изображений с поддержкой API"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

        # Инициализируем API поиск если доступен
        self.api_searcher = None
        if IMAGE_SEARCH_API_AVAILABLE:
            try:
                self.api_searcher = ComprehensiveImageSearcher()
                print("[OK] API поиска изображений инициализирован")
            except Exception as e:
                print(f"[!] Ошибка инициализации API поиска: {e}")

    def search_all(self, image_path: str) -> List[ImageSearchResult]:
        """
        Поиск по всем доступным источникам
        Использует API если настроен, иначе генерирует ссылки для ручной проверки
        """
        results = []

        # Если API доступен - используем его
        if self.api_searcher:
            try:
                api_results = self.api_searcher.search_all(image_path, use_api=True)
                results.extend(api_results)
            except Exception as e:
                print(f"Ошибка API поиска: {e}")

        # Если API не дал результатов или недоступен - добавляем ручные проверки
        if not results:
            results.append(self.search_yandex(image_path))
            results.append(self.search_google(image_path))
            results.append(self.search_tineye(image_path))

        return results

    def search_yandex(self, image_path: str) -> ImageSearchResult:
        """Поиск через Яндекс.Картинки"""
        result = ImageSearchResult(
            resource_name="Яндекс.Картинки",
            resource_url="https://ya.ru/images"
        )

        # Если есть API - используем его
        if self.api_searcher and hasattr(self.api_searcher, 'serpapi') and self.api_searcher.serpapi:
            try:
                return self.api_searcher.serpapi.search_yandex(image_path)
            except Exception as e:
                print(f"Ошибка Yandex API: {e}")

        # Иначе - инструкции для ручной проверки
        result.notes = self._get_yandex_search_instructions(image_path)
        result.status = RiskLevel.YELLOW
        return result

    def _get_yandex_search_instructions(self, image_path: str) -> str:
        """Инструкции для ручного поиска в Яндексе"""
        return (
            "Для проверки перейдите на https://ya.ru/images, "
            "нажмите на иконку камеры и загрузите изображение для поиска."
        )

    def search_google(self, image_path: str) -> ImageSearchResult:
        """Поиск через Google Images"""
        result = ImageSearchResult(
            resource_name="Google Images",
            resource_url="https://images.google.com"
        )

        # Если есть API - используем его
        if self.api_searcher and hasattr(self.api_searcher, 'serpapi') and self.api_searcher.serpapi:
            try:
                return self.api_searcher.serpapi.search_google_reverse(image_path)
            except Exception as e:
                print(f"Ошибка Google API: {e}")

        result.notes = self._get_google_search_instructions(image_path)
        result.status = RiskLevel.YELLOW
        return result

    def _get_google_search_instructions(self, image_path: str) -> str:
        """Инструкции для ручного поиска в Google"""
        return (
            "Для проверки перейдите на https://images.google.com, "
            "нажмите на иконку камеры и загрузите изображение для поиска."
        )

    def search_tineye(self, image_path: str) -> ImageSearchResult:
        """Поиск через TinEye"""
        result = ImageSearchResult(
            resource_name="TinEye",
            resource_url="https://tineye.com"
        )

        try:
            # TinEye имеет API, но требует ключ
            # Попробуем веб-интерфейс
            with open(image_path, 'rb') as f:
                files = {'image': f}
                response = self.session.post(
                    'https://tineye.com/search',
                    files=files,
                    timeout=60
                )

                if response.status_code == 200:
                    # Парсим результаты
                    self._parse_tineye_results(result, response.text)
                else:
                    result.notes = "Рекомендуется ручная проверка на https://tineye.com"
                    result.status = RiskLevel.YELLOW

        except Exception as e:
            result.notes = f"Требуется ручная проверка на TinEye: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result

    def _parse_tineye_results(self, result: ImageSearchResult, html: str):
        """Парсинг результатов TinEye"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        # Ищем количество результатов
        results_text = soup.find(class_='search-summary')
        if results_text:
            import re
            numbers = re.findall(r'\d+', results_text.get_text())
            if numbers:
                result.total_results = int(numbers[0])

        if result.total_results > 0:
            result.status = RiskLevel.YELLOW
            result.notes = f"Найдено {result.total_results} совпадений. Требуется проверка источников."
        else:
            result.status = RiskLevel.GREEN
            result.notes = "Совпадений не найдено"

    def search_all(self, image_path: str) -> List[ImageSearchResult]:
        """Поиск по всем доступным сервисам"""
        results = []

        # Поиск в каждом сервисе
        results.append(self.search_yandex(image_path))
        results.append(self.search_google(image_path))
        results.append(self.search_tineye(image_path))

        return results

    def generate_search_links(self, image_path: str) -> Dict[str, str]:
        """Генерация ссылок для ручного поиска"""
        links = {
            "Яндекс.Картинки": "https://ya.ru/images",
            "Google Images": "https://images.google.com",
            "TinEye": "https://tineye.com",
            "Bing Visual Search": "https://www.bing.com/visualsearch",
            "Pinterest": "https://pinterest.com"
        }

        # Дополнительные ресурсы для проверки авторских прав
        links.update({
            "Behance": "https://www.behance.net/search",
            "Illustrators.ru": "https://illustrators.ru/search",
            "Dribbble": "https://dribbble.com/search"
        })

        return links


class CopyrightAnalyzer:
    """Анализ изображения на предмет авторских прав"""

    # Известные бренды и персонажи для проверки
    KNOWN_BRANDS = [
        "Nike", "Adidas", "Apple", "Samsung", "Google", "Microsoft",
        "Disney", "Marvel", "DC Comics", "Warner Bros", "Sony",
        "Coca-Cola", "Pepsi", "McDonald's", "Starbucks", "Amazon",
        "Louis Vuitton", "Gucci", "Chanel", "Prada", "Hermès",
        "Ferrari", "Lamborghini", "BMW", "Mercedes", "Audi"
    ]

    KNOWN_CHARACTERS = [
        "Mickey Mouse", "Микки Маус", "Minnie Mouse", "Donald Duck",
        "Spider-Man", "Человек-Паук", "Batman", "Бэтмен", "Superman",
        "Iron Man", "Hulk", "Thor", "Captain America",
        "Hello Kitty", "Pikachu", "Покемон", "Pokemon",
        "Shrek", "Frozen", "Elsa", "Эльза", "Minions", "Миньоны",
        "Peppa Pig", "Свинка Пеппа", "Маша и Медведь", "Фиксики",
        "Смешарики", "Лунтик", "Три кота"
    ]

    def __init__(self):
        self.ocr = OCRProcessor()

    def analyze_image(self, image_path: str,
                       recognized_texts: List[TextOnImage] = None) -> CopyrightCheckResult:
        """Полный анализ изображения на предмет авторских прав"""
        result = CopyrightCheckResult()

        # Если текст не распознан, делаем OCR
        if recognized_texts is None:
            recognized_texts = self.ocr.extract_text(image_path)

        # Собираем весь текст
        all_text = " ".join([t.text for t in recognized_texts])

        # Проверяем на известные бренды
        found_brands = self._check_known_items(all_text, self.KNOWN_BRANDS)
        if found_brands:
            result.brand_elements = found_brands
            result.status = RiskLevel.RED
            result.notes = f"Обнаружены известные бренды: {', '.join(found_brands)}"

        # Проверяем на известных персонажей
        found_characters = self._check_known_items(all_text, self.KNOWN_CHARACTERS)
        if found_characters:
            result.contains_characters = True
            result.character_names = found_characters
            result.status = RiskLevel.RED
            if result.notes:
                result.notes += f"; Обнаружены известные персонажи: {', '.join(found_characters)}"
            else:
                result.notes = f"Обнаружены известные персонажи: {', '.join(found_characters)}"

        # Если ничего критичного не найдено
        if result.status != RiskLevel.RED:
            if recognized_texts:
                result.status = RiskLevel.YELLOW
                result.notes = "На изображении обнаружен текст, рекомендуется проверка"
            else:
                result.status = RiskLevel.GREEN
                result.notes = "Автоматическая проверка не выявила проблем"

        return result

    def _check_known_items(self, text: str, items: List[str]) -> List[str]:
        """Проверка текста на наличие известных элементов"""
        found = []
        text_lower = text.lower()

        for item in items:
            if item.lower() in text_lower:
                found.append(item)

        return found


class ComprehensiveImageChecker:
    """Комплексная проверка изображений"""

    def __init__(self):
        self.processor = ImageProcessor()
        self.ocr = OCRProcessor()
        self.searcher = ReverseImageSearcher()
        self.copyright_analyzer = CopyrightAnalyzer()

    def check_image(self, image_path: str) -> Dict[str, Any]:
        """
        Полная проверка изображения

        Returns:
            {
                "recognized_texts": List[TextOnImage],
                "search_results": List[ImageSearchResult],
                "copyright_result": CopyrightCheckResult,
                "overall_status": RiskLevel,
                "recommendations": List[str],
                "manual_check_links": Dict[str, str]
            }
        """
        results = {
            "recognized_texts": [],
            "search_results": [],
            "copyright_result": None,
            "overall_status": RiskLevel.GREEN,
            "recommendations": [],
            "manual_check_links": {}
        }

        # 1. Распознавание текста
        try:
            results["recognized_texts"] = self.ocr.extract_text(image_path)
        except Exception as e:
            results["recommendations"].append(f"Ошибка OCR: {str(e)}")

        # 2. Обратный поиск изображений
        try:
            results["search_results"] = self.searcher.search_all(image_path)
        except Exception as e:
            results["recommendations"].append(f"Ошибка поиска изображений: {str(e)}")

        # 3. Анализ на авторские права
        try:
            results["copyright_result"] = self.copyright_analyzer.analyze_image(
                image_path, results["recognized_texts"]
            )
        except Exception as e:
            results["recommendations"].append(f"Ошибка анализа: {str(e)}")

        # 4. Определение общего статуса
        results["overall_status"] = self._determine_overall_status(results)

        # 5. Генерация ссылок для ручной проверки
        results["manual_check_links"] = self.searcher.generate_search_links(image_path)

        # 6. Формирование рекомендаций
        results["recommendations"].extend(self._generate_recommendations(results))

        return results

    def _determine_overall_status(self, results: Dict) -> RiskLevel:
        """Определение общего статуса"""
        # Проверяем результаты на наличие красных флагов
        if results.get("copyright_result") and results["copyright_result"].status == RiskLevel.RED:
            return RiskLevel.RED

        # Проверяем результаты поиска изображений
        for search_result in results.get("search_results", []):
            if search_result.status == RiskLevel.RED:
                return RiskLevel.RED

        # Если есть желтые статусы
        if results.get("copyright_result") and results["copyright_result"].status == RiskLevel.YELLOW:
            return RiskLevel.YELLOW

        for search_result in results.get("search_results", []):
            if search_result.status == RiskLevel.YELLOW:
                return RiskLevel.YELLOW

        # Если есть распознанный текст - желтый статус
        if results.get("recognized_texts"):
            return RiskLevel.YELLOW

        return RiskLevel.GREEN

    def _generate_recommendations(self, results: Dict) -> List[str]:
        """Генерация рекомендаций"""
        recommendations = []

        if results["overall_status"] == RiskLevel.RED:
            recommendations.append(
                "ВНИМАНИЕ: Обнаружены потенциальные нарушения авторских прав или "
                "использование защищенных брендов/персонажей. "
                "Использование данного изображения НЕ РЕКОМЕНДУЕТСЯ."
            )

        if results.get("recognized_texts"):
            texts = [t.text for t in results["recognized_texts"]]
            recommendations.append(
                f"На изображении обнаружен текст: {', '.join(texts[:5])}. "
                "Рекомендуется проверить эти надписи на товарные знаки."
            )

        if results["overall_status"] == RiskLevel.YELLOW:
            recommendations.append(
                "Рекомендуется выполнить ручную проверку по указанным ссылкам."
            )

        if results["overall_status"] == RiskLevel.GREEN:
            recommendations.append(
                "Автоматическая проверка не выявила явных проблем. "
                "Рекомендуется дополнительно проверить источник изображения."
            )

        return recommendations


if __name__ == "__main__":
    # Пример использования
    checker = ComprehensiveImageChecker()

    # Тест с тестовым изображением
    print("Система проверки изображений готова к работе")
    print("\nДоступные сервисы для проверки:")
    for name, url in checker.searcher.generate_search_links("test.jpg").items():
        print(f"  - {name}: {url}")
