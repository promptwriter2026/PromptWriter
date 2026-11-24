import json
import sqlite3
from contextlib import closing
from datetime import datetime

from promptwriter.config import DATA_DIR, HISTORY_DB_PATH

HISTORY_LIST_LIMIT = 200


def initialize_history_database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                source_tab TEXT,
                rough_idea TEXT,
                generated_prompt TEXT,
                engine TEXT,
                model TEXT,
                is_favorite INTEGER DEFAULT 0,
                image_path TEXT,
                settings_json TEXT
            )
            """
        )


def insert_generation(
    user_idea,
    generated_prompt,
    generation_settings,
    source_tab="generator",
    engine=None,
    model=None,
    image_path=None,
):
    if not isinstance(generated_prompt, str):
        raise ValueError("Cannot save a generated prompt that is not text.")
    if source_tab not in ("generator", "image_to_prompt"):
        raise ValueError(f"Unsupported history source tab: {source_tab}")
    with closing(
        sqlite3.connect(HISTORY_DB_PATH, timeout=10)
    ) as connection, connection:
        connection.execute(
            """
            INSERT INTO generations (
                timestamp, source_tab, rough_idea, generated_prompt,
                engine, model, is_favorite, image_path, settings_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                datetime.now()
                .astimezone()
                .isoformat(timespec="seconds"),
                source_tab,
                user_idea,
                generated_prompt,
                engine or generation_settings.get("llm_engine", ""),
                model or generation_settings.get("api_model", ""),
                image_path,
                json.dumps(generation_settings, ensure_ascii=False),
            ),
        )


def fetch_recent_generations(search_text="", favorites_only=False):
    search_pattern = f"%{search_text}%"
    with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
        return connection.execute(
            """
            SELECT id, timestamp, rough_idea, is_favorite
            FROM generations
            WHERE (? = '' OR rough_idea LIKE ? COLLATE NOCASE
                   OR generated_prompt LIKE ? COLLATE NOCASE)
              AND (? = 0 OR is_favorite = 1)
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                search_text,
                search_pattern,
                search_pattern,
                int(favorites_only),
                HISTORY_LIST_LIMIT,
            ),
        ).fetchall()


def fetch_generation(generation_id):
    with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
        return connection.execute(
            """
            SELECT id, timestamp, source_tab, rough_idea,
                   generated_prompt, engine, model, is_favorite,
                   image_path, settings_json
            FROM generations
            WHERE id = ?
            """,
            (generation_id,),
        ).fetchone()


def delete_generation(generation_id):
    with closing(
        sqlite3.connect(HISTORY_DB_PATH, timeout=10)
    ) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM generations WHERE id = ?", (generation_id,)
        )
        return cursor.rowcount > 0


def _bulk_delete_filter(include_favorites, older_than):
    clauses = []
    params = []
    if not include_favorites:
        clauses.append("COALESCE(is_favorite, 0) = 0")
    if older_than is not None:
        clauses.append("datetime(timestamp) < datetime(?)")
        params.append(older_than.isoformat(timespec="seconds"))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def count_generations_for_delete(include_favorites=False, older_than=None):
    where, params = _bulk_delete_filter(include_favorites, older_than)
    with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
        return connection.execute(
            f"SELECT COUNT(*) FROM generations {where}", params
        ).fetchone()[0]


def bulk_delete_generations(include_favorites=False, older_than=None):
    where, params = _bulk_delete_filter(include_favorites, older_than)
    with closing(
        sqlite3.connect(HISTORY_DB_PATH, timeout=10)
    ) as connection, connection:
        cursor = connection.execute(f"DELETE FROM generations {where}", params)
        return cursor.rowcount


def clear_history():
    """Delete every history row, creating the database if it does not exist."""
    initialize_history_database()
    with closing(
        sqlite3.connect(HISTORY_DB_PATH, timeout=10)
    ) as connection, connection:
        return connection.execute("DELETE FROM generations").rowcount


def toggle_favorite(generation_id):
    with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
        connection.execute(
            """
            UPDATE generations
            SET is_favorite = CASE WHEN is_favorite = 1 THEN 0 ELSE 1 END
            WHERE id = ?
            """,
            (generation_id,),
        )


def fetch_favorite_prompts():
    with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
        rows = connection.execute(
            """
            SELECT generated_prompt
            FROM generations
            WHERE is_favorite = 1
            ORDER BY id DESC
            """
        ).fetchall()
    return [row[0] for row in rows if isinstance(row[0], str) and row[0].strip()]
