"""Per-user progress stored in SQLite."""

import sqlite3
from pathlib import Path


class ProgressStore:
    def __init__(self, filename):
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER PRIMARY KEY,
            last_stop_id TEXT NOT NULL,
            quiz_index INTEGER NOT NULL DEFAULT 0,
            quiz_score INTEGER NOT NULL DEFAULT 0,
            quiz_active INTEGER NOT NULL DEFAULT 0,
            quiz_run INTEGER NOT NULL DEFAULT 0
        )""")
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(progress)")}
        if "quiz_run" not in columns:
            self.connection.execute("ALTER TABLE progress ADD COLUMN quiz_run INTEGER NOT NULL DEFAULT 0")
        self.connection.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.connection.commit()

    def get_offset(self):
        row = self.connection.execute("SELECT value FROM meta WHERE key='update_offset'").fetchone()
        return int(row[0]) if row else None

    def set_offset(self, offset):
        self.connection.execute("""INSERT INTO meta (key, value) VALUES ('update_offset', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (str(offset),))
        self.connection.commit()

    def get(self, user_id):
        row = self.connection.execute("SELECT * FROM progress WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def start(self, user_id, stop_id):
        self.connection.execute("""INSERT INTO progress (user_id, last_stop_id) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_stop_id=excluded.last_stop_id,
            quiz_index=0, quiz_score=0, quiz_active=0""", (user_id, stop_id))
        self.connection.commit()

    def visit(self, user_id, stop_id):
        self.connection.execute("""INSERT INTO progress (user_id, last_stop_id) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_stop_id=excluded.last_stop_id""", (user_id, stop_id))
        self.connection.commit()

    def start_quiz(self, user_id, stop_id):
        self.visit(user_id, stop_id)
        self.connection.execute("UPDATE progress SET quiz_index=0, quiz_score=0, quiz_active=1, quiz_run=quiz_run+1 WHERE user_id=?", (user_id,))
        self.connection.commit()

    def answer(self, user_id, quiz_run, question_index, is_correct, total):
        """Return updated state; None means a duplicate or stale answer."""
        row = self.get(user_id)
        if not row or not row["quiz_active"] or row["quiz_run"] != quiz_run or row["quiz_index"] != question_index:
            return None
        next_index = question_index + 1
        score = row["quiz_score"] + int(is_correct)
        self.connection.execute("""UPDATE progress SET quiz_index=?, quiz_score=?, quiz_active=?
            WHERE user_id=?""", (next_index, score, int(next_index < total), user_id))
        self.connection.commit()
        return {"quiz_index": next_index, "quiz_score": score, "quiz_active": int(next_index < total)}

    def close(self):
        self.connection.close()
