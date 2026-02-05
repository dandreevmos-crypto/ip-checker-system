# -*- coding: utf-8 -*-
"""
Модуль оценки рисков по принципу светофора
Красный - запрещено, Желтый - требует проверки, Зеленый - разрешено
"""

from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from models import (
    ProductItem, RiskLevel, TrademarkCheckResult,
    ImageSearchResult, CopyrightCheckResult, ImageSource
)
from config import IMAGE_SOURCES, TrafficLightStatus


@dataclass
class RiskFactor:
    """Фактор риска"""
    name: str
    category: str  # trademark, copyright, source, image
    severity: RiskLevel
    description: str
    weight: float = 1.0  # Вес фактора


@dataclass
class RiskAssessment:
    """Оценка риска для товарной позиции"""
    overall_status: RiskLevel
    overall_score: float  # 0-100, где 100 = максимальный риск
    factors: List[RiskFactor] = field(default_factory=list)
    summary: str = ""
    recommendations: List[str] = field(default_factory=list)
    requires_manual_check: bool = False
    manual_check_items: List[str] = field(default_factory=list)


class RiskEvaluator:
    """
    Класс для оценки рисков использования изображений и обозначений
    по принципу светофора
    """

    # Веса различных категорий проверок
    CATEGORY_WEIGHTS = {
        "trademark": 1.5,      # Товарные знаки - высший приоритет
        "copyright": 1.3,      # Авторские права
        "source": 1.2,         # Источник изображения
        "image_search": 1.0,   # Поиск изображений
        "text_on_image": 0.8   # Текст на изображении
    }

    # Пороги для определения статуса
    RED_THRESHOLD = 70       # 70+ баллов = красный
    YELLOW_THRESHOLD = 30    # 30-69 баллов = желтый

    def __init__(self):
        self.status_labels = TrafficLightStatus.LABELS
        self.status_descriptions = TrafficLightStatus.DESCRIPTIONS

    def evaluate_product(self, product: ProductItem) -> RiskAssessment:
        """
        Полная оценка риска для товарной позиции

        Args:
            product: Товарная позиция со всеми результатами проверок

        Returns:
            RiskAssessment с итоговой оценкой
        """
        assessment = RiskAssessment(
            overall_status=RiskLevel.GREEN,
            overall_score=0
        )

        # 1. Оценка источника изображения
        source_factors = self._evaluate_image_source(product.image_source)
        assessment.factors.extend(source_factors)

        # 2. Оценка результатов проверки товарных знаков
        tm_factors = self._evaluate_trademark_results(product.trademark_results)
        assessment.factors.extend(tm_factors)

        # 3. Оценка результатов поиска изображений
        img_factors = self._evaluate_image_search_results(product.image_search_results)
        assessment.factors.extend(img_factors)

        # 4. Оценка результатов проверки авторских прав
        cr_factors = self._evaluate_copyright_results(product.copyright_results)
        assessment.factors.extend(cr_factors)

        # 5. Оценка распознанного текста
        text_factors = self._evaluate_recognized_texts(
            product.recognized_texts,
            product.text_on_product,
            product.logos_on_product
        )
        assessment.factors.extend(text_factors)

        # 6. Расчет итогового балла и статуса
        assessment.overall_score = self._calculate_overall_score(assessment.factors)
        assessment.overall_status = self._determine_status(assessment.overall_score)

        # 7. Формирование рекомендаций
        assessment.summary = self._generate_summary(assessment)
        assessment.recommendations = self._generate_recommendations(assessment)

        # 8. Определение необходимости ручной проверки
        assessment.requires_manual_check = self._check_manual_review_needed(assessment)
        assessment.manual_check_items = self._get_manual_check_items(assessment)

        return assessment

    def _evaluate_image_source(self, source: ImageSource) -> List[RiskFactor]:
        """Оценка источника изображения"""
        factors = []

        if source is None:
            factors.append(RiskFactor(
                name="Источник неизвестен",
                category="source",
                severity=RiskLevel.RED,
                description="Информация об источнике изображения отсутствует",
                weight=1.5
            ))
            return factors

        source_config = IMAGE_SOURCES.get(source.source_type, IMAGE_SOURCES["unknown"])

        # Оценка по типу источника
        if source_config["risk_level"] == "high":
            factors.append(RiskFactor(
                name=f"Источник: {source_config['name']}",
                category="source",
                severity=RiskLevel.RED,
                description="Источник изображения представляет высокий риск",
                weight=1.5
            ))
        elif source_config["risk_level"] == "medium":
            factors.append(RiskFactor(
                name=f"Источник: {source_config['name']}",
                category="source",
                severity=RiskLevel.YELLOW,
                description="Источник изображения требует проверки документов",
                weight=1.0
            ))
        else:
            factors.append(RiskFactor(
                name=f"Источник: {source_config['name']}",
                category="source",
                severity=RiskLevel.GREEN,
                description="Источник изображения низкого риска",
                weight=0.5
            ))

        # Проверка наличия документов
        if source_config["risk_level"] != "low":
            required_docs = source_config.get("documents_required", [])

            if not source.has_contract and "Договор" in str(required_docs):
                factors.append(RiskFactor(
                    name="Отсутствует договор",
                    category="source",
                    severity=RiskLevel.YELLOW,
                    description="Договор на права использования не предоставлен",
                    weight=1.2
                ))

            if not source.has_license and "Лицензия" in str(required_docs):
                factors.append(RiskFactor(
                    name="Отсутствует лицензия",
                    category="source",
                    severity=RiskLevel.YELLOW,
                    description="Лицензионное соглашение не предоставлено",
                    weight=1.0
                ))

        return factors

    def _evaluate_trademark_results(self, results: List[TrademarkCheckResult]) -> List[RiskFactor]:
        """Оценка результатов проверки товарных знаков"""
        factors = []

        if not results:
            factors.append(RiskFactor(
                name="Проверка ТЗ не проведена",
                category="trademark",
                severity=RiskLevel.YELLOW,
                description="Рекомендуется провести проверку по базам товарных знаков",
                weight=0.8
            ))
            return factors

        for result in results:
            if result.exact_match:
                factors.append(RiskFactor(
                    name=f"Точное совпадение ТЗ ({result.resource_name})",
                    category="trademark",
                    severity=RiskLevel.RED,
                    description=f"Найден тождественный товарный знак: {result.notes}",
                    weight=2.0
                ))
            elif result.similar_match and result.similarity_score >= 0.9:
                factors.append(RiskFactor(
                    name=f"Высокое сходство ТЗ ({result.resource_name})",
                    category="trademark",
                    severity=RiskLevel.RED,
                    description=f"Сходство до степени смешения: {result.similarity_score:.0%}",
                    weight=1.8
                ))
            elif result.similar_match:
                factors.append(RiskFactor(
                    name=f"Частичное сходство ТЗ ({result.resource_name})",
                    category="trademark",
                    severity=RiskLevel.YELLOW,
                    description=f"Обнаружено сходство: {result.similarity_score:.0%}",
                    weight=1.0
                ))
            else:
                factors.append(RiskFactor(
                    name=f"Проверка ТЗ пройдена ({result.resource_name})",
                    category="trademark",
                    severity=RiskLevel.GREEN,
                    description="Совпадений не найдено",
                    weight=0.3
                ))

        return factors

    def _evaluate_image_search_results(self, results: List[ImageSearchResult]) -> List[RiskFactor]:
        """Оценка результатов поиска изображений"""
        factors = []

        if not results:
            factors.append(RiskFactor(
                name="Поиск изображений не проведен",
                category="image_search",
                severity=RiskLevel.YELLOW,
                description="Рекомендуется провести обратный поиск изображения",
                weight=0.7
            ))
            return factors

        total_matches = sum(r.total_results for r in results)
        exact_matches = sum(r.exact_matches for r in results)

        if exact_matches > 0:
            factors.append(RiskFactor(
                name="Найдены точные копии",
                category="image_search",
                severity=RiskLevel.RED,
                description=f"Обнаружено {exact_matches} точных совпадений изображения",
                weight=1.8
            ))
        elif total_matches > 10:
            factors.append(RiskFactor(
                name="Множество совпадений",
                category="image_search",
                severity=RiskLevel.YELLOW,
                description=f"Найдено {total_matches} похожих изображений",
                weight=1.0
            ))
        elif total_matches > 0:
            factors.append(RiskFactor(
                name="Найдены похожие изображения",
                category="image_search",
                severity=RiskLevel.YELLOW,
                description=f"Найдено {total_matches} похожих изображений",
                weight=0.7
            ))

        # Проверка потенциальных авторов
        authors = []
        for r in results:
            authors.extend(r.potential_authors)

        if authors:
            factors.append(RiskFactor(
                name="Обнаружены потенциальные авторы",
                category="image_search",
                severity=RiskLevel.YELLOW,
                description=f"Возможные авторы: {', '.join(set(authors)[:3])}",
                weight=1.2
            ))

        return factors

    def _evaluate_copyright_results(self, results: List[CopyrightCheckResult]) -> List[RiskFactor]:
        """Оценка результатов проверки авторских прав"""
        factors = []

        if not results:
            return factors

        for result in results:
            if result.contains_characters:
                factors.append(RiskFactor(
                    name="Обнаружены известные персонажи",
                    category="copyright",
                    severity=RiskLevel.RED,
                    description=f"Персонажи: {', '.join(result.character_names[:3])}",
                    weight=2.0
                ))

            if result.brand_elements:
                factors.append(RiskFactor(
                    name="Обнаружены элементы брендов",
                    category="copyright",
                    severity=RiskLevel.RED,
                    description=f"Бренды: {', '.join(result.brand_elements[:3])}",
                    weight=2.0
                ))

            if result.contains_known_works:
                factors.append(RiskFactor(
                    name="Элементы известных произведений",
                    category="copyright",
                    severity=RiskLevel.RED,
                    description=f"Произведения: {', '.join(result.known_work_references[:3])}",
                    weight=1.8
                ))

            if result.contains_people_photos:
                factors.append(RiskFactor(
                    name="Фотографии людей",
                    category="copyright",
                    severity=RiskLevel.YELLOW,
                    description="Требуется согласие на использование изображения",
                    weight=1.0
                ))

        return factors

    def _evaluate_recognized_texts(self, recognized_texts,
                                     text_on_product: List[str],
                                     logos_on_product: List[str]) -> List[RiskFactor]:
        """Оценка текста на изображении"""
        factors = []

        all_texts = []
        if recognized_texts:
            all_texts.extend([t.text for t in recognized_texts])
        if text_on_product:
            all_texts.extend(text_on_product)

        if all_texts:
            factors.append(RiskFactor(
                name="Текст на изображении",
                category="text_on_image",
                severity=RiskLevel.YELLOW,
                description=f"Обнаружен текст: {', '.join(all_texts[:3])}...",
                weight=0.8
            ))

        if logos_on_product:
            factors.append(RiskFactor(
                name="Логотипы на товаре",
                category="text_on_image",
                severity=RiskLevel.YELLOW,
                description=f"Логотипы: {', '.join(logos_on_product[:3])}",
                weight=1.0
            ))

        return factors

    def _calculate_overall_score(self, factors: List[RiskFactor]) -> float:
        """Расчет итогового балла риска"""
        if not factors:
            return 0

        total_score = 0
        total_weight = 0

        for factor in factors:
            category_weight = self.CATEGORY_WEIGHTS.get(factor.category, 1.0)
            factor_weight = factor.weight * category_weight

            if factor.severity == RiskLevel.RED:
                score = 100
            elif factor.severity == RiskLevel.YELLOW:
                score = 50
            else:
                score = 0

            total_score += score * factor_weight
            total_weight += factor_weight

        if total_weight == 0:
            return 0

        return min(100, total_score / total_weight)

    def _determine_status(self, score: float) -> RiskLevel:
        """Определение статуса по баллу"""
        # Если есть хотя бы один критический фактор - красный
        if score >= self.RED_THRESHOLD:
            return RiskLevel.RED
        elif score >= self.YELLOW_THRESHOLD:
            return RiskLevel.YELLOW
        else:
            return RiskLevel.GREEN

    def _generate_summary(self, assessment: RiskAssessment) -> str:
        """Генерация краткого описания"""
        status_label = self.status_labels.get(assessment.overall_status.value, "Неизвестно")

        red_count = sum(1 for f in assessment.factors if f.severity == RiskLevel.RED)
        yellow_count = sum(1 for f in assessment.factors if f.severity == RiskLevel.YELLOW)

        summary = f"Статус: {status_label}. "
        summary += f"Оценка риска: {assessment.overall_score:.0f}/100. "

        if red_count > 0:
            summary += f"Критических факторов: {red_count}. "
        if yellow_count > 0:
            summary += f"Требуют внимания: {yellow_count}."

        return summary

    def _generate_recommendations(self, assessment: RiskAssessment) -> List[str]:
        """Генерация рекомендаций"""
        recommendations = []

        if assessment.overall_status == RiskLevel.RED:
            recommendations.append(
                "ЗАПРЕЩЕНО: Использование данного изображения/обозначения "
                "не рекомендуется из-за высокого риска претензий третьих лиц."
            )

            # Добавляем конкретные рекомендации по красным факторам
            for factor in assessment.factors:
                if factor.severity == RiskLevel.RED:
                    if factor.category == "trademark":
                        recommendations.append(
                            "Обратитесь к юристу для оценки возможности использования "
                            "или выберите альтернативное обозначение."
                        )
                    elif factor.category == "copyright":
                        recommendations.append(
                            "Необходимо получить разрешение правообладателя или "
                            "заменить изображение на оригинальное."
                        )
                    elif factor.category == "source":
                        recommendations.append(
                            "Запросите документы, подтверждающие права на использование."
                        )

        elif assessment.overall_status == RiskLevel.YELLOW:
            recommendations.append(
                "ВНИМАНИЕ: Требуется дополнительная проверка перед использованием."
            )

            for factor in assessment.factors:
                if factor.severity == RiskLevel.YELLOW:
                    if factor.category == "trademark":
                        recommendations.append(
                            "Проведите ручную проверку по базам товарных знаков."
                        )
                    elif factor.category == "source":
                        recommendations.append(
                            "Запросите документы на права использования изображения."
                        )
                    elif factor.category == "image_search":
                        recommendations.append(
                            "Проверьте источники найденных похожих изображений."
                        )

        else:
            recommendations.append(
                "РАЗРЕШЕНО: Автоматическая проверка не выявила явных рисков. "
                "Рекомендуется сохранить подтверждающие документы."
            )

        return list(set(recommendations))  # Убираем дубликаты

    def _check_manual_review_needed(self, assessment: RiskAssessment) -> bool:
        """Проверка необходимости ручной проверки"""
        return assessment.overall_status in [RiskLevel.RED, RiskLevel.YELLOW]

    def _get_manual_check_items(self, assessment: RiskAssessment) -> List[str]:
        """Получение списка пунктов для ручной проверки"""
        items = []

        for factor in assessment.factors:
            if factor.severity in [RiskLevel.RED, RiskLevel.YELLOW]:
                if factor.category == "trademark":
                    items.append("Проверка по базам товарных знаков (ФИПС, WIPO)")
                elif factor.category == "copyright":
                    items.append("Проверка авторских прав и лицензий")
                elif factor.category == "source":
                    items.append("Запрос документов у поставщика")
                elif factor.category == "image_search":
                    items.append("Ручной поиск изображения в интернете")

        return list(set(items))  # Убираем дубликаты


