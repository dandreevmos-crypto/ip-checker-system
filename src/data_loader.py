# -*- coding: utf-8 -*-
"""
Модуль загрузки данных из файлов и папок с изображениями
"""

import os
import re
import uuid
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Generator
from datetime import datetime
import pandas as pd
from PIL import Image
import hashlib

from config import APP_CONFIG, DATA_DIR, OUTPUT_DIR
from models import ProductItem, CheckSession, ImageSource


class DataLoader:
    """Класс для загрузки данных из различных источников"""

    def __init__(self):
        self.allowed_image_extensions = APP_CONFIG["allowed_extensions"]
        self.allowed_data_extensions = APP_CONFIG["allowed_data_extensions"]
        self.max_file_size = APP_CONFIG["max_file_size_mb"] * 1024 * 1024

    def load_from_excel(self, file_path: str) -> List[ProductItem]:
        """
        Загрузка данных из Excel файла
        Ожидаемые колонки: Артикул, Название, Описание, Категория, Классы МКТУ,
                          Путь к изображениям, Текст на товаре, Источник изображения
        """
        items = []
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        if file_path.suffix.lower() not in self.allowed_data_extensions:
            raise ValueError(f"Неподдерживаемый формат файла: {file_path.suffix}")

        try:
            if file_path.suffix.lower() == '.csv':
                df = pd.read_csv(file_path, encoding='utf-8')
            else:
                df = pd.read_excel(file_path)

            # Нормализация названий колонок
            df.columns = [self._normalize_column_name(col) for col in df.columns]

            for idx, row in df.iterrows():
                item = self._create_product_item_from_row(row, idx)
                if item:
                    items.append(item)

        except Exception as e:
            raise Exception(f"Ошибка при чтении файла {file_path}: {str(e)}")

        return items

    def _normalize_column_name(self, name: str) -> str:
        """Нормализация названия колонки"""
        name = str(name).lower().strip()
        mappings = {
            'артикул': 'article',
            'sku': 'article',
            'код': 'article',
            'название': 'name',
            'наименование': 'name',
            'product': 'name',
            'описание': 'description',
            'description': 'description',
            'категория': 'category',
            'category': 'category',
            'мкту': 'mktu_classes',
            'классы': 'mktu_classes',
            'classes': 'mktu_classes',
            'изображение': 'image_paths',
            'изображения': 'image_paths',
            'фото': 'image_paths',
            'image': 'image_paths',
            'images': 'image_paths',
            'текст': 'text_on_product',
            'надпись': 'text_on_product',
            'text': 'text_on_product',
            'логотип': 'logos_on_product',
            'logo': 'logos_on_product',
            'источник': 'image_source',
            'source': 'image_source',
            'поставщик': 'supplier_info',
            'supplier': 'supplier_info'
        }

        for key, value in mappings.items():
            if key in name:
                return value
        return name

    def _create_product_item_from_row(self, row: pd.Series, idx: int) -> Optional[ProductItem]:
        """Создание ProductItem из строки DataFrame"""
        try:
            # Артикул - обязательное поле
            article = str(row.get('article', row.get('артикул', f'AUTO_{idx}')))
            if pd.isna(article) or not article.strip():
                article = f'AUTO_{idx}'

            # Название
            name = str(row.get('name', row.get('название', '')))
            if pd.isna(name):
                name = ''

            # Описание
            description = str(row.get('description', ''))
            if pd.isna(description):
                description = ''

            # Категория
            category = str(row.get('category', ''))
            if pd.isna(category):
                category = ''

            # Классы МКТУ
            mktu_raw = row.get('mktu_classes', '')
            mktu_classes = self._parse_mktu_classes(mktu_raw)

            # Пути к изображениям
            image_paths_raw = row.get('image_paths', '')
            image_paths = self._parse_image_paths(image_paths_raw)

            # Текст на товаре
            text_raw = row.get('text_on_product', '')
            text_on_product = self._parse_list_field(text_raw)

            # Логотипы
            logos_raw = row.get('logos_on_product', '')
            logos_on_product = self._parse_list_field(logos_raw)

            # Источник изображения
            source_raw = str(row.get('image_source', 'unknown'))
            if pd.isna(source_raw):
                source_raw = 'unknown'
            image_source = ImageSource(source_type=source_raw)

            # Информация о поставщике
            supplier_info = str(row.get('supplier_info', ''))
            if pd.isna(supplier_info):
                supplier_info = ''

            return ProductItem(
                article=article.strip(),
                name=name.strip(),
                description=description.strip(),
                category=category.strip(),
                mktu_classes=mktu_classes,
                image_paths=image_paths,
                text_on_product=text_on_product,
                logos_on_product=logos_on_product,
                image_source=image_source,
                supplier_info=supplier_info.strip()
            )

        except Exception as e:
            print(f"Ошибка при обработке строки {idx}: {str(e)}")
            return None

    def _parse_mktu_classes(self, value) -> List[int]:
        """Парсинг классов МКТУ"""
        if pd.isna(value):
            return []

        value = str(value)
        # Извлекаем все числа
        numbers = re.findall(r'\d+', value)
        classes = []
        for num in numbers:
            try:
                n = int(num)
                if 1 <= n <= 45:  # Классы МКТУ от 1 до 45
                    classes.append(n)
            except ValueError:
                continue
        return sorted(list(set(classes)))

    def _parse_image_paths(self, value) -> List[str]:
        """Парсинг путей к изображениям"""
        if pd.isna(value):
            return []

        value = str(value)
        # Разделители: запятая, точка с запятой, новая строка
        paths = re.split(r'[,;\n]', value)
        result = []
        for path in paths:
            path = path.strip()
            if path and Path(path).suffix.lower() in self.allowed_image_extensions:
                result.append(path)
        return result

    def _parse_list_field(self, value) -> List[str]:
        """Парсинг поля со списком значений"""
        if pd.isna(value):
            return []

        value = str(value)
        items = re.split(r'[,;\n]', value)
        return [item.strip() for item in items if item.strip()]

    def load_images_from_folder(self, folder_path: str,
                                 article_pattern: Optional[str] = None) -> List[ProductItem]:
        """
        Загрузка изображений из папки

        Args:
            folder_path: Путь к папке с изображениями
            article_pattern: Паттерн для извлечения артикула из имени файла
                           Например: r'^(\w+)_' - артикул до первого подчеркивания
        """
        items = []
        folder = Path(folder_path)

        if not folder.exists():
            raise FileNotFoundError(f"Папка не найдена: {folder_path}")

        if not folder.is_dir():
            raise ValueError(f"Указанный путь не является папкой: {folder_path}")

        # Группируем изображения по артикулам
        article_images: Dict[str, List[str]] = {}

        for file_path in folder.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in self.allowed_image_extensions:
                # Проверка размера файла
                if file_path.stat().st_size > self.max_file_size:
                    print(f"Пропущен файл (слишком большой): {file_path}")
                    continue

                # Извлечение артикула
                if article_pattern:
                    match = re.search(article_pattern, file_path.stem)
                    article = match.group(1) if match else file_path.stem
                else:
                    # По умолчанию - имя файла без расширения
                    article = file_path.stem

                if article not in article_images:
                    article_images[article] = []
                article_images[article].append(str(file_path))

        # Создаем ProductItem для каждого артикула
        for article, images in article_images.items():
            item = ProductItem(
                article=article,
                name=f"Товар {article}",
                image_paths=images,
                image_source=ImageSource(source_type='unknown')
            )
            items.append(item)

        return items

    def load_single_image(self, image_path: str, article: str = None) -> ProductItem:
        """Загрузка одного изображения"""
        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {image_path}")

        if path.suffix.lower() not in self.allowed_image_extensions:
            raise ValueError(f"Неподдерживаемый формат изображения: {path.suffix}")

        if not article:
            article = path.stem

        return ProductItem(
            article=article,
            name=f"Товар {article}",
            image_paths=[str(path)],
            image_source=ImageSource(source_type='unknown')
        )

    def create_check_session(self, items: List[ProductItem]) -> CheckSession:
        """Создание сессии проверки"""
        session_id = str(uuid.uuid4())[:8].upper()
        session = CheckSession(
            session_id=session_id,
            items=items,
            total_items=len(items)
        )
        return session

    def get_image_hash(self, image_path: str) -> str:
        """Получение хеша изображения для дедупликации"""
        with open(image_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def validate_image(self, image_path: str) -> Tuple[bool, str]:
        """Валидация изображения"""
        try:
            path = Path(image_path)

            if not path.exists():
                return False, "Файл не найден"

            if path.suffix.lower() not in self.allowed_image_extensions:
                return False, "Неподдерживаемый формат"

            if path.stat().st_size > self.max_file_size:
                return False, "Файл слишком большой"

            # Проверка, что файл является изображением
            with Image.open(image_path) as img:
                img.verify()

            return True, "OK"

        except Exception as e:
            return False, str(e)


class TemplateGenerator:
    """Генератор шаблонов для загрузки данных"""

    @staticmethod
    def create_excel_template(output_path: str = None) -> str:
        """Создание шаблона Excel для заполнения"""
        if output_path is None:
            output_path = str(OUTPUT_DIR / "template_products.xlsx")

        template_data = {
            'Артикул': ['SKU001', 'SKU002', 'SKU003'],
            'Название': ['Пример товара 1', 'Пример товара 2', 'Пример товара 3'],
            'Описание': ['Описание товара 1', 'Описание товара 2', 'Описание товара 3'],
            'Категория': ['Одежда', 'Аксессуары', 'Электроника'],
            'Классы МКТУ': ['25', '18, 25', '9'],
            'Путь к изображениям': [
                '/path/to/image1.jpg',
                '/path/to/image2.jpg; /path/to/image2_2.jpg',
                '/path/to/image3.png'
            ],
            'Текст на товаре': ['BRAND', 'Premium Quality', 'Tech Pro'],
            'Логотипы': ['logo1.png', '', 'tech_logo.png'],
            'Источник изображения': ['internal_designer', 'stock_paid', 'unknown'],
            'Поставщик': ['ООО Поставщик 1', 'ООО Поставщик 2', 'ООО Поставщик 3']
        }

        df = pd.DataFrame(template_data)

        # Создаем Excel с форматированием
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Товары', index=False)

            # Добавляем лист с инструкцией
            instructions = pd.DataFrame({
                'Поле': [
                    'Артикул',
                    'Название',
                    'Описание',
                    'Категория',
                    'Классы МКТУ',
                    'Путь к изображениям',
                    'Текст на товаре',
                    'Логотипы',
                    'Источник изображения',
                    'Поставщик'
                ],
                'Описание': [
                    'Уникальный идентификатор товара (обязательно)',
                    'Название товара',
                    'Подробное описание товара',
                    'Категория товара',
                    'Классы МКТУ через запятую (1-45)',
                    'Пути к изображениям через точку с запятой',
                    'Текстовые надписи на товаре через запятую',
                    'Описание логотипов на товаре',
                    'internal_designer / contractor / ai / stock_free / stock_paid / unknown',
                    'Информация о поставщике'
                ]
            })
            instructions.to_excel(writer, sheet_name='Инструкция', index=False)

            # Добавляем лист с классами МКТУ
            from config import MKTU_CLASSES
            mktu_df = pd.DataFrame({
                'Класс': list(MKTU_CLASSES.keys()),
                'Описание': list(MKTU_CLASSES.values())
            })
            mktu_df.to_excel(writer, sheet_name='Классы МКТУ', index=False)

        return output_path


if __name__ == "__main__":
    # Пример использования
    loader = DataLoader()

    # Создание шаблона
    template_path = TemplateGenerator.create_excel_template()
    print(f"Шаблон создан: {template_path}")
