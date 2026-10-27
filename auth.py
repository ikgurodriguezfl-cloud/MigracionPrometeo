"""Autenticacion local y sesiones revocables para la aplicacion."""
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import bcrypt


class AuthenticationService:
    """Gestiona usuarios con hashes bcrypt y tokens de sesion en memoria."""

    BCRYPT_ROUNDS = 12

    def __init__(self, database_path: str):
        self.database_path = Path(database_path)
        self._active_sessions = {}
        self._initialize_database()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def create_user(self, username: str, password: str):
        username = username.strip()
        if not username or not password:
            raise ValueError('El usuario y la contrasena son obligatorios.')
        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(rounds=self.BCRYPT_ROUNDS),
        ).decode('ascii')
        with self._connect() as connection:
            connection.execute(
                'INSERT INTO users (username, password_hash) VALUES (?, ?)',
                (username, password_hash),
            )

    def authenticate(self, username: str, password: str) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT password_hash FROM users WHERE username = ?',
                (username.strip(),),
            ).fetchone()
        if row is None:
            return None
        try:
            valid = bcrypt.checkpw(
                password.encode('utf-8'), row['password_hash'].encode('ascii')
            )
        except (ValueError, UnicodeEncodeError):
            valid = False
        if not valid:
            return None
        token = secrets.token_urlsafe(32)
        self._active_sessions[token] = username.strip()
        return token

    def is_authenticated(self, token: str) -> bool:
        return bool(token and token in self._active_sessions)

    def require_authenticated(self, token: str):
        if not self.is_authenticated(token):
            raise PermissionError('La sesion no es valida o ha sido cerrada.')

    def logout(self, token: str):
        self._active_sessions.pop(token, None)

    def has_users(self) -> bool:
        with self._connect() as connection:
            row = connection.execute('SELECT 1 FROM users LIMIT 1').fetchone()
        return row is not None