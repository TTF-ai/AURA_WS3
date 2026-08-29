"""
Language Manager for AURA voice system.

Manages per-user language preferences stored in the shared
AURA SQLite database. Does not import from aura_face_auth;
accesses the database file directly.
"""

import os
import sqlite3

DEFAULT_DB_PATH = os.path.expanduser("~/.aura/face_auth.db")
SUPPORTED_LANGUAGES = {"en", "kn", "en+kn"}
DEFAULT_LANGUAGE = "en"


class LanguageManager:
    """Manages user language preferences."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DEFAULT_DB_PATH

        # Add preferred_language column if it doesn't exist
        if os.path.exists(self.db_path):
            self._ensure_column()

    def _ensure_column(self):
        """Add preferred_language column to users table if missing."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("PRAGMA table_info(users)")
            columns = [row[1] for row in cursor.fetchall()]

            if "preferred_language" not in columns:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN preferred_language TEXT DEFAULT 'en'"
                )
                conn.commit()
            conn.close()
        except sqlite3.Error:
            pass  # Database may not exist yet

    def get_language(self, username: str) -> str:
        """
        Get preferred language for a user.

        Args:
            username: The authenticated username.

        Returns:
            str: Language code ('en', 'kn', 'en+kn').
        """
        if not os.path.exists(self.db_path):
            return DEFAULT_LANGUAGE

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                "SELECT preferred_language FROM users WHERE username = ?",
                (username,),
            )
            row = cursor.fetchone()
            conn.close()

            if row and row[0] in SUPPORTED_LANGUAGES:
                return row[0]
        except sqlite3.Error:
            pass

        return DEFAULT_LANGUAGE

    def set_language(self, username: str, language: str) -> bool:
        """
        Set preferred language for a user.

        Args:
            username: The authenticated username.
            language: Language code ('en', 'kn', 'en+kn').

        Returns:
            bool: True if updated successfully.
        """
        if language not in SUPPORTED_LANGUAGES:
            return False

        if not os.path.exists(self.db_path):
            return False

        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE users SET preferred_language = ? WHERE username = ?",
                (language, username),
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.Error:
            return False
