# -*- coding: utf-8 -*-
"""
Модуль проверки товарных знаков по различным базам данных
ФИПС, Роспатент, Linkmark, WIPO, EUIPO
"""

import re
import time
import json
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
import requests
from bs4 import BeautifulSoup
import Levenshtein
from transliterate import translit, get_available_language_codes

from config import TRADEMARK_RESOURCES, APP_CONFIG, API_KEYS
from models import TrademarkCheckResult, RiskLevel


class TextSimilarity:
    """Класс для проверки схожести текстов"""

    @staticmethod
    def normalize_text(text: str) -> str:
        """Нормализация текста для сравнения"""
        if not text:
            return ""
        # Приводим к нижнему регистру
        text = text.lower().strip()
        # Удаляем специальные символы
        text = re.sub(r'[^\w\s]', '', text)
        # Удаляем лишние пробелы
        text = re.sub(r'\s+', ' ', text)
        return text

    @staticmethod
    def levenshtein_similarity(text1: str, text2: str) -> float:
        """Расчет схожести по Левенштейну (0-1)"""
        text1 = TextSimilarity.normalize_text(text1)
        text2 = TextSimilarity.normalize_text(text2)

        if not text1 or not text2:
            return 0.0

        distance = Levenshtein.distance(text1, text2)
        max_len = max(len(text1), len(text2))

        if max_len == 0:
            return 1.0

        return 1 - (distance / max_len)

    @staticmethod
    def contains_similarity(text1: str, text2: str) -> float:
        """Проверка вхождения одного текста в другой"""
        text1 = TextSimilarity.normalize_text(text1)
        text2 = TextSimilarity.normalize_text(text2)

        if not text1 or not text2:
            return 0.0

        if text1 in text2 or text2 in text1:
            return 1.0

        return 0.0

    # Словарь фонетической транслитерации (созвучие)
    PHONETIC_MAP_RU_TO_EN = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }

    PHONETIC_MAP_EN_TO_RU = {
        'a': 'а', 'b': 'б', 'c': 'к', 'd': 'д', 'e': 'е', 'f': 'ф', 'g': 'г',
        'h': 'х', 'i': 'и', 'j': 'дж', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н',
        'o': 'о', 'p': 'п', 'q': 'к', 'r': 'р', 's': 'с', 't': 'т', 'u': 'у',
        'v': 'в', 'w': 'в', 'x': 'кс', 'y': 'й', 'z': 'з',
        'ch': 'ч', 'sh': 'ш', 'th': 'т', 'ph': 'ф', 'ck': 'к'
    }

    @staticmethod
    def transliterate_variants(text: str) -> List[str]:
        """
        Получение всех вариантов транслитерации для поиска созвучных названий.
        Возвращает оригинал + транслитерацию в обе стороны + фонетические варианты.
        """
        variants = [text]
        text_lower = text.lower()

        # Определяем язык текста
        has_cyrillic = any('\u0400' <= c <= '\u04FF' for c in text)
        has_latin = any('a' <= c.lower() <= 'z' for c in text)

        # 1. Стандартная транслитерация через библиотеку
        try:
            translit_ru = translit(text, 'ru', reversed=True)
            if translit_ru and translit_ru != text:
                variants.append(translit_ru)
        except:
            pass

        try:
            translit_en = translit(text, 'ru')
            if translit_en and translit_en != text:
                variants.append(translit_en)
        except:
            pass

        # 2. Фонетическая транслитерация (для созвучия)
        if has_cyrillic:
            # Русский → Латиница (фонетически)
            phonetic_en = ""
            for char in text_lower:
                phonetic_en += TextSimilarity.PHONETIC_MAP_RU_TO_EN.get(char, char)
            if phonetic_en and phonetic_en != text_lower:
                variants.append(phonetic_en)
                variants.append(phonetic_en.capitalize())

        if has_latin:
            # Латиница → Русский (фонетически)
            phonetic_ru = text_lower
            # Сначала заменяем диграфы
            for digraph, ru_char in sorted(TextSimilarity.PHONETIC_MAP_EN_TO_RU.items(),
                                           key=lambda x: -len(x[0])):
                if len(digraph) > 1:
                    phonetic_ru = phonetic_ru.replace(digraph, ru_char)
            # Потом одиночные буквы
            result = ""
            for char in phonetic_ru:
                if char in TextSimilarity.PHONETIC_MAP_EN_TO_RU and len(char) == 1:
                    result += TextSimilarity.PHONETIC_MAP_EN_TO_RU[char]
                else:
                    result += char
            phonetic_ru = result
            if phonetic_ru and phonetic_ru != text_lower:
                variants.append(phonetic_ru)
                variants.append(phonetic_ru.capitalize())

        # 3. Альтернативные написания (частые замены)
        alternatives = {
            'c': 'k', 'k': 'c',  # c/k взаимозаменяемы
            'i': 'y', 'y': 'i',  # i/y взаимозаменяемы
            'ph': 'f', 'f': 'ph',
            'ks': 'x', 'x': 'ks',
        }
        for old, new in alternatives.items():
            if old in text_lower:
                variants.append(text_lower.replace(old, new))

        # Убираем дубликаты и пустые
        return list(set(v for v in variants if v and v.strip()))

    @staticmethod
    def check_similarity(text1: str, text2: str,
                         threshold: float = 0.8) -> Tuple[bool, float, str]:
        """
        Комплексная проверка схожести текстов

        Returns:
            (is_similar, score, reason)
        """
        norm1 = TextSimilarity.normalize_text(text1)
        norm2 = TextSimilarity.normalize_text(text2)

        # Точное совпадение
        if norm1 == norm2:
            return True, 1.0, "Точное совпадение"

        # Проверка вхождения - оценка ЗАВИСИТ от соотношения длин
        if norm1 in norm2 or norm2 in norm1:
            shorter = min(len(norm1), len(norm2))
            longer = max(len(norm1), len(norm2))
            # Чем больше разница в длине, тем меньше оценка
            containment_score = shorter / longer
            # Если тексты очень разные по длине - это частичное совпадение
            if containment_score < 0.7:
                return True, containment_score, f"Частичное вхождение ({containment_score:.0%})"
            else:
                return True, 0.9, "Один текст содержится в другом"

        # Проверка по Левенштейну
        lev_score = TextSimilarity.levenshtein_similarity(text1, text2)
        if lev_score >= threshold:
            return True, lev_score, f"Схожесть по Левенштейну: {lev_score:.2f}"

        # Проверка транслитерации
        variants1 = TextSimilarity.transliterate_variants(text1)
        variants2 = TextSimilarity.transliterate_variants(text2)

        best_translit_score = 0
        for v1 in variants1:
            for v2 in variants2:
                v1_norm = TextSimilarity.normalize_text(v1)
                v2_norm = TextSimilarity.normalize_text(v2)

                # Точное совпадение транслитерации
                if v1_norm == v2_norm:
                    return True, 1.0, "Точное совпадение (транслитерация)"

                # Вхождение с учётом транслитерации
                if v1_norm in v2_norm or v2_norm in v1_norm:
                    shorter = min(len(v1_norm), len(v2_norm))
                    longer = max(len(v1_norm), len(v2_norm))
                    containment_score = shorter / longer
                    if containment_score > best_translit_score:
                        best_translit_score = containment_score

                score = TextSimilarity.levenshtein_similarity(v1, v2)
                if score > best_translit_score:
                    best_translit_score = score

        if best_translit_score >= threshold:
            return True, best_translit_score, f"Схожесть с транслитерацией: {best_translit_score:.2f}"

        return False, max(lev_score, best_translit_score), "Нет значительного сходства"


