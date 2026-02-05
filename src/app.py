# -*- coding: utf-8 -*-
"""
Веб-приложение для проверки интеллектуальной собственности
Flask-based веб-интерфейс для менеджеров
"""

import os
import sys
import uuid
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Добавляем путь к src
sys.path.insert(0, str(Path(__file__).parent))

from config import APP_CONFIG, DATA_DIR, OUTPUT_DIR, TRADEMARK_RESOURCES, IMAGE_SEARCH_RESOURCES, MKTU_CLASSES
from models import ProductItem, CheckSession, ImageSource, RiskLevel
from data_loader import DataLoader, TemplateGenerator
from trademark_checker import ComprehensiveTrademarkChecker
from image_checker import ComprehensiveImageChecker
from risk_evaluator import RiskEvaluator, RiskAssessment
from export_manager import ExportManager

# Инициализация Flask
app = Flask(__name__,
            template_folder=str(Path(__file__).parent.parent / 'templates'),
            static_folder=str(Path(__file__).parent.parent / 'static'))
app.config['SECRET_KEY'] = os.urandom(24).hex()
app.config['MAX_CONTENT_LENGTH'] = APP_CONFIG['max_file_size_mb'] * 1024 * 1024
app.config['UPLOAD_FOLDER'] = str(DATA_DIR / 'uploads')
CORS(app)

# Создаем папку для загрузок
Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)

# Инициализация компонентов
data_loader = DataLoader()
trademark_checker = ComprehensiveTrademarkChecker()
image_checker = ComprehensiveImageChecker()
risk_evaluator = RiskEvaluator()
export_manager = ExportManager()

# Хранилище сессий (в production использовать БД)
sessions_store: Dict[str, Dict] = {}


def allowed_file(filename: str, allowed_extensions: set) -> bool:
    """Проверка допустимости расширения файла"""
    return '.' in filename and \
           '.' + filename.rsplit('.', 1)[1].lower() in allowed_extensions


@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html',
                          mktu_classes=MKTU_CLASSES,
                          trademark_resources=TRADEMARK_RESOURCES,
                          image_resources=IMAGE_SEARCH_RESOURCES)


