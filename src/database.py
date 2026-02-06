# -*- coding: utf-8 -*-
"""
Модуль для работы с базой данных истории проверок
SQLite для хранения результатов проверок
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

# Путь к базе данных
DB_PATH = Path(__file__).parent.parent / "data" / "history.db"


@contextmanager
def get_db_connection():
    """Контекстный менеджер для подключения к БД"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """Инициализация базы данных"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Таблица проверок наименований
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS name_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                query_text TEXT NOT NULL,
                mktu_classes TEXT,
                overall_status TEXT NOT NULL,
                results_json TEXT,
                manual_links_json TEXT
            )
        ''')

        # Таблица проверок изображений
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS image_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                filename TEXT NOT NULL,
                filepath TEXT,
                overall_status TEXT NOT NULL,
                recognized_texts_json TEXT,
                trademark_results_json TEXT,
                image_search_results_json TEXT,
                risk_factors_json TEXT,
                recommendations_json TEXT,
                summary_json TEXT
            )
        ''')

        # Индексы для быстрого поиска
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_name_checks_date ON name_checks(created_at DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_image_checks_date ON image_checks(created_at DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_name_checks_status ON name_checks(overall_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_image_checks_status ON image_checks(overall_status)')

        conn.commit()
        print("[OK] База данных истории инициализирована")


def save_name_check(query_text: str, mktu_classes: List[int],
                    overall_status: str, results: List[Dict],
                    manual_links: Dict[str, str]) -> int:
    """Сохранить результат проверки наименования"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO name_checks (query_text, mktu_classes, overall_status, results_json, manual_links_json)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            query_text,
            json.dumps(mktu_classes),
            overall_status,
            json.dumps(results, ensure_ascii=False),
            json.dumps(manual_links, ensure_ascii=False)
        ))
        conn.commit()
        return cursor.lastrowid


def save_image_check(filename: str, filepath: str, overall_status: str,
                     recognized_texts: List[Dict], trademark_results: List[Dict],
                     image_search_results: List[Dict], risk_factors: List[Dict],
                     recommendations: List[str], summary: Dict) -> int:
    """Сохранить результат проверки изображения"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO image_checks (filename, filepath, overall_status,
                recognized_texts_json, trademark_results_json, image_search_results_json,
                risk_factors_json, recommendations_json, summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            filename,
            filepath,
            overall_status,
            json.dumps(recognized_texts, ensure_ascii=False),
            json.dumps(trademark_results, ensure_ascii=False),
            json.dumps(image_search_results, ensure_ascii=False),
            json.dumps(risk_factors, ensure_ascii=False),
            json.dumps(recommendations, ensure_ascii=False),
            json.dumps(summary, ensure_ascii=False)
        ))
        conn.commit()
        return cursor.lastrowid


def get_name_checks(limit: int = 50, offset: int = 0,
                    status_filter: str = None) -> List[Dict]:
    """Получить историю проверок наименований"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        query = 'SELECT * FROM name_checks'
        params = []

        if status_filter:
            query += ' WHERE overall_status = ?'
            params.append(status_filter)

        query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            results.append({
                'id': row['id'],
                'created_at': row['created_at'],
                'query_text': row['query_text'],
                'mktu_classes': json.loads(row['mktu_classes']) if row['mktu_classes'] else [],
                'overall_status': row['overall_status'],
                'results': json.loads(row['results_json']) if row['results_json'] else [],
                'manual_links': json.loads(row['manual_links_json']) if row['manual_links_json'] else {}
            })

        return results


def get_image_checks(limit: int = 50, offset: int = 0,
                     status_filter: str = None) -> List[Dict]:
    """Получить историю проверок изображений"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        query = 'SELECT * FROM image_checks'
        params = []

        if status_filter:
            query += ' WHERE overall_status = ?'
            params.append(status_filter)

        query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            results.append({
                'id': row['id'],
                'created_at': row['created_at'],
                'filename': row['filename'],
                'filepath': row['filepath'],
                'overall_status': row['overall_status'],
                'recognized_texts': json.loads(row['recognized_texts_json']) if row['recognized_texts_json'] else [],
                'trademark_results': json.loads(row['trademark_results_json']) if row['trademark_results_json'] else [],
                'image_search_results': json.loads(row['image_search_results_json']) if row['image_search_results_json'] else [],
                'risk_factors': json.loads(row['risk_factors_json']) if row['risk_factors_json'] else [],
                'recommendations': json.loads(row['recommendations_json']) if row['recommendations_json'] else [],
                'summary': json.loads(row['summary_json']) if row['summary_json'] else {}
            })

        return results


def get_name_check_by_id(check_id: int) -> Optional[Dict]:
    """Получить проверку наименования по ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM name_checks WHERE id = ?', (check_id,))
        row = cursor.fetchone()

        if not row:
            return None

        return {
            'id': row['id'],
            'created_at': row['created_at'],
            'query_text': row['query_text'],
            'mktu_classes': json.loads(row['mktu_classes']) if row['mktu_classes'] else [],
            'overall_status': row['overall_status'],
            'results': json.loads(row['results_json']) if row['results_json'] else [],
            'manual_links': json.loads(row['manual_links_json']) if row['manual_links_json'] else {}
        }


def get_image_check_by_id(check_id: int) -> Optional[Dict]:
    """Получить проверку изображения по ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM image_checks WHERE id = ?', (check_id,))
        row = cursor.fetchone()

        if not row:
            return None

        return {
            'id': row['id'],
            'created_at': row['created_at'],
            'filename': row['filename'],
            'filepath': row['filepath'],
            'overall_status': row['overall_status'],
            'recognized_texts': json.loads(row['recognized_texts_json']) if row['recognized_texts_json'] else [],
            'trademark_results': json.loads(row['trademark_results_json']) if row['trademark_results_json'] else [],
            'image_search_results': json.loads(row['image_search_results_json']) if row['image_search_results_json'] else [],
            'risk_factors': json.loads(row['risk_factors_json']) if row['risk_factors_json'] else [],
            'recommendations': json.loads(row['recommendations_json']) if row['recommendations_json'] else [],
            'summary': json.loads(row['summary_json']) if row['summary_json'] else {}
        }


def get_statistics() -> Dict:
    """Получить статистику проверок"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Статистика по наименованиям
        cursor.execute('SELECT COUNT(*) as total FROM name_checks')
        name_total = cursor.fetchone()['total']

        cursor.execute('SELECT overall_status, COUNT(*) as count FROM name_checks GROUP BY overall_status')
        name_by_status = {row['overall_status']: row['count'] for row in cursor.fetchall()}

        # Статистика по изображениям
        cursor.execute('SELECT COUNT(*) as total FROM image_checks')
        image_total = cursor.fetchone()['total']

        cursor.execute('SELECT overall_status, COUNT(*) as count FROM image_checks GROUP BY overall_status')
        image_by_status = {row['overall_status']: row['count'] for row in cursor.fetchall()}

        return {
            'name_checks': {
                'total': name_total,
                'red': name_by_status.get('red', 0),
                'yellow': name_by_status.get('yellow', 0),
                'green': name_by_status.get('green', 0)
            },
            'image_checks': {
                'total': image_total,
                'red': image_by_status.get('red', 0),
                'yellow': image_by_status.get('yellow', 0),
                'green': image_by_status.get('green', 0)
            }
        }


def delete_check(check_type: str, check_id: int) -> bool:
    """Удалить проверку из истории"""
    table = 'name_checks' if check_type == 'name' else 'image_checks'

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f'DELETE FROM {table} WHERE id = ?', (check_id,))
        conn.commit()
        return cursor.rowcount > 0


def clear_history(check_type: str = None) -> int:
    """Очистить историю проверок"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        deleted = 0

        if check_type == 'name' or check_type is None:
            cursor.execute('DELETE FROM name_checks')
            deleted += cursor.rowcount

        if check_type == 'image' or check_type is None:
            cursor.execute('DELETE FROM image_checks')
            deleted += cursor.rowcount

        conn.commit()
        return deleted


# Инициализация при импорте
init_database()
