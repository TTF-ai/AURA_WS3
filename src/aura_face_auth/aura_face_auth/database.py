"""
SQLite database for AURA face authentication.

Stores users and their face embeddings.
No ROS dependencies in this file.
"""

import os
import sqlite3
import time

import numpy as np


# =================================================================
# DEFAULT DATABASE PATH
# =================================================================

DEFAULT_DB_DIR = os.path.expanduser("~/.aura")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, "face_auth.db")


# =================================================================
# DATABASE CLASS
# =================================================================

class FaceAuthDatabase:
    """SQLite database for face authentication data."""

    def __init__(self, db_path=None):
        """
        Initialize database connection.

        Args:
            db_path: path to SQLite database file.
                     Defaults to ~/.aura/face_auth.db
        """
        if db_path is None:
            db_path = DEFAULT_DB_PATH

        self.db_path = db_path

        # Create directory if needed
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

        self._create_tables()

    # =============================================================
    # TABLE CREATION
    # =============================================================

    def _create_tables(self):
        """Create database tables if they don't exist."""

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT UNIQUE NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                embedding  BLOB NOT NULL,
                quality    REAL DEFAULT 0.0,
                created_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        self.conn.commit()

    # =============================================================
    # USER OPERATIONS
    # =============================================================

    def create_user(self, username):
        """
        Create a new user.

        Args:
            username: unique username string

        Returns:
            int: user_id of the created user

        Raises:
            ValueError: if username already exists
        """
        now = time.time()

        try:
            cursor = self.conn.execute(
                "INSERT INTO users (username, created_at, updated_at) "
                "VALUES (?, ?, ?)",
                (username, now, now)
            )
            self.conn.commit()
            return cursor.lastrowid

        except sqlite3.IntegrityError:
            raise ValueError(
                f"User '{username}' already exists"
            )

    def get_user(self, username):
        """
        Get user by username.

        Args:
            username: username string

        Returns:
            dict with user_id, username, created_at, updated_at
            or None if not found
        """
        row = self.conn.execute(
            "SELECT user_id, username, created_at, updated_at "
            "FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    def get_all_users(self):
        """
        Get all users.

        Returns:
            list of dicts with user_id, username, created_at, updated_at
        """
        rows = self.conn.execute(
            "SELECT user_id, username, created_at, updated_at "
            "FROM users ORDER BY username"
        ).fetchall()

        return [dict(row) for row in rows]

    def delete_user(self, username):
        """
        Delete a user and all their embeddings.

        Args:
            username: username string

        Returns:
            bool: True if user was deleted, False if not found
        """
        cursor = self.conn.execute(
            "DELETE FROM users WHERE username = ?",
            (username,)
        )
        self.conn.commit()

        return cursor.rowcount > 0

    def user_exists(self, username):
        """
        Check if a user exists.

        Args:
            username: username string

        Returns:
            bool: True if user exists
        """
        row = self.conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        return row is not None

    # =============================================================
    # EMBEDDING OPERATIONS
    # =============================================================

    def save_embedding(self, user_id, embedding, quality=0.0):
        """
        Save a face embedding for a user.

        Args:
            user_id: integer user ID
            embedding: numpy array (e.g. 512-d float32)
            quality: quality score float

        Returns:
            int: embedding row ID
        """
        embedding = np.asarray(embedding, dtype=np.float32)
        blob = embedding.tobytes()
        now = time.time()

        cursor = self.conn.execute(
            "INSERT INTO embeddings "
            "(user_id, embedding, quality, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, blob, quality, now)
        )
        self.conn.commit()

        # Update user's updated_at
        self.conn.execute(
            "UPDATE users SET updated_at = ? WHERE user_id = ?",
            (now, user_id)
        )
        self.conn.commit()

        return cursor.lastrowid

    def get_embeddings(self, user_id):
        """
        Get all embeddings for a user.

        Args:
            user_id: integer user ID

        Returns:
            list of numpy arrays (float32)
        """
        rows = self.conn.execute(
            "SELECT embedding FROM embeddings "
            "WHERE user_id = ? ORDER BY created_at",
            (user_id,)
        ).fetchall()

        embeddings = []
        for row in rows:
            emb = np.frombuffer(row["embedding"], dtype=np.float32)
            embeddings.append(emb.copy())

        return embeddings

    def get_all_embeddings(self):
        """
        Get all embeddings grouped by username.

        Returns:
            dict of {username: [numpy arrays]}
        """
        rows = self.conn.execute(
            "SELECT u.username, e.embedding "
            "FROM embeddings e "
            "JOIN users u ON e.user_id = u.user_id "
            "ORDER BY u.username, e.created_at"
        ).fetchall()

        result = {}
        for row in rows:
            username = row["username"]
            emb = np.frombuffer(
                row["embedding"], dtype=np.float32
            ).copy()

            if username not in result:
                result[username] = []
            result[username].append(emb)

        return result

    def get_embedding_count(self, user_id):
        """
        Get the number of embeddings stored for a user.

        Args:
            user_id: integer user ID

        Returns:
            int: number of embeddings
        """
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM embeddings "
            "WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        return row["cnt"] if row else 0

    # =============================================================
    # CLEANUP
    # =============================================================

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __del__(self):
        self.close()