@app.route('/api/upload/excel', methods=['POST'])
def upload_excel():
    """Загрузка Excel/CSV файла с товарами"""
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не найден'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400

    if not allowed_file(file.filename, APP_CONFIG['allowed_data_extensions']):
        return jsonify({'error': 'Неподдерживаемый формат файла'}), 400

    try:
        # Сохраняем файл
        filename = secure_filename(file.filename)
        filepath = Path(app.config['UPLOAD_FOLDER']) / filename
        file.save(filepath)

        # Загружаем данные
        items = data_loader.load_from_excel(str(filepath))

        # Создаем сессию
        session = data_loader.create_check_session(items)

        # Сохраняем в хранилище
        sessions_store[session.session_id] = {
            'session': session,
            'assessments': {},
            'created_at': datetime.now().isoformat()
        }

        return jsonify({
            'success': True,
            'session_id': session.session_id,
            'total_items': len(items),
            'items': [
                {
                    'article': item.article,
                    'name': item.name,
                    'category': item.category,
                    'mktu_classes': item.mktu_classes,
                    'image_count': len(item.image_paths),
                    'text_on_product': item.text_on_product,
                    'source_type': item.image_source.source_type if item.image_source else 'unknown'
                }
                for item in items
            ]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/upload/images', methods=['POST'])
def upload_images():
    """Загрузка изображений из папки или отдельных файлов"""
    if 'files' not in request.files:
        return jsonify({'error': 'Файлы не найдены'}), 400

    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'Файлы не выбраны'}), 400

    try:
        items = []
        upload_dir = Path(app.config['UPLOAD_FOLDER']) / str(uuid.uuid4())[:8]
        upload_dir.mkdir(parents=True, exist_ok=True)

        for file in files:
            if file and allowed_file(file.filename, APP_CONFIG['allowed_extensions']):
                filename = secure_filename(file.filename)
                filepath = upload_dir / filename
                file.save(filepath)

                # Создаем ProductItem для каждого изображения
                article = Path(filename).stem
                item = ProductItem(
                    article=article,
                    name=f"Товар {article}",
                    image_paths=[str(filepath)],
                    image_source=ImageSource(source_type='unknown')
                )
                items.append(item)

        if not items:
            return jsonify({'error': 'Нет допустимых изображений'}), 400

        # Создаем сессию
        session = data_loader.create_check_session(items)

        sessions_store[session.session_id] = {
            'session': session,
            'assessments': {},
            'created_at': datetime.now().isoformat()
        }

        return jsonify({
            'success': True,
            'session_id': session.session_id,
            'total_items': len(items),
            'items': [
                {
                    'article': item.article,
                    'name': item.name,
                    'image_path': item.image_paths[0] if item.image_paths else None
                }
                for item in items
            ]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/check/single', methods=['POST'])
def check_single():
    """Проверка одного товара"""
    data = request.json

    if not data:
        return jsonify({'error': 'Данные не предоставлены'}), 400

    try:
        article = data.get('article', 'MANUAL_' + str(uuid.uuid4())[:8])
        text_to_check = data.get('text', '')
        mktu_classes = data.get('mktu_classes', [])
        image_path = data.get('image_path')

        results = {
            'article': article,
            'trademark_results': [],
            'image_results': None,
            'overall_status': 'green',
            'recommendations': [],
            'manual_check_links': {}
        }

        # Проверка товарных знаков
        if text_to_check:
            tm_results = trademark_checker.check_all(text_to_check, mktu_classes)
            results['trademark_results'] = [
                {
                    'resource': r.resource_name,
                    'status': r.status.value,
                    'exact_match': r.exact_match,
                    'similar_match': r.similar_match,
                    'similarity_score': r.similarity_score,
                    'notes': r.notes,
                    'matches': r.found_matches[:5]  # Первые 5 совпадений
                }
                for r in tm_results
            ]

            # Ссылки для ручной проверки
            results['manual_check_links'] = trademark_checker.generate_manual_check_links(
                text_to_check, mktu_classes
            )

        # Проверка изображения
        if image_path and os.path.exists(image_path):
            img_results = image_checker.check_image(image_path)
            results['image_results'] = {
                'recognized_texts': [
                    {'text': t.text, 'confidence': t.confidence}
                    for t in img_results.get('recognized_texts', [])
                ],
                'overall_status': img_results.get('overall_status', RiskLevel.GREEN).value,
                'recommendations': img_results.get('recommendations', [])
            }

            # Добавляем ссылки для поиска изображений
            results['manual_check_links'].update(
                img_results.get('manual_check_links', {})
            )

        # Определяем общий статус
        has_red = any(r['status'] == 'red' for r in results['trademark_results'])
        has_yellow = any(r['status'] == 'yellow' for r in results['trademark_results'])

        if results.get('image_results'):
            if results['image_results']['overall_status'] == 'red':
                has_red = True
            elif results['image_results']['overall_status'] == 'yellow':
                has_yellow = True

        if has_red:
            results['overall_status'] = 'red'
        elif has_yellow:
            results['overall_status'] = 'yellow'

        return jsonify(results)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/check/session/<session_id>', methods=['POST'])
def check_session(session_id):
    """Запуск проверки для всей сессии"""
    if session_id not in sessions_store:
        return jsonify({'error': 'Сессия не найдена'}), 404

    try:
        session_data = sessions_store[session_id]
        session = session_data['session']
        assessments = {}

        for item in session.items:
            # Проверка товарных знаков для текста на товаре
            all_texts = item.text_on_product + item.logos_on_product
            for text in all_texts:
                if text:
                    tm_results = trademark_checker.check_all(text, item.mktu_classes)
                    item.trademark_results.extend(tm_results)

            # Проверка изображений
            for image_path in item.image_paths:
                if os.path.exists(image_path):
                    img_check = image_checker.check_image(image_path)

                    # Добавляем распознанный текст
                    item.recognized_texts.extend(img_check.get('recognized_texts', []))

                    # Проверяем распознанный текст на товарные знаки
                    for text_item in img_check.get('recognized_texts', []):
                        if text_item.text and len(text_item.text) > 2:
                            tm_results = trademark_checker.check_all(
                                text_item.text, item.mktu_classes
                            )
                            item.trademark_results.extend(tm_results)

                    # Результаты поиска изображений
                    item.image_search_results.extend(img_check.get('search_results', []))

                    # Результаты проверки авторских прав
                    if img_check.get('copyright_result'):
                        item.copyright_results.append(img_check['copyright_result'])

            # Оценка риска
            assessment = risk_evaluator.evaluate_product(item)
            assessments[item.article] = assessment

            # Обновляем статус товара
            item.overall_status = assessment.overall_status
            item.status_reason = assessment.summary
            item.recommendations = assessment.recommendations
            item.checked_at = datetime.now()

        # Сохраняем результаты
        session_data['assessments'] = assessments
        session.update_statistics()

        return jsonify({
            'success': True,
            'session_id': session_id,
            'statistics': {
                'total': session.total_items,
                'checked': session.checked_items,
                'red': session.red_count,
                'yellow': session.yellow_count,
                'green': session.green_count
            },
            'results': [
                {
                    'article': item.article,
                    'name': item.name,
                    'status': item.overall_status.value,
                    'risk_score': assessments[item.article].overall_score if item.article in assessments else 0,
                    'summary': item.status_reason,
                    'recommendations': item.recommendations[:3]
                }
                for item in session.items
            ]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/session/<session_id>')
def get_session(session_id):
    """Получение информации о сессии"""
    if session_id not in sessions_store:
        return jsonify({'error': 'Сессия не найдена'}), 404

    session_data = sessions_store[session_id]
    session = session_data['session']
    assessments = session_data.get('assessments', {})

    return jsonify({
        'session_id': session.session_id,
        'created_at': session.created_at.isoformat(),
        'statistics': {
            'total': session.total_items,
            'red': session.red_count,
            'yellow': session.yellow_count,
            'green': session.green_count
        },
        'items': [
            {
                'article': item.article,
                'name': item.name,
                'status': item.overall_status.value,
                'risk_score': assessments[item.article].overall_score if item.article in assessments else 0,
                'checked': item.checked_at is not None
            }
            for item in session.items
        ]
    })


@app.route('/api/export/<session_id>/<format>')
def export_results(session_id, format):
    """Экспорт результатов"""
    if session_id not in sessions_store:
        return jsonify({'error': 'Сессия не найдена'}), 404

    session_data = sessions_store[session_id]
    session = session_data['session']
    assessments = session_data.get('assessments', {})

    try:
        if format == 'excel':
            filepath = export_manager.export_to_excel(session, assessments)
            return send_file(filepath, as_attachment=True)
        elif format == 'csv':
            filepath = export_manager.export_to_csv(session, assessments)
            return send_file(filepath, as_attachment=True)
        elif format == 'json':
            filepath = export_manager.export_to_json(session, assessments)
            return send_file(filepath, as_attachment=True)
        elif format == 'html':
            filepath = export_manager.export_to_html(session, assessments)
            return send_file(filepath, as_attachment=True)
        else:
            return jsonify({'error': 'Неподдерживаемый формат'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/template')
def download_template():
    """Скачивание шаблона Excel"""
    try:
        filepath = TemplateGenerator.create_excel_template()
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/resources')
def get_resources():
    """Получение списка ресурсов для проверки"""
    return jsonify({
        'trademark_resources': TRADEMARK_RESOURCES,
        'image_resources': IMAGE_SEARCH_RESOURCES,
        'mktu_classes': MKTU_CLASSES
    })


@app.route('/api/check/links', methods=['POST'])
def get_check_links():
    """Получение ссылок для ручной проверки"""
    data = request.json
    text = data.get('text', '')
    mktu_classes = data.get('mktu_classes', [])

    links = trademark_checker.generate_manual_check_links(text, mktu_classes)

    return jsonify({
        'text': text,
        'links': links
    })


@app.route('/api/check/image', methods=['POST'])
def check_image_full():
    """
    Полная проверка изображения:
    1. Загрузка изображения
    2. Распознавание текста (OCR)
    3. Поиск по товарным знакам
    4. Генерация ссылок для обратного поиска
    """
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не найден'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400

    if not allowed_file(file.filename, APP_CONFIG['allowed_extensions']):
        return jsonify({'error': 'Неподдерживаемый формат файла'}), 400

    try:
        # Сохраняем файл
        upload_dir = Path(app.config['UPLOAD_FOLDER']) / str(uuid.uuid4())[:8]
        upload_dir.mkdir(parents=True, exist_ok=True)

        from werkzeug.utils import secure_filename
        filename = secure_filename(file.filename)
        filepath = upload_dir / filename
        file.save(filepath)

        # Получаем параметры
        mktu_classes = request.form.getlist('mktu_classes', type=int)
        manual_text = request.form.get('text', '').strip()

        # Результат
        result = {
            'filename': filename,
            'filepath': str(filepath),
            'image_url': f'/uploads/{upload_dir.name}/{filename}',
            'recognized_texts': [],
            'trademark_results': [],
            'image_search_links': {},
            'overall_status': 'green',
            'risk_factors': [],
            'recommendations': [],
            'summary': ''
        }

        # 1. Распознавание текста (OCR)
        try:
            img_check = image_checker.check_image(str(filepath))

            # Получаем распознанный текст
            for text_item in img_check.get('recognized_texts', []):
                result['recognized_texts'].append({
                    'text': text_item.text,
                    'confidence': round(text_item.confidence * 100, 1)
                })

            # Результаты анализа авторских прав
            copyright_result = img_check.get('copyright_result')
            if copyright_result:
                if copyright_result.brand_elements:
                    result['risk_factors'].append({
                        'type': 'brand',
                        'severity': 'red',
                        'message': f"Обнаружены бренды: {', '.join(copyright_result.brand_elements)}"
                    })
                if copyright_result.character_names:
                    result['risk_factors'].append({
                        'type': 'character',
                        'severity': 'red',
                        'message': f"Обнаружены персонажи: {', '.join(copyright_result.character_names)}"
                    })
        except Exception as e:
            result['recommendations'].append(f"Ошибка OCR: {str(e)}")

        # 2. Собираем текст для поиска ТЗ
        texts_to_check = []
        texts_to_check_lower = set()  # Для дедупликации

        # Добавляем ручной текст
        if manual_text:
            texts_to_check.append(manual_text)
            texts_to_check_lower.add(manual_text.lower())

        # Добавляем распознанный текст
        for text_item in result['recognized_texts']:
            full_text = text_item['text'].strip()

            # Добавляем полный текст целиком (если > 2 символов)
            if len(full_text) > 2 and full_text.lower() not in texts_to_check_lower:
                texts_to_check.append(full_text)
                texts_to_check_lower.add(full_text.lower())

            # Также добавляем отдельные слова (если > 2 символов)
            words = full_text.split()
            for word in words:
                clean_word = ''.join(c for c in word if c.isalnum())
                if len(clean_word) > 2 and clean_word.lower() not in texts_to_check_lower:
                    texts_to_check.append(clean_word)
                    texts_to_check_lower.add(clean_word.lower())

        # 2.1. Проверка на известные бренды с учётом опечаток OCR
        KNOWN_BRANDS_PATTERNS = {
            'nike': ['nike', 'nke', 'nik', 'nikе', 'niке', 'nіke', 'n1ke', 'nikel'],
            'adidas': ['adidas', 'adldas', 'adіdas', 'ad1das'],
            'puma': ['puma', 'рuma', 'pumа'],
            'gucci': ['gucci', 'guccі', 'guсci'],
            'chanel': ['chanel', 'сhanel', 'chanеl'],
            'louis vuitton': ['vuitton', 'vuіtton', 'lv'],
            'supreme': ['supreme', 'suprеme', 'suprеmе'],
        }

        all_recognized_text = ' '.join([t['text'] for t in result['recognized_texts']]).lower()
        # Нормализуем текст (заменяем похожие символы)
        normalized_text = all_recognized_text.replace('к', 'k').replace('е', 'e').replace('і', 'i').replace('а', 'a').replace('о', 'o').replace('с', 'c').replace('р', 'p').replace('в', 'b')

        for brand, patterns in KNOWN_BRANDS_PATTERNS.items():
            for pattern in patterns:
                if pattern in normalized_text or pattern in all_recognized_text:
                    # Нашли бренд - добавляем его для проверки
                    if brand.upper() not in texts_to_check and brand not in texts_to_check_lower:
                        texts_to_check.insert(0, brand.upper())  # В начало списка
                        texts_to_check_lower.add(brand)
                        result['risk_factors'].append({
                            'type': 'brand_detected',
                            'severity': 'red',
                            'message': f"Обнаружен известный бренд: {brand.upper()} (распознано как: '{all_recognized_text[:50]}')"
                        })
                    break

        # 3. Поиск по товарным знакам
        all_tm_results = []
        checked_texts = []

        for text in texts_to_check[:5]:  # Максимум 5 проверок
            try:
                tm_results = trademark_checker.check_all(text, mktu_classes)
                checked_texts.append(text)

                for r in tm_results:
                    tm_entry = {
                        'text': text,
                        'resource': r.resource_name,
                        'status': r.status.value,
                        'exact_match': r.exact_match,
                        'similar_match': r.similar_match,
                        'similarity_score': r.similarity_score,
                        'notes': r.notes,
                        'matches': r.found_matches[:5]
                    }
                    all_tm_results.append(tm_entry)

                    # Добавляем факторы риска
                    if r.exact_match:
                        result['risk_factors'].append({
                            'type': 'trademark',
                            'severity': 'red',
                            'message': f"Точное совпадение ТЗ для '{text}': {r.notes}"
                        })
                    elif r.similar_match and r.similarity_score >= 0.8:
                        result['risk_factors'].append({
                            'type': 'trademark',
                            'severity': 'yellow',
                            'message': f"Похожий ТЗ для '{text}' ({r.similarity_score:.0%}): {r.notes}"
                        })

            except Exception as e:
                result['recommendations'].append(f"Ошибка проверки '{text}': {str(e)}")

        result['trademark_results'] = all_tm_results
        result['checked_texts'] = checked_texts

        # 4. Ссылки для ручной проверки ТЗ
        if checked_texts:
            result['trademark_links'] = trademark_checker.generate_manual_check_links(
                checked_texts[0], mktu_classes
            )

        # 5. Ссылки для обратного поиска изображений
        result['image_search_links'] = {
            'yandex': {
                'name': 'Яндекс.Картинки',
                'url': 'https://yandex.ru/images/',
                'instruction': 'Нажмите на иконку камеры и загрузите изображение'
            },
            'google': {
                'name': 'Google Images',
                'url': 'https://images.google.com/',
                'instruction': 'Нажмите на иконку камеры и загрузите изображение'
            },
            'tineye': {
                'name': 'TinEye',
                'url': 'https://tineye.com/',
                'instruction': 'Загрузите изображение для поиска копий'
            },
            'bing': {
                'name': 'Bing Visual Search',
                'url': 'https://www.bing.com/visualsearch',
                'instruction': 'Перетащите изображение для поиска'
            }
        }

        # 6. Определяем общий статус
        has_red = any(f['severity'] == 'red' for f in result['risk_factors'])
        has_yellow = any(f['severity'] == 'yellow' for f in result['risk_factors'])
        has_tm_red = any(r['status'] == 'red' for r in all_tm_results)
        has_tm_yellow = any(r['status'] == 'yellow' for r in all_tm_results)

        if has_red or has_tm_red:
            result['overall_status'] = 'red'
        elif has_yellow or has_tm_yellow:
            result['overall_status'] = 'yellow'
        else:
            result['overall_status'] = 'green'

        # 7. Генерируем рекомендации
        if result['overall_status'] == 'red':
            result['recommendations'].insert(0,
                "⛔ ВНИМАНИЕ: Обнаружены критические совпадения. Использование не рекомендуется без консультации юриста."
            )
        elif result['overall_status'] == 'yellow':
            result['recommendations'].insert(0,
                "⚠️ Требуется дополнительная проверка перед использованием."
            )
        else:
            result['recommendations'].insert(0,
                "✅ Автоматическая проверка не выявила явных проблем."
            )

        if not result['recognized_texts']:
            result['recommendations'].append(
                "Текст на изображении не распознан. Если на изображении есть текст, проверьте его вручную."
            )

        result['recommendations'].append(
            "Рекомендуется выполнить обратный поиск изображения по ссылкам ниже."
        )

        # 8. Сводка
        result['summary'] = {
            'texts_found': len(result['recognized_texts']),
            'texts_checked': len(checked_texts),
            'tm_checks': len(all_tm_results),
            'risk_factors_count': len(result['risk_factors'])
        }

        return jsonify(result)

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """Отдача загруженных файлов"""
    return send_file(Path(app.config['UPLOAD_FOLDER']) / filename)


if __name__ == '__main__':
    print("=" * 60)
    print("Система проверки интеллектуальной собственности")
    print("=" * 60)
    print(f"Запуск веб-сервера на http://localhost:{APP_CONFIG['port']}")
    print("Для остановки нажмите Ctrl+C")
    print("=" * 60)

    app.run(
        host=APP_CONFIG['host'],
        port=APP_CONFIG['port'],
        debug=APP_CONFIG['debug']
    )
