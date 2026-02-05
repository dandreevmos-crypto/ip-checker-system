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

    @staticmethod
    def transliterate_variants(text: str) -> List[str]:
        """Получение вариантов транслитерации"""
        variants = [text]

        # Транслитерация с русского на латиницу
        try:
            translit_ru = translit(text, 'ru', reversed=True)
            variants.append(translit_ru)
        except:
            pass

        # Транслитерация с латиницы на русский
        try:
            translit_en = translit(text, 'ru')
            variants.append(translit_en)
        except:
            pass

        return list(set(variants))

    @staticmethod
    def check_similarity(text1: str, text2: str,
                         threshold: float = 0.8) -> Tuple[bool, float, str]:
        """
        Комплексная проверка схожести текстов

        Returns:
            (is_similar, score, reason)
        """
        # Точное совпадение
        if TextSimilarity.normalize_text(text1) == TextSimilarity.normalize_text(text2):
            return True, 1.0, "Точное совпадение"

        # Проверка вхождения
        if TextSimilarity.contains_similarity(text1, text2) == 1.0:
            return True, 0.95, "Один текст содержится в другом"

        # Проверка по Левенштейну
        lev_score = TextSimilarity.levenshtein_similarity(text1, text2)
        if lev_score >= threshold:
            return True, lev_score, f"Схожесть по Левенштейну: {lev_score:.2f}"

        # Проверка транслитерации
        variants1 = TextSimilarity.transliterate_variants(text1)
        variants2 = TextSimilarity.transliterate_variants(text2)

        for v1 in variants1:
            for v2 in variants2:
                lev_score = TextSimilarity.levenshtein_similarity(v1, v2)
                if lev_score >= threshold:
                    return True, lev_score, f"Схожесть с учетом транслитерации: {lev_score:.2f}"

        return False, lev_score, "Нет значительного сходства"


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
        """Проверка товарного знака через Linkmark"""
        result = TrademarkCheckResult(
            resource_name=self.resource_info["name"],
            resource_url=self.resource_info["url"],
            search_query=text,
            mktu_classes=mktu_classes or []
        )

        try:
            # POST запрос на поиск (без фильтрации по МКТУ - Linkmark не поддерживает)
            search_data = {"search": text}

            response = self.session.post(
                self.search_url,
                data=search_data,
                timeout=30,
                allow_redirects=True
            )

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                self._parse_linkmark_results(result, soup, text, mktu_classes)
            else:
                result.notes = f"Рекомендуется ручная проверка на {self.base_url}"
                result.status = RiskLevel.YELLOW

        except requests.exceptions.RequestException as e:
            result.notes = f"Ошибка подключения: {str(e)}"
            result.status = RiskLevel.YELLOW
        except Exception as e:
            result.notes = f"Требуется ручная проверка на {self.base_url}: {str(e)}"
            result.status = RiskLevel.YELLOW

        return result

    def _parse_linkmark_results(self, result: TrademarkCheckResult,
                                 soup: BeautifulSoup, search_text: str,
                                 mktu_filter: List[int] = None):
        """Парсинг результатов поиска Linkmark с фильтрацией по МКТУ"""

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

        # Ищем карточки товарных знаков
        # Ищем карточки товарных знаков
        items = soup.find_all('div', class_='result-div-item')

        # Счётчики для статистики
        matches_in_mktu = 0  # Совпадения в выбранных классах МКТУ
        high_similarity_count = 0  # Высокое сходство (>80%)

        for item in items[:30]:  # Обрабатываем первые 30
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

            # Проверяем схожесть по каждому слову в ТЗ
            compare_text = trademark_words if trademark_words else ""
            best_score = 0.0
            best_reason = "Найден в результатах поиска"

            # Разбиваем слова из ТЗ и проверяем каждое
            if compare_text:
                words_list = compare_text.split()
                for word in words_list:
                    is_similar, score, reason = TextSimilarity.check_similarity(
                        search_text, word, 0.7  # Понижен порог для отлова похожих
                    )
                    if score > best_score:
                        best_score = score
                        best_reason = reason

            # Также проверяем весь текст целиком
            if compare_text:
                is_similar, score, reason = TextSimilarity.check_similarity(
                    search_text, compare_text, 0.7
                )
                if score > best_score:
                    best_score = score
                    best_reason = reason

            # Определяем уровень совпадения
            is_exact = best_score >= 0.95
            is_high_similar = best_score >= 0.8
            is_similar = best_score >= 0.7

            # Добавляем только релевантные результаты
            if is_similar or (mktu_match and best_score >= 0.5):
                match_info = {
                    "text": trademark_words or f"ТЗ №{reg_number}",
                    "registration_number": reg_number,
                    "similarity_score": best_score,
                    "reason": best_reason,
                    "classes": tm_classes,
                    "status": tm_status,
                    "holder": holder[:100] if holder else "",
                    "mktu_match": mktu_match
                }

                # Приоритет: сначала совпадения по МКТУ, потом остальные
                if mktu_match and is_similar:
                    result.found_matches.insert(0, match_info)
                    matches_in_mktu += 1
                else:
                    result.found_matches.append(match_info)

                if is_exact:
                    result.exact_match = True
                elif is_high_similar:
                    result.similar_match = True
                    high_similarity_count += 1

                result.similarity_score = max(result.similarity_score, best_score)

                if reg_number:
                    result.registration_numbers.append(reg_number)

        # Ограничиваем количество результатов
        result.found_matches = result.found_matches[:10]

        # Определяем статус с учётом фильтра МКТУ
        self._set_status(result, total_marks, total_apps, matches_in_mktu, mktu_filter)

    def _set_status(self, result: TrademarkCheckResult, total_marks: int = 0,
                    total_apps: int = 0, matches_in_mktu: int = 0,
                    mktu_filter: List[int] = None):
        """Установка статуса на основе результатов"""

        mktu_info = f" (класс {', '.join(map(str, mktu_filter))})" if mktu_filter else ""

        if result.exact_match:
            result.status = RiskLevel.RED
            result.notes = f"Найден тождественный ТЗ{mktu_info}! Всего в базе: {total_marks} ТЗ"
        elif result.similar_match and matches_in_mktu > 0:
            result.status = RiskLevel.RED
            result.notes = f"Найдены похожие ТЗ в классе МКТУ{mktu_info}: {matches_in_mktu} совпадений"
        elif result.similar_match:
            result.status = RiskLevel.YELLOW
            result.notes = f"Найдены похожие ТЗ (всего {total_marks}), но не в выбранном классе{mktu_info}"
        elif matches_in_mktu > 0:
            result.status = RiskLevel.YELLOW
            result.notes = f"Найдено {matches_in_mktu} ТЗ в классе{mktu_info}. Требуется анализ."
        elif total_marks > 0 and not mktu_filter:
            result.status = RiskLevel.YELLOW
            result.notes = f"Найдено {total_marks} ТЗ с похожими названиями. Укажите класс МКТУ для точной проверки."
        elif total_marks > 0:
            result.status = RiskLevel.GREEN
            result.notes = f"В классе{mktu_info} совпадений не найдено. Всего в базе: {total_marks} похожих ТЗ."
        else:
            result.status = RiskLevel.GREEN
            result.notes = f"Совпадений в базе ТЗ РФ не найдено{mktu_info}"


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
            "linkmark": LinkmarkChecker(),
            "wipo": WIPOChecker()
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

        # Международные базы
        if check_international:
            wipo_result = self.checkers["wipo"].check_trademark(text, mktu_classes)
            results.append(wipo_result)

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

        # ФИПС
        links["ФИПС (реестр)"] = TRADEMARK_RESOURCES["fips"]["search_url"]
        links["ФИПС (бюллетени)"] = TRADEMARK_RESOURCES["fips"]["bulletins_url"]

        # Платформа Роспатента
        rospatent_url = TRADEMARK_RESOURCES["rospatent_platform"]["url"]
        if mktu_classes:
            params = {"q": text, "classes": ",".join(map(str, mktu_classes))}
        else:
            params = {"q": text}
        links["Платформа Роспатента"] = f"{rospatent_url}?{urllib.parse.urlencode(params)}"

        # Проверка ТЗ РФ (Linkmark)
        links["Проверка ТЗ РФ"] = f"{TRADEMARK_RESOURCES['linkmark']['url']}?search={urllib.parse.quote(text)}"

        # WIPO
        links["WIPO Global Brand"] = self.checkers["wipo"].get_manual_search_url(text)

        # EUIPO
        euipo_url = "https://euipo.europa.eu/eSearch/"
        links["EUIPO"] = f"{euipo_url}#basic/1+1+1+1/100+100+100+100/{urllib.parse.quote(text)}"

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