class TrademarkChecker:
    """Базовый класс для проверки товарных знаков"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.similarity_threshold = APP_CONFIG["text_similarity_threshold"]

    def check_trademark(self, text: str, mktu_classes: List[int] = None) -> TrademarkCheckResult:
        """Абстрактный метод проверки - переопределяется в подклассах"""
        raise NotImplementedError


class RospatentPlatformChecker(TrademarkChecker):
    """
    Проверка через официальный API платформы Роспатента
    https://searchplatform.rospatent.gov.ru/patsearch/v0.2/

    ВАЖНО: Этот API предназначен для патентного поиска.
    Для поиска товарных знаков используйте веб-интерфейс:
    https://searchplatform.rospatent.gov.ru/trademarks

    Документация API: Открытые_API_ИС_ПП.docx
    """

    def __init__(self):
        super().__init__()
        self.base_url = "https://searchplatform.rospatent.gov.ru"
        self.api_url = f"{self.base_url}/patsearch/v0.2"
        self.search_url = f"{self.api_url}/search"
        self.tm_search_url = f"{self.base_url}/trademarks"  # Веб-интерфейс для ТЗ
        self.resource_info = TRADEMARK_RESOURCES["rospatent_platform"]

        # Добавляем авторизацию через Bearer токен
        api_key = API_KEYS.get("rospatent", "")
        if api_key:
            self.session.headers.update({
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            })
            self.api_available = True
        else:
            self.api_available = False

    def check_trademark(self, text: str, mktu_classes: List[int] = None) -> TrademarkCheckResult:
        """
        Проверка через патентный API Роспатента.

        Примечание: API ищет по патентам, а не по товарным знакам напрямую.
        Для полноценной проверки ТЗ рекомендуется ручная проверка через веб-интерфейс.
        """
        result = TrademarkCheckResult(
            resource_name=self.resource_info["name"],
            resource_url=self.tm_search_url,  # Ссылка на веб-интерфейс ТЗ
            search_query=text,
            mktu_classes=mktu_classes or []
        )

        if not self.api_available:
            result.notes = f"API ключ не настроен. Проверьте ТЗ вручную: {self.tm_search_url}"
            result.status = RiskLevel.YELLOW
            return result

        try:
            # Патентный поиск - находит упоминания в патентных документах
            search_body = {
                "qn": text,
                "limit": 20,
                "offset": 0,
                "sort": "relevance"
            }

            # Выполняем POST запрос к API (увеличен таймаут до 60 сек)
            response = self.session.post(
                self.search_url,
                json=search_body,
                timeout=60
            )

            if response.status_code == 200:
                data = response.json()
                self._process_search_results(result, data, text)
            elif response.status_code == 401:
                result.notes = "Ошибка авторизации API. Проверьте API ключ."
                result.status = RiskLevel.YELLOW
            elif response.status_code == 403:
                result.notes = "Доступ к API запрещён. Проверьте права доступа."
                result.status = RiskLevel.YELLOW
            else:
                result.notes = f"Ошибка API ({response.status_code}). Рекомендуется ручная проверка."
                result.status = RiskLevel.YELLOW

        except requests.exceptions.RequestException as e:
            result.notes = f"Ошибка подключения к API: {str(e)}. Рекомендуется ручная проверка."
            result.status = RiskLevel.YELLOW
        except Exception as e:
            result.notes = f"Ошибка обработки: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result

    def _process_search_results(self, result: TrademarkCheckResult,
                                 data: Dict, search_text: str):
        """Обработка результатов поиска API Роспатента"""
        # Получаем общее количество найденных результатов
        total = data.get("total", 0)
        hits = data.get("hits", [])

        if total == 0:
            result.status = RiskLevel.GREEN
            result.notes = "Совпадений в базе Роспатента не найдено"
            return

        for hit in hits:
            # Извлекаем данные из структуры ответа API
            snippet = hit.get("snippet", {})

            # Название товарного знака может быть в разных полях
            trademark_text = (
                snippet.get("title", "") or
                snippet.get("name", "") or
                hit.get("id", "")
            )

            # Номер регистрации
            reg_number = snippet.get("registration_number", "") or snippet.get("reg_number", "")

            # Классы МКТУ
            tm_classes = snippet.get("index_class", [])
            if isinstance(tm_classes, str):
                tm_classes = [tm_classes]

            # Статус товарного знака
            tm_status = snippet.get("status", "")

            # Правообладатель
            holder = snippet.get("holder", "") or snippet.get("applicant", "")

            # Проверяем схожесть
            is_similar, score, reason = TextSimilarity.check_similarity(
                search_text, trademark_text, self.similarity_threshold
            )

            if is_similar:
                result.found_matches.append({
                    "text": trademark_text,
                    "registration_number": reg_number,
                    "similarity_score": score,
                    "reason": reason,
                    "classes": tm_classes,
                    "status": tm_status,
                    "holder": holder,
                    "dataset": hit.get("dataset", ""),
                    "doc_id": hit.get("id", "")
                })

                if score == 1.0:
                    result.exact_match = True
                else:
                    result.similar_match = True

                if reg_number:
                    result.registration_numbers.append(reg_number)
                result.similarity_score = max(result.similarity_score, score)

        # ВАЖНО: Это патентный поиск, не поиск товарных знаков!
        # Результаты носят информационный характер
        # Основная проверка ТЗ идёт через Linkmark

        result.status = RiskLevel.GREEN  # Патентный поиск не влияет на статус ТЗ
        result.found_matches = []  # Не показываем патенты как ТЗ

        if total > 0:
            result.notes = f"Патенты: {total} упоминаний. Для проверки ТЗ см. Linkmark."
        else:
            result.notes = "В патентной базе упоминаний не найдено."

    def get_document_details(self, doc_id: str) -> Optional[Dict]:
        """Получение детальной информации о документе по ID"""
        if not self.api_available:
            return None

        try:
            url = f"{self.api_url}/docs/{doc_id}"
            response = self.session.get(url, timeout=30)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return None

    def similar_image_search(self, image_path: str) -> Optional[Dict]:
        """Поиск похожих изображений товарных знаков"""
        if not self.api_available:
            return None

        try:
            url = f"{self.api_url}/similar_search"
            with open(image_path, 'rb') as f:
                files = {'file': f}
                # Для загрузки файла нужно убрать Content-Type из заголовков
                headers = dict(self.session.headers)
                if 'Content-Type' in headers:
                    del headers['Content-Type']
                response = requests.post(
                    url,
                    files=files,
                    headers=headers,
                    timeout=60
                )
                if response.status_code == 200:
                    return response.json()
        except:
            pass
        return None

    def get_manual_search_url(self, text: str, mktu_classes: List[int] = None) -> str:
        """Получение URL для ручного поиска"""
        params = {"q": text}
        if mktu_classes:
            params["classes"] = ",".join(map(str, mktu_classes))
        return f"{self.resource_info['url']}?{urllib.parse.urlencode(params)}"


class LinkmarkChecker(TrademarkChecker):
    """
    Проверка через Linkmark - бесплатный поиск по товарным знакам РФ
    https://linkmark.ru/

    Linkmark получает данные из базы ФИПС/Роспатента и предоставляет
    удобный веб-интерфейс для поиска.
    """

    def __init__(self):
        super().__init__()
        self.base_url = "https://linkmark.ru"
        self.search_url = f"{self.base_url}/search"
        self.resource_info = TRADEMARK_RESOURCES["linkmark"]

    def check_trademark(self, text: str, mktu_classes: List[int] = None) -> TrademarkCheckResult:
        """
        Проверка товарного знака через Linkmark.
        Автоматически проверяет все варианты транслитерации для поиска созвучных названий.
        """
        result = TrademarkCheckResult(
            resource_name=self.resource_info["name"],
            resource_url=self.resource_info["url"],
            search_query=text,
            mktu_classes=mktu_classes or []
        )

        # Получаем все варианты транслитерации для поиска
        search_variants = TextSimilarity.transliterate_variants(text)
        print(f"[Linkmark] Поиск вариантов: {search_variants}")

        all_found_matches = []
        best_status = RiskLevel.GREEN
        search_notes = []

        for variant in search_variants[:3]:  # Проверяем до 3 вариантов
            try:
                # POST запрос на поиск
                search_data = {"search": variant}

                response = self.session.post(
                    self.search_url,
                    data=search_data,
                    timeout=30,
                    allow_redirects=True
                )

                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    # Временный результат для этого варианта
                    temp_result = TrademarkCheckResult(
                        resource_name=self.resource_info["name"],
                        resource_url=self.resource_info["url"],
                        search_query=variant,
                        mktu_classes=mktu_classes or []
                    )
                    self._parse_linkmark_results(temp_result, soup, variant, mktu_classes)
                    print(f"[Linkmark] После _parse: temp_result.found_matches = {len(temp_result.found_matches)}")

                    # Собираем результаты
                    for match in temp_result.found_matches:
                        # Добавляем информацию о варианте поиска
                        match['search_variant'] = variant
                        if match not in all_found_matches:
                            all_found_matches.append(match)

                    # Обновляем лучший статус
                    if temp_result.status == RiskLevel.RED:
                        best_status = RiskLevel.RED
                        if temp_result.exact_match:
                            result.exact_match = True
                        if temp_result.similar_match:
                            result.similar_match = True
                    elif temp_result.status == RiskLevel.YELLOW and best_status != RiskLevel.RED:
                        best_status = RiskLevel.YELLOW

                    if temp_result.notes:
                        search_notes.append(f"[{variant}]: {temp_result.notes}")

                    # Обновляем similarity_score
                    result.similarity_score = max(result.similarity_score, temp_result.similarity_score)

                    # Небольшая пауза между запросами
                    if len(search_variants) > 1:
                        time.sleep(0.5)

            except requests.exceptions.RequestException as e:
                search_notes.append(f"[{variant}]: Ошибка подключения")
            except Exception as e:
                search_notes.append(f"[{variant}]: Ошибка: {str(e)}")

        # Устанавливаем итоговые результаты
        print(f"[Linkmark FINAL] all_found_matches: {len(all_found_matches)}, best_status: {best_status}")
        result.found_matches = all_found_matches[:15]  # Максимум 15 результатов
        print(f"[Linkmark FINAL] result.found_matches assigned: {len(result.found_matches)}")
        result.status = best_status

        # Формируем итоговые заметки
        if len(search_variants) > 1:
            variants_info = f" (проверены варианты: {', '.join(search_variants[:3])})"
        else:
            variants_info = ""

        if result.exact_match:
            result.notes = f"Найден тождественный ТЗ!{variants_info}"
        elif result.similar_match:
            result.notes = f"Найдены похожие ТЗ{variants_info}"
        elif all_found_matches:
            result.notes = f"Найдено {len(all_found_matches)} результатов{variants_info}"
        else:
            result.notes = f"Совпадений не найдено{variants_info}"

        if not all_found_matches and not result.notes:
            result.notes = f"Рекомендуется ручная проверка на {self.base_url}"
            result.status = RiskLevel.YELLOW

        return result

    def _parse_linkmark_results(self, result: TrademarkCheckResult,
                                 soup: BeautifulSoup, search_text: str,
                                 mktu_filter: List[int] = None):
        """
        Парсинг результатов поиска Linkmark с СТРОГОЙ фильтрацией по МКТУ.
        Если указаны классы МКТУ - показываются ТОЛЬКО результаты в этих классах.
        """

        # Ищем счетчики результатов в табах
        total_marks = 0
        total_apps = 0

        tabs = soup.find_all('li', {'data-name': True})
        for tab in tabs:
            count_div = tab.find('div', class_='result-count')
            if count_div:
                try:
                    count = int(count_div.get_text(strip=True))
                    tab_name = tab.get('data-name', '')
                    if tab_name == 'tab-marks':
                        total_marks = count
                    elif tab_name == 'tab-apps':
                        total_apps = count
                except ValueError:
                    pass

        # Преобразуем фильтр МКТУ в строки для сравнения
        mktu_filter_str = set(str(c) for c in mktu_filter) if mktu_filter else None
        print(f"[Linkmark] mktu_filter={mktu_filter}, mktu_filter_str={mktu_filter_str}")

        # Ищем карточки товарных знаков
        items = soup.find_all('div', class_='result-div-item')
        print(f"[Linkmark] Найдено {len(items)} карточек ТЗ на странице")

        # Счётчики для статистики
        matches_in_mktu = 0  # Совпадения в выбранных классах МКТУ
        matches_outside_mktu = 0  # Совпадения вне выбранных классов
        high_similarity_count = 0  # Высокое сходство (>80%)

        # Списки для разделения результатов
        results_in_mktu = []  # Результаты в выбранных классах МКТУ
        results_outside_mktu = []  # Результаты вне выбранных классов

        for item in items[:50]:  # Обрабатываем больше для лучшей фильтрации
            # Извлекаем номер свидетельства
            number_div = item.find('div', class_='result-div-item-number')
            reg_number = ""
            if number_div:
                link = number_div.find('a')
                if link:
                    reg_number = link.get_text(strip=True)

            # Извлекаем классы МКТУ
            mktu_div = item.find('div', class_='result-div-item-mktu')
            tm_classes = []
            if mktu_div:
                mktu_text = mktu_div.get_text(strip=True)
                tm_classes = [c.strip() for c in mktu_text.split(',') if c.strip()]

            # Проверяем, попадает ли ТЗ в выбранные классы МКТУ
            mktu_match = False
            if mktu_filter_str:
                mktu_match = bool(set(tm_classes) & mktu_filter_str)
            else:
                mktu_match = True  # Если фильтр не указан, считаем совпадением

            # Извлекаем правообладателя
            owner_div = item.find('div', class_='result-div-item-owner')
            holder = ""
            if owner_div:
                holder = owner_div.get_text(strip=True)

            # Извлекаем статус
            status_div = item.find('div', class_='result-div-item-status')
            tm_status = ""
            if status_div:
                status_text = status_div.find('div')
                if status_text:
                    tm_status = status_text.get_text(strip=True)

            # Извлекаем слова из товарного знака
            words_div = item.find('div', class_='words-part')
            trademark_words = ""
            if words_div:
                trademark_words = words_div.get_text(strip=True)

            # Проверяем схожесть с ЦЕЛЫМ названием товарного знака
            compare_text = trademark_words if trademark_words else ""
            best_score = 0.0
            best_reason = "Найден в результатах поиска"
            is_exact_name_match = False  # Флаг точного совпадения ВСЕГО названия

            if compare_text:
                search_normalized = TextSimilarity.normalize_text(search_text)
                compare_normalized = TextSimilarity.normalize_text(compare_text)

                # 1. Проверяем точное совпадение ВСЕГО названия
                if search_normalized == compare_normalized:
                    best_score = 1.0
                    best_reason = "Точное совпадение названия"
                    is_exact_name_match = True
                else:
                    # 1.1 Проверяем совпадение с учётом транслитерации
                    search_variants = TextSimilarity.transliterate_variants(search_text)
                    compare_variants = TextSimilarity.transliterate_variants(compare_text)
                    for sv in search_variants:
                        sv_norm = TextSimilarity.normalize_text(sv)
                        for cv in compare_variants:
                            cv_norm = TextSimilarity.normalize_text(cv)
                            if sv_norm == cv_norm:
                                best_score = 1.0
                                best_reason = "Точное совпадение (транслитерация)"
                                is_exact_name_match = True
                                break
                        if is_exact_name_match:
                            break

                if not is_exact_name_match:
                    # 2. Проверяем схожесть ВСЕГО названия
                    is_similar_full, score_full, reason_full = TextSimilarity.check_similarity(
                        search_text, compare_text, 0.7
                    )
                    if score_full > best_score:
                        best_score = score_full
                        best_reason = reason_full

                    # 3. Проверяем, является ли наш запрос одним из слов в ТЗ
                    # Но это НЕ считается точным совпадением - только частичное
                    words_list = compare_normalized.split()
                    if len(words_list) > 1:  # Только если в ТЗ несколько слов
                        for word in words_list:
                            word_similarity = TextSimilarity.levenshtein_similarity(search_normalized, word)
                            if word_similarity >= 0.9:
                                # Слово найдено, но это часть составного названия
                                # Снижаем оценку пропорционально длине названия
                                partial_score = word_similarity * (len(search_normalized) / len(compare_normalized))
                                partial_score = min(partial_score, 0.7)  # Максимум 70% для частичного совпадения
                                if partial_score > best_score:
                                    best_score = partial_score
                                    best_reason = f"Частичное совпадение (слово '{word}' в составном названии)"

                    # 4. Если наш запрос длиннее - проверяем, содержится ли ТЗ в нашем запросе
                    if search_normalized in compare_normalized or compare_normalized in search_normalized:
                        # Одно содержится в другом - оцениваем по соотношению длин
                        shorter = min(len(search_normalized), len(compare_normalized))
                        longer = max(len(search_normalized), len(compare_normalized))
                        containment_score = shorter / longer
                        if containment_score > best_score and containment_score < 0.9:
                            best_score = containment_score
                            best_reason = "Частичное вхождение"

            # Определяем уровень совпадения
            # Точное совпадение - только если ПОЛНОСТЬЮ совпадает название
            is_exact = is_exact_name_match and best_score >= 0.95
            is_high_similar = best_score >= 0.8 and not is_exact_name_match
            # Показываем ВСЕ результаты из поиска Linkmark (они уже отфильтрованы по запросу)
            # Если есть номер регистрации - это валидный результат из Linkmark
            is_relevant = bool(reg_number)  # Любой результат с номером регистрации

            # Если нет score, устанавливаем минимальный для отображения
            if best_score == 0 and reg_number:
                best_score = 0.1
                best_reason = "Найден в результатах поиска Linkmark"

            # Создаём информацию о совпадении
            match_info = {
                "text": trademark_words or f"ТЗ №{reg_number}",
                "registration_number": reg_number,
                "similarity_score": best_score,  # 0-1 для логики, умножается на 100 в шаблоне
                "reason": best_reason,
                "classes": tm_classes,
                "classes_str": ", ".join(tm_classes) if tm_classes else "не указаны",
                "status": tm_status,
                "holder": holder[:100] if holder else "",
                "mktu_match": mktu_match
            }

            # Отладка: выводим найденные результаты
            print(f"[Linkmark DEBUG] ТЗ #{reg_number}: '{trademark_words[:40] if trademark_words else '-'}', МКТУ: {tm_classes}, score: {best_score:.2f}, mktu_match: {mktu_match}, is_relevant: {is_relevant}")

            # СТРОГАЯ фильтрация по МКТУ:
            # Если указан фильтр МКТУ - добавляем ТОЛЬКО совпадения в этих классах
            if mktu_filter_str:
                if mktu_match:
                    # Совпадение в выбранном классе МКТУ - добавляем ВСЕ результаты
                    if is_relevant:
                        results_in_mktu.append(match_info)
                        matches_in_mktu += 1

                        if is_exact:
                            result.exact_match = True
                        elif is_high_similar:
                            result.similar_match = True
                            high_similarity_count += 1

                        result.similarity_score = max(result.similarity_score, best_score)
                        if reg_number:
                            result.registration_numbers.append(reg_number)
                else:
                    # Совпадение вне выбранного класса - считаем для информации
                    if is_relevant:
                        matches_outside_mktu += 1
                        results_outside_mktu.append(match_info)
            else:
                # Фильтр МКТУ не указан - показываем ВСЕ результаты из поиска
                if is_relevant:
                    results_in_mktu.append(match_info)

                    if is_exact:
                        result.exact_match = True
                    elif is_high_similar:
                        result.similar_match = True
                        high_similarity_count += 1

                    result.similarity_score = max(result.similarity_score, best_score)
                    if reg_number:
                        result.registration_numbers.append(reg_number)

        # Формируем итоговые результаты
        # Сортировка: 1) по схожести (полные совпадения первыми), 2) действующие первыми, 3) истёкшие последними
        def sort_key(x):
            # Схожесть: полные совпадения (>= 0.9) получают приоритет 0
            similarity = x.get('similarity_score', 0)
            if similarity >= 0.9:
                similarity_priority = 0
            elif similarity >= 0.7:
                similarity_priority = 1
            else:
                similarity_priority = 2

            # Статус: "действует" = 0 (первые), "истёк"/"не действует" = 1 (последние)
            status_lower = x.get('status', '').lower()
            if status_lower in ['действует', 'действующий']:
                status_priority = 0
            elif 'истёк' in status_lower or 'истек' in status_lower or 'не действует' in status_lower:
                status_priority = 2  # В самый конец
            else:
                status_priority = 1

            # Детальная схожесть для вторичной сортировки (инвертируем)
            detail_similarity = 1 - similarity

            return (similarity_priority, status_priority, detail_similarity)

        results_in_mktu.sort(key=sort_key)
        print(f"[Linkmark] results_in_mktu: {len(results_in_mktu)}, results_outside_mktu: {len(results_outside_mktu)}")
        result.found_matches = results_in_mktu[:15]  # Показываем до 15 результатов
        print(f"[Linkmark] result.found_matches: {len(result.found_matches)}")

        # Определяем статус с учётом фильтра МКТУ
        self._set_status(result, total_marks, total_apps, matches_in_mktu,
                        matches_outside_mktu, mktu_filter)

    def _set_status(self, result: TrademarkCheckResult, total_marks: int = 0,
                    total_apps: int = 0, matches_in_mktu: int = 0,
                    matches_outside_mktu: int = 0, mktu_filter: List[int] = None):
        """
        Установка статуса на основе результатов.
        ВАЖНО: Статус определяется ТОЛЬКО по совпадениям в выбранных классах МКТУ.
        """

        mktu_info = f" (класс {', '.join(map(str, mktu_filter))})" if mktu_filter else ""

        if mktu_filter:
            # СТРОГИЙ РЕЖИМ: указаны классы МКТУ
            if result.exact_match:
                result.status = RiskLevel.RED
                result.notes = f"🔴 ЗАПРЕЩЕНО: Найден тождественный ТЗ в классе{mktu_info}!"
            elif result.similar_match and matches_in_mktu > 0:
                result.status = RiskLevel.RED
                result.notes = f"🔴 ВНИМАНИЕ: Найдено {matches_in_mktu} похожих ТЗ в классе{mktu_info}"
            elif matches_in_mktu > 0:
                result.status = RiskLevel.YELLOW
                result.notes = f"🟡 Найдено {matches_in_mktu} ТЗ в классе{mktu_info}. Требуется анализ."
            elif matches_outside_mktu > 0:
                # Есть совпадения, но в других классах - это ЗЕЛЁНЫЙ для выбранного класса
                result.status = RiskLevel.GREEN
                result.notes = f"🟢 В классе{mktu_info} совпадений НЕТ. (В других классах: {matches_outside_mktu} ТЗ)"
            elif total_marks > 0:
                result.status = RiskLevel.GREEN
                result.notes = f"🟢 В классе{mktu_info} совпадений НЕТ. (Всего в базе: {total_marks} похожих ТЗ в других классах)"
            else:
                result.status = RiskLevel.GREEN
                result.notes = f"🟢 Совпадений в базе ТЗ РФ не найдено{mktu_info}"
        else:
            # БЕЗ ФИЛЬТРА МКТУ: показываем всё
            if result.exact_match:
                result.status = RiskLevel.RED
                result.notes = f"🔴 ЗАПРЕЩЕНО: Найден тождественный ТЗ! Всего в базе: {total_marks} ТЗ"
            elif result.similar_match:
                result.status = RiskLevel.YELLOW
                result.notes = f"🟡 Найдены похожие ТЗ (всего {total_marks}). Укажите класс МКТУ для точной проверки."
            elif total_marks > 0:
                result.status = RiskLevel.YELLOW
                result.notes = f"🟡 Найдено {total_marks} ТЗ с похожими названиями. Укажите класс МКТУ для точной проверки."
            else:
                result.status = RiskLevel.GREEN
                result.notes = f"🟢 Совпадений в базе ТЗ РФ не найдено"


class WIPOChecker(TrademarkChecker):
    """
    Проверка через WIPO Global Brand Database
    https://branddb.wipo.int/
    """

    def __init__(self):
        super().__init__()
        self.base_url = "https://branddb.wipo.int"
        self.api_url = f"{self.base_url}/branddb/en/similarname"
        self.resource_info = TRADEMARK_RESOURCES["wipo"]

    def check_trademark(self, text: str, mktu_classes: List[int] = None) -> TrademarkCheckResult:
        """Проверка товарного знака через WIPO"""
        result = TrademarkCheckResult(
            resource_name=self.resource_info["name"],
            resource_url=self.resource_info["url"],
            search_query=text,
            mktu_classes=mktu_classes or []
        )

        try:
            # WIPO имеет сложный API, формируем структуру запроса
            search_structure = {
                "boolean": "AND",
                "bricks": [
                    {
                        "key": "brandName",
                        "value": text,
                        "strategy": "Simple"
                    }
                ]
            }

            if mktu_classes:
                search_structure["bricks"].append({
                    "key": "niceClass",
                    "value": ",".join(map(str, mktu_classes)),
                    "strategy": "Simple"
                })

            params = {
                "sort": "score desc",
                "start": 0,
                "rows": 30,
                "asStructure": json.dumps(search_structure)
            }

            response = self.session.get(
                self.api_url,
                params=params,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                self._process_wipo_results(result, data, text)
            else:
                result.notes = f"Рекомендуется ручная проверка на {self.base_url}"
                result.status = RiskLevel.YELLOW

        except Exception as e:
            result.notes = f"Требуется ручная проверка: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result

    def _process_wipo_results(self, result: TrademarkCheckResult,
                               data: Dict, search_text: str):
        """Обработка результатов WIPO"""
        docs = data.get("response", {}).get("docs", [])

        for doc in docs:
            brand_name = doc.get("brandName", "")

            is_similar, score, reason = TextSimilarity.check_similarity(
                search_text, brand_name, self.similarity_threshold
            )

            if is_similar:
                result.found_matches.append({
                    "text": brand_name,
                    "registration_number": doc.get("ST13", ""),
                    "similarity_score": score,
                    "reason": reason,
                    "holder": doc.get("holderName", ""),
                    "country": doc.get("designationCurrentStatusCode", ""),
                    "classes": doc.get("niceClass", [])
                })

                if score == 1.0:
                    result.exact_match = True
                else:
                    result.similar_match = True

                result.similarity_score = max(result.similarity_score, score)

        # Определяем статус
        if result.exact_match:
            result.status = RiskLevel.RED
            result.notes = "Найден тождественный международный товарный знак"
        elif result.similar_match:
            result.status = RiskLevel.YELLOW
            result.notes = "Найдены похожие международные товарные знаки"
        else:
            result.status = RiskLevel.GREEN
            result.notes = "Совпадений в международной базе не найдено"

    def get_manual_search_url(self, text: str) -> str:
        """URL для ручного поиска"""
        encoded = urllib.parse.quote(text)
        return f"{self.base_url}/branddb/en/?q=brandName:{encoded}"


class ComprehensiveTrademarkChecker:
    """
    Комплексная проверка товарных знаков по всем доступным базам
    """

    def __init__(self):
        self.checkers = {
            "linkmark": LinkmarkChecker()
        }

    def check_all(self, text: str, mktu_classes: List[int] = None,
                  check_international: bool = True) -> List[TrademarkCheckResult]:
        """
        Проверка по всем базам

        Args:
            text: Текст для проверки
            mktu_classes: Классы МКТУ
            check_international: Проверять ли международные базы
        """
        results = []

        # Российские базы
        linkmark_result = self.checkers["linkmark"].check_trademark(text, mktu_classes)
        results.append(linkmark_result)

        return results

    def get_overall_status(self, results: List[TrademarkCheckResult]) -> Tuple[RiskLevel, str]:
        """
        Определение общего статуса на основе всех результатов
        """
        has_red = any(r.status == RiskLevel.RED for r in results)
        has_yellow = any(r.status == RiskLevel.YELLOW for r in results)

        if has_red:
            return RiskLevel.RED, "Обнаружены критические совпадения с товарными знаками"
        elif has_yellow:
            return RiskLevel.YELLOW, "Требуется дополнительная проверка товарных знаков"
        else:
            return RiskLevel.GREEN, "Проверка товарных знаков не выявила проблем"

    def generate_manual_check_links(self, text: str, mktu_classes: List[int] = None) -> Dict[str, str]:
        """Генерация ссылок для ручной проверки"""
        links = {}

        # Платформа Роспатента
        rospatent_url = TRADEMARK_RESOURCES["rospatent_platform"]["url"]
        if mktu_classes:
            params = {"q": text, "classes": ",".join(map(str, mktu_classes))}
        else:
            params = {"q": text}
        links["Платформа Роспатента"] = f"{rospatent_url}?{urllib.parse.urlencode(params)}"

        # Проверка товарного знака (Linkmark)
        links["Проверка товарного знака"] = f"{TRADEMARK_RESOURCES['linkmark']['url']}?search={urllib.parse.quote(text)}"

        # WIPO Global Brand Database (международная база)
        wipo_params = {"brandName": text}
        if mktu_classes:
            wipo_params["niceClass"] = ",".join(map(str, mktu_classes))
        links["WIPO Global Brand Database"] = f"https://branddb.wipo.int/en/quicksearch/brand?{urllib.parse.urlencode(wipo_params)}"

        return links


if __name__ == "__main__":
    # Пример использования
    checker = ComprehensiveTrademarkChecker()

    # Тест проверки
    test_text = "EXAMPLE BRAND"
    test_classes = [25, 35]

    print(f"Проверка товарного знака: {test_text}")
    print(f"Классы МКТУ: {test_classes}")
    print("-" * 50)

    # Получаем ссылки для ручной проверки
    links = checker.generate_manual_check_links(test_text, test_classes)
    print("\nСсылки для ручной проверки:")
    for name, url in links.items():
        print(f"  {name}: {url}")