class TrafficLightReportGenerator:
    """Генератор отчетов с визуализацией по принципу светофора"""

    STATUS_COLORS = {
        RiskLevel.RED: "#FF4444",
        RiskLevel.YELLOW: "#FFBB33",
        RiskLevel.GREEN: "#00C851"
    }

    STATUS_ICONS = {
        RiskLevel.RED: "🔴",
        RiskLevel.YELLOW: "🟡",
        RiskLevel.GREEN: "🟢"
    }

    @staticmethod
    def get_status_display(status: RiskLevel) -> Dict[str, str]:
        """Получение данных для отображения статуса"""
        return {
            "status": status.value,
            "color": TrafficLightReportGenerator.STATUS_COLORS[status],
            "icon": TrafficLightReportGenerator.STATUS_ICONS[status],
            "label": TrafficLightStatus.LABELS.get(status.value, "Неизвестно"),
            "descriptions": TrafficLightStatus.DESCRIPTIONS.get(status.value, [])
        }

    @staticmethod
    def format_assessment_for_export(assessment: RiskAssessment,
                                       product: ProductItem) -> Dict[str, Any]:
        """Форматирование оценки для экспорта"""
        status_display = TrafficLightReportGenerator.get_status_display(assessment.overall_status)

        return {
            "article": product.article,
            "name": product.name,
            "status": status_display["label"],
            "status_icon": status_display["icon"],
            "status_color": status_display["color"],
            "risk_score": round(assessment.overall_score, 1),
            "summary": assessment.summary,
            "factors_count": {
                "red": sum(1 for f in assessment.factors if f.severity == RiskLevel.RED),
                "yellow": sum(1 for f in assessment.factors if f.severity == RiskLevel.YELLOW),
                "green": sum(1 for f in assessment.factors if f.severity == RiskLevel.GREEN)
            },
            "factors_details": [
                {
                    "name": f.name,
                    "category": f.category,
                    "severity": f.severity.value,
                    "description": f.description
                }
                for f in assessment.factors
            ],
            "recommendations": assessment.recommendations,
            "requires_manual_check": assessment.requires_manual_check,
            "manual_check_items": assessment.manual_check_items,
            "checked_at": datetime.now().isoformat()
        }


if __name__ == "__main__":
    # Пример использования
    evaluator = RiskEvaluator()

    # Тестовый продукт
    test_product = ProductItem(
        article="TEST001",
        name="Тестовый товар",
        image_source=ImageSource(source_type="unknown")
    )

    assessment = evaluator.evaluate_product(test_product)

    print(f"Статус: {assessment.overall_status.value}")
    print(f"Оценка: {assessment.overall_score:.1f}/100")
    print(f"Сводка: {assessment.summary}")
    print("\nРекомендации:")
    for rec in assessment.recommendations:
        print(f"  - {rec}")
