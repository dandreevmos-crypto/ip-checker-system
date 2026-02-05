# -*- coding: utf-8 -*-
"""
Модели данных для системы проверки ИС
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
from enum import Enum


class RiskLevel(Enum):
    """Уровни риска по принципу светофора"""
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"


class CheckType(Enum):
    """Типы проверок"""
    TRADEMARK = "trademark"
    COPYRIGHT = "copyright"
    IMAGE_SEARCH = "image_search"
    TEXT_RECOGNITION = "text_recognition"
    SOURCE_VERIFICATION = "source_verification"


@dataclass
class ImageSource:
    """Информация об источнике изображения"""
    source_type: str  # internal_designer, contractor, ai, stock_free, stock_paid, unknown
    creator_name: Optional[str] = None
    has_contract: bool = False
    has_license: bool = False
    has_certificate: bool = False
    documents: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class TrademarkCheckResult:
    """Результат проверки товарного знака"""
    resource_name: str
    resource_url: str
    search_query: str
    found_matches: List[Dict[str, Any]] = field(default_factory=list)
    exact_match: bool = False
    similar_match: bool = False
    similarity_score: float = 0.0
    registration_numbers: List[str] = field(default_factory=list)
    mktu_classes: List[int] = field(default_factory=list)
    status: RiskLevel = RiskLevel.GREEN
    notes: str = ""
    checked_at: datetime = field(default_factory=datetime.now)


@dataclass
class ImageSearchResult:
    """Результат обратного поиска изображения"""
    resource_name: str
    resource_url: str
    total_results: int = 0
    similar_images: List[Dict[str, Any]] = field(default_factory=list)
    exact_matches: int = 0
    potential_authors: List[str] = field(default_factory=list)
    known_sources: List[str] = field(default_factory=list)
    status: RiskLevel = RiskLevel.GREEN
    notes: str = ""
    checked_at: datetime = field(default_factory=datetime.now)


@dataclass
class TextOnImage:
    """Текст, распознанный на изображении"""
    text: str
    confidence: float
    position: Dict[str, int] = field(default_factory=dict)  # x, y, width, height
    language: str = "unknown"


@dataclass
class CopyrightCheckResult:
    """Результат проверки авторских прав"""
    contains_characters: bool = False
    character_names: List[str] = field(default_factory=list)
    contains_known_works: bool = False
    known_work_references: List[str] = field(default_factory=list)
    contains_people_photos: bool = False
    brand_elements: List[str] = field(default_factory=list)
    status: RiskLevel = RiskLevel.GREEN
    notes: str = ""


@dataclass
class ProductItem:
    """Товарная позиция для проверки"""
    article: str  # Артикул товара
    name: str  # Название товара
    description: str = ""
    category: str = ""
    mktu_classes: List[int] = field(default_factory=list)
    image_paths: List[str] = field(default_factory=list)
    text_on_product: List[str] = field(default_factory=list)
    logos_on_product: List[str] = field(default_factory=list)
    image_source: Optional[ImageSource] = None
    supplier_info: str = ""

    # Результаты проверок
    trademark_results: List[TrademarkCheckResult] = field(default_factory=list)
    image_search_results: List[ImageSearchResult] = field(default_factory=list)
    copyright_results: List[CopyrightCheckResult] = field(default_factory=list)
    recognized_texts: List[TextOnImage] = field(default_factory=list)

    # Итоговый статус
    overall_status: RiskLevel = RiskLevel.GREEN
    status_reason: str = ""
    recommendations: List[str] = field(default_factory=list)

    # Метаданные
    created_at: datetime = field(default_factory=datetime.now)
    checked_at: Optional[datetime] = None
    checked_by: str = ""


@dataclass
class CheckSession:
    """Сессия проверки (пакетная проверка)"""
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)
    items: List[ProductItem] = field(default_factory=list)
    total_items: int = 0
    checked_items: int = 0
    red_count: int = 0
    yellow_count: int = 0
    green_count: int = 0
    status: str = "pending"  # pending, in_progress, completed, error
    error_message: str = ""

    def update_statistics(self):
        """Обновление статистики сессии"""
        self.total_items = len(self.items)
        self.checked_items = sum(1 for item in self.items if item.checked_at is not None)
        self.red_count = sum(1 for item in self.items if item.overall_status == RiskLevel.RED)
        self.yellow_count = sum(1 for item in self.items if item.overall_status == RiskLevel.YELLOW)
        self.green_count = sum(1 for item in self.items if item.overall_status == RiskLevel.GREEN)


@dataclass
class CheckReport:
    """Отчет о проверке"""
    session: CheckSession
    generated_at: datetime = field(default_factory=datetime.now)
    summary: Dict[str, Any] = field(default_factory=dict)
    detailed_results: List[Dict[str, Any]] = field(default_factory=list)

    def generate_summary(self):
        """Генерация сводки отчета"""
        self.session.update_statistics()
        self.summary = {
            "total_items": self.session.total_items,
            "checked_items": self.session.checked_items,
            "statistics": {
                "red": {
                    "count": self.session.red_count,
                    "percentage": round(self.session.red_count / max(self.session.total_items, 1) * 100, 1),
                    "label": "Запрещено к использованию"
                },
                "yellow": {
                    "count": self.session.yellow_count,
                    "percentage": round(self.session.yellow_count / max(self.session.total_items, 1) * 100, 1),
                    "label": "Требуется дополнительная проверка"
                },
                "green": {
                    "count": self.session.green_count,
                    "percentage": round(self.session.green_count / max(self.session.total_items, 1) * 100, 1),
                    "label": "Разрешено к использованию"
                }
            },
            "session_id": self.session.session_id,
            "check_date": self.session.created_at.isoformat()
        }
