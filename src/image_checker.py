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
        """
        Извлечение текста с помощью EasyOCR.
        Улучшено для многострочного текста и текста под углом.
        """
        if not self.reader:
            print("[OCR] EasyOCR reader не инициализирован!")
            return []

        results = []
        found_texts = set()
        all_raw_detections = []  # Для диагностики

        try:
            print(f"[OCR] Обработка изображения: {image_path}")

            # Пробуем на оригинале и предобработанных вариантах
            variants = self._preprocess_image(image_path)
            print(f"[OCR] Создано {len(variants)} вариантов изображения")

            for idx, img_variant in enumerate(variants[:5]):  # Ограничиваем 5 вариантами для скорости
                try:
                    # EasyOCR может принимать PIL Image или путь
                    import numpy as np

                    # Конвертируем в RGB если нужно
                    if img_variant.mode != 'RGB':
                        img_variant = img_variant.convert('RGB')

                    img_array = np.array(img_variant)
                    print(f"[OCR] Вариант {idx}: размер {img_array.shape}, dtype={img_array.dtype}")

                    # Используем разные параметры для разных вариантов
                    # Низкий порог текста для обнаружения стилизованных шрифтов
                    detections = self.reader.readtext(
                        img_array,
                        paragraph=False,
                        width_ths=0.7,  # Увеличено для объединения слов
                        height_ths=0.7,
                        ycenter_ths=0.5,
                        add_margin=0.15,  # Увеличен отступ
                        text_threshold=0.3,  # Снижен порог текста (по умолчанию 0.7)
                        low_text=0.3,  # Снижен порог для низкого текста
                        link_threshold=0.3,  # Снижен порог связи
                        mag_ratio=1.5  # Увеличение масштаба для мелкого текста
                    )

                    print(f"[OCR] Вариант {idx}: найдено {len(detections)} детекций")

                    for detection in detections:
                        bbox, text, confidence = detection
                        text_clean = text.strip()
                        text_lower = text_clean.lower()

                        # Сохраняем для диагностики
                        all_raw_detections.append({
                            'variant': idx,
                            'text': text_clean,
                            'confidence': confidence,
                            'accepted': False
                        })

                        print(f"[OCR]   - '{text_clean}' (conf={confidence:.2f})")

                        # Дедупликация
                        if text_lower in found_texts:
                            continue

                        # БОЛЕЕ МЯГКИЕ критерии фильтрации для логотипов
                        # Снижен порог уверенности до 20% для стилизованных шрифтов
                        is_valid_text = (
                            confidence > 0.20 and  # Очень низкий порог для логотипов
                            len(text_clean) >= 2 and  # Минимум 2 символа
                            any(c.isalpha() for c in text_clean)  # Должны быть буквы
                        )

                        # Дополнительная проверка на мусор только если текст прошёл базовую
                        if is_valid_text and len(text_clean) > 3:
                            is_valid_text = not self._is_garbage_text(text_clean)

                        if is_valid_text:
                            found_texts.add(text_lower)
                            all_raw_detections[-1]['accepted'] = True

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
                            print(f"[OCR]   ✓ Принято: '{text_clean}'")
                        else:
                            print(f"[OCR]   ✗ Отклонено: '{text_clean}' (conf={confidence:.2f}, len={len(text_clean)})")

                except Exception as e:
                    print(f"[OCR] Ошибка для варианта {idx}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

            # Диагностика
            print(f"[OCR] Всего сырых детекций: {len(all_raw_detections)}")
            print(f"[OCR] Принято текстов: {len(results)}")

        except Exception as e:
            print(f"[OCR] Критическая ошибка EasyOCR: {e}")
            import traceback
            traceback.print_exc()

        # Сортируем по уверенности
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results

    def _preprocess_image(self, image_path: str) -> List[Image.Image]:
        """
        Предобработка изображения для улучшения OCR
        Возвращает список ОПТИМИЗИРОВАННЫХ вариантов изображения для распознавания
        Сокращено до 6 наиболее эффективных вариантов
        """
        img = Image.open(image_path)
        variants = []

        try:
            from PIL import ImageEnhance, ImageFilter, ImageOps
            import numpy as np

            # Конвертируем в RGB если нужно
            if img.mode != 'RGB':
                img_rgb = img.convert('RGB')
            else:
                img_rgb = img

            width, height = img_rgb.size
            print(f"[Preprocess] Оригинал: {width}x{height}")

            # === ОПТИМИЗИРОВАННЫЙ НАБОР (6 вариантов) ===

            # 1. Увеличенный оригинал (критично для мелкого текста!)
            scale = max(2, 1500 // max(width, height))
            large = img_rgb.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
            variants.append(large)

            # 2. Увеличенный + контраст (основной вариант)
            large_contrast = ImageEnhance.Contrast(large).enhance(2.0)
            variants.append(large_contrast)

            # 3. Оригинал (для качественных изображений)
            variants.append(img_rgb)

            # 4. Инверсия увеличенная (для светлого текста на тёмном фоне)
            inverted_large = ImageOps.invert(large)
            variants.append(inverted_large)

            # 5. Выделение цветного текста по насыщенности
            try:
                img_np = np.array(img_rgb)
                r_ch, g_ch, b_ch = img_np[:,:,0], img_np[:,:,1], img_np[:,:,2]

                max_rgb = np.maximum(np.maximum(r_ch, g_ch), b_ch)
                min_rgb = np.minimum(np.minimum(r_ch, g_ch), b_ch)
                saturation = np.where(max_rgb == 0, 0, (max_rgb - min_rgb) / max_rgb * 255).astype(np.uint8)

                # Маска цветного текста
                color_mask = saturation > 35
                result = np.where(color_mask, 0, 255).astype(np.uint8)
                color_text_img = Image.fromarray(result, mode='L')
                ct_large = color_text_img.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
                variants.append(ct_large.convert('RGB'))
            except:
                # Fallback: серое увеличенное
                gray_large = img_rgb.convert('L').resize((width * scale, height * scale), Image.Resampling.LANCZOS)
                variants.append(gray_large.convert('RGB'))

            # 6. Высокий контраст оригинала
            high_contrast = ImageEnhance.Contrast(img_rgb).enhance(2.5)
            variants.append(high_contrast)

            print(f"[Preprocess] Создано {len(variants)} оптимизированных вариантов")

        except Exception as e:
            print(f"[Preprocess] Ошибка предобработки: {e}")
            # Возвращаем хотя бы оригинал
            if not variants:
                variants = [img]

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

                            # Фильтр: текст > 2 символов, уверенность > 40%, должны быть буквы
                            is_valid = (
                                text and
                                len(text) > 2 and
                                conf > 40 and  # Повышен порог
                                any(c.isalpha() for c in text) and  # Должны быть буквы
                                not text.replace(' ', '').isdigit()  # Не только цифры
                            )
                            if is_valid:
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
        """Извлечение текста (использует все доступные OCR движки и комбинирует результаты)"""
        all_results = []
        found_texts = set()

        # Пробуем EasyOCR (обычно лучше для разных шрифтов)
        easyocr_results = self.extract_text_easyocr(image_path)
        for r in easyocr_results:
            text_lower = r.text.lower()
            if text_lower not in found_texts:
                found_texts.add(text_lower)
                all_results.append(r)
        print(f"[OCR] EasyOCR: {len(easyocr_results)} текстов")

        # Также пробуем Tesseract для дополнительного покрытия
        tesseract_results = self.extract_text_tesseract(image_path)
        for r in tesseract_results:
            text_lower = r.text.lower()
            if text_lower not in found_texts:
                found_texts.add(text_lower)
                all_results.append(r)
        print(f"[OCR] Tesseract: {len(tesseract_results)} текстов")

        # Объединяем близко расположенный текст
        merged = self._merge_nearby_text(all_results)
        print(f"[OCR] После объединения: {len(merged)} текстов")

        return merged

    def _is_garbage_text(self, text: str) -> bool:
        """
        Проверка, является ли текст мусорным (ложное распознавание)
        """
        text = text.strip()

        # Слишком короткий текст (менее 3 символов)
        if len(text) < 3:
            return True

        # Только знаки препинания и специальные символы
        if not any(c.isalnum() for c in text):
            return True

        # Случайные комбинации (нет гласных или слишком много согласных подряд)
        vowels = set('аеёиоуыэюяaeiou')
        consonants = set('бвгджзйклмнпрстфхцчшщbcdfghjklmnpqrstvwxyz')

        text_lower = text.lower()
        vowel_count = sum(1 for c in text_lower if c in vowels)
        consonant_count = sum(1 for c in text_lower if c in consonants)
        alpha_count = vowel_count + consonant_count

        # Если в тексте нет гласных (кроме аббревиатур)
        if alpha_count > 3 and vowel_count == 0:
            return True

        # Слишком много согласных подряд (5+)
        consecutive_consonants = 0
        max_consecutive = 0
        for c in text_lower:
            if c in consonants:
                consecutive_consonants += 1
                max_consecutive = max(max_consecutive, consecutive_consonants)
            else:
                consecutive_consonants = 0
        if max_consecutive >= 5:
            return True

        # Паттерны мусора от OCR
        garbage_patterns = [
            r'^[^a-zA-Zа-яА-ЯёЁ]*$',  # Нет букв
            r'^[a-z]{1,2}$',  # Одна-две маленькие буквы
            r'^[A-Z][a-z]?\??$',  # Одна большая + опционально маленькая + вопрос
            r'^[\?\!\.]+$',  # Только знаки препинания
        ]

        import re
        for pattern in garbage_patterns:
            if re.match(pattern, text):
                return True

        return False

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
                           distance_threshold: int = 50) -> List[TextOnImage]:
        """
        Улучшенное объединение близко расположенного текста.
        Поддерживает многострочный текст (вертикальное и горизонтальное объединение).
        """
        if len(texts) <= 1:
            return texts

        # Сортируем по позиции (сверху вниз, слева направо)
        texts = sorted(texts, key=lambda t: (t.position.get('y', 0), t.position.get('x', 0)))

        # Шаг 1: Объединяем текст на одной строке (горизонтально)
        horizontal_merged = []
        current_line = None

        for text in texts:
            if current_line is None:
                current_line = text
            else:
                # Проверяем, находятся ли тексты на одной линии
                current_y = current_line.position.get('y', 0)
                current_height = current_line.position.get('height', 20)
                text_y = text.position.get('y', 0)
                text_height = text.position.get('height', 20)

                # Тексты на одной линии, если их центры по Y близки
                current_center_y = current_y + current_height / 2
                text_center_y = text_y + text_height / 2
                y_diff = abs(text_center_y - current_center_y)

                # Горизонтальный промежуток между текстами
                current_right = current_line.position.get('x', 0) + current_line.position.get('width', 0)
                text_left = text.position.get('x', 0)
                x_gap = text_left - current_right

                # Объединяем если на одной строке и близко друг к другу
                max_height = max(current_height, text_height)
                if y_diff < max_height * 0.7 and x_gap < distance_threshold * 2:
                    # Объединяем на одной строке
                    current_line = TextOnImage(
                        text=f"{current_line.text} {text.text}",
                        confidence=min(current_line.confidence, text.confidence),
                        position={
                            "x": current_line.position.get('x', 0),
                            "y": min(current_y, text_y),
                            "width": (text.position.get('x', 0) + text.position.get('width', 0) -
                                      current_line.position.get('x', 0)),
                            "height": max(current_height, text_height)
                        },
                        language=current_line.language
                    )
                else:
                    horizontal_merged.append(current_line)
                    current_line = text

        if current_line:
            horizontal_merged.append(current_line)

        # Шаг 2: Объединяем строки вертикально (многострочный текст)
        if len(horizontal_merged) <= 1:
            return horizontal_merged

        # Сортируем по Y (сверху вниз)
        horizontal_merged = sorted(horizontal_merged, key=lambda t: t.position.get('y', 0))

        vertical_merged = []
        current_block = None

        for text in horizontal_merged:
            if current_block is None:
                current_block = text
            else:
                # Проверяем, можно ли объединить вертикально
                current_bottom = current_block.position.get('y', 0) + current_block.position.get('height', 0)
                text_top = text.position.get('y', 0)
                y_gap = text_top - current_bottom

                # Проверяем горизонтальное выравнивание
                current_x = current_block.position.get('x', 0)
                current_width = current_block.position.get('width', 100)
                text_x = text.position.get('x', 0)
                text_width = text.position.get('width', 100)

                # Тексты выровнены если их X координаты пересекаются
                x_overlap = (text_x < current_x + current_width) and (text_x + text_width > current_x)

                # Объединяем вертикально если близко и выровнены
                line_height = current_block.position.get('height', 20)
                if y_gap < line_height * 1.5 and x_overlap:
                    # Объединяем вертикально (многострочный текст)
                    current_block = TextOnImage(
                        text=f"{current_block.text}\n{text.text}",
                        confidence=min(current_block.confidence, text.confidence),
                        position={
                            "x": min(current_x, text_x),
                            "y": current_block.position.get('y', 0),
                            "width": max(current_x + current_width, text_x + text_width) - min(current_x, text_x),
                            "height": (text.position.get('y', 0) + text.position.get('height', 0) -
                                      current_block.position.get('y', 0))
                        },
                        language=current_block.language
                    )
                else:
                    vertical_merged.append(current_block)
                    current_block = text

        if current_block:
            vertical_merged.append(current_block)

        # Шаг 3: Также добавляем объединённый текст целиком (для брендов из нескольких слов)
        if len(vertical_merged) > 1:
            all_text = " ".join(t.text.replace('\n', ' ') for t in vertical_merged)
            if len(all_text) > 3:
                # Вычисляем среднюю уверенность
                avg_confidence = sum(t.confidence for t in vertical_merged) / len(vertical_merged)
                combined = TextOnImage(
                    text=all_text,
                    confidence=avg_confidence * 0.9,  # Немного снижаем для объединённого
                    position=vertical_merged[0].position,
                    language=vertical_merged[0].language
                )
                # Добавляем в конец списка
                vertical_merged.append(combined)

        return vertical_merged


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
        # Спортивные бренды
        "Nike", "Adidas", "Puma", "Reebok", "New Balance", "Fila",
        "Champion", "Under Armour", "Converse", "Vans", "Asics",
        "Jordan", "Umbro", "Kappa", "Ellesse", "Lacoste",
        # Техника
        "Apple", "Samsung", "Google", "Microsoft", "Sony", "LG",
        "Huawei", "Xiaomi", "Intel", "AMD", "Nvidia",
        # Медиа
        "Disney", "Marvel", "DC Comics", "Warner Bros", "Pixar",
        "DreamWorks", "Netflix", "HBO", "Nickelodeon",
        # Напитки и еда
        "Coca-Cola", "Pepsi", "McDonald's", "Starbucks", "KFC",
        "Burger King", "Subway", "Pizza Hut", "Red Bull",
        # Люкс
        "Louis Vuitton", "Gucci", "Chanel", "Prada", "Hermès",
        "Dior", "Versace", "Balenciaga", "Burberry", "Fendi",
        "Cartier", "Rolex", "Tiffany",
        # Авто
        "Ferrari", "Lamborghini", "BMW", "Mercedes", "Audi",
        "Porsche", "Maserati", "Tesla", "Bentley",
        # Retail
        "Amazon", "Ikea", "Zara", "H&M", "Gap", "Uniqlo",
        "Supreme", "Off-White", "Bape", "Thrasher",
    ]

    KNOWN_CHARACTERS = [
        "Mickey Mouse", "Микки Маус", "Minnie Mouse", "Donald Duck",
        "Spider-Man", "Человек-Паук", "Batman", "Бэтмен", "Superman",
        "Iron Man", "Hulk", "Thor", "Captain America",
        "Hello Kitty", "Pikachu", "Покемон", "Pokemon",
        "Shrek", "Frozen", "Elsa", "Эльза", "Minions", "Миньоны",
        "Peppa Pig", "Свинка Пеппа", "Маша и Медведь", "Фиксики",
        "Смешарики", "Лунтик", "Три кота",
        # Дополнительные персонажи
        "Teletubbies", "Телепузики", "Tinky Winky", "Dipsy", "Laa-Laa", "Po",
        "SpongeBob", "Губка Боб", "Patrick Star", "Патрик",
        "Paw Patrol", "Щенячий патруль",
        "Dora", "Даша Следопыт", "Dora Explorer",
        "Barbie", "Барби", "Ken",
        "Thomas", "Паровозик Томас", "Thomas Train",
        "Sonic", "Соник", "Mario", "Марио", "Luigi",
        "Winnie", "Винни Пух", "Winnie the Pooh", "Pooh",
        "Simpsons", "Симпсоны", "Homer", "Bart", "Lisa",
        "Tom and Jerry", "Том и Джерри",
        "Looney Tunes", "Bugs Bunny", "Багз Банни",
        "Scooby", "Скуби Ду", "Scooby-Doo"
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
        """Проверка текста на наличие известных элементов с нечётким поиском"""
        found = []
        text_lower = text.lower()

        # Точный поиск
        for item in items:
            if item.lower() in text_lower:
                found.append(item)

        # Нечёткий поиск (для ошибок OCR)
        if not found and len(text_lower) >= 4:
            from difflib import SequenceMatcher

            words = text_lower.replace('\n', ' ').split()
            for word in words:
                if len(word) < 3:
                    continue
                for item in items:
                    item_lower = item.lower()
                    # Проверяем похожесть
                    ratio = SequenceMatcher(None, word, item_lower).ratio()
                    if ratio > 0.7:  # 70% похожести
                        print(f"[Copyright] Нечёткое совпадение: '{word}' ~ '{item}' ({ratio:.2f})")
                        found.append(f"{item} (похоже на '{word}')")
                        break

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
