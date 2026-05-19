"""
Notes Manager — persistent quick-capture notes with SQLite.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent.parent / "data" / "notes.db"


class NotesManager:

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT DEFAULT '',
                    tags TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notes_tags ON notes(tags)
            """)
            conn.commit()
        finally:
            conn.close()

    def create(self, title: str, body: str = "", tags: list = None) -> dict:
        note_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        tags_str = ",".join(tags) if tags else ""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO notes (id, title, body, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (note_id, title, body, tags_str, now, now),
            )
            self._evict_overflow(cursor)
            conn.commit()
        finally:
            conn.close()
        return {
            "id": note_id, "title": title, "body": body,
            "tags": tags or [], "created_at": now, "updated_at": now,
        }

    def _evict_overflow(self, cursor) -> None:
        """Drop oldest notes if the total exceeds settings.notes.max_notes.

        Called inside ``create()``'s transaction so the insert + eviction
        are atomic. ``max_notes <= 0`` is treated as "no cap" so users can
        opt out by setting it to 0.
        """
        try:
            from core.settings_store import settings as _app_settings
            max_notes = int(_app_settings.get("notes.max_notes", 500))
        except Exception:
            return
        if max_notes <= 0:
            return
        cursor.execute("SELECT COUNT(*) FROM notes")
        (total,) = cursor.fetchone()
        excess = total - max_notes
        if excess <= 0:
            return
        cursor.execute(
            "DELETE FROM notes WHERE id IN "
            "(SELECT id FROM notes ORDER BY updated_at ASC LIMIT ?)",
            (excess,),
        )

    def get(self, note_id: str) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, body, tags, created_at, updated_at FROM notes WHERE id = ?", (note_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0], "title": row[1], "body": row[2],
                    "tags": row[3].split(",") if row[3] else [],
                    "created_at": row[4], "updated_at": row[5],
                }
            return None
        finally:
            conn.close()

    def list(self, tag: str = None, search: str = None) -> list:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            if search:
                cursor.execute(
                    "SELECT id, title, body, tags, created_at, updated_at FROM notes "
                    "WHERE title LIKE ? OR body LIKE ? ORDER BY updated_at DESC",
                    (f"%{search}%", f"%{search}%"),
                )
            elif tag:
                cursor.execute(
                    "SELECT id, title, body, tags, created_at, updated_at FROM notes "
                    "WHERE tags LIKE ? ORDER BY updated_at DESC",
                    (f"%{tag}%",),
                )
            else:
                cursor.execute(
                    "SELECT id, title, body, tags, created_at, updated_at FROM notes "
                    "ORDER BY updated_at DESC"
                )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0], "title": r[1], "body": r[2],
                    "tags": r[3].split(",") if r[3] else [],
                    "created_at": r[4], "updated_at": r[5],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def update(self, note_id: str, title: str = None, body: str = None, tags: list = None) -> bool:
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            fields = []
            values = []
            if title is not None:
                fields.append("title = ?")
                values.append(title)
            if body is not None:
                fields.append("body = ?")
                values.append(body)
            if tags is not None:
                fields.append("tags = ?")
                values.append(",".join(tags))
            fields.append("updated_at = ?")
            values.append(now)
            values.append(note_id)
            cursor.execute(
                f"UPDATE notes SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete(self, note_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def search(self, query: str) -> list:
        return self.list(search=query)


notes_manager = NotesManager()
