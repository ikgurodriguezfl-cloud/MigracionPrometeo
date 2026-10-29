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
    ADMIN_USERNAME = 'admin'

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
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row['name'] for row in connection.execute('PRAGMA table_info(users)')
            }
            if 'role' not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
                )

    def create_user(self, username: str, password: str, role: str = 'user'):
        username = username.strip()
        if not username or not password or role not in ('admin', 'user'):
            raise ValueError('El usuario y la contrasena son obligatorios.')
        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(rounds=self.BCRYPT_ROUNDS),
        ).decode('ascii')
        with self._connect() as connection:
            connection.execute(
                'INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                (username, password_hash, role),
            )

    def ensure_admin(self, password: str):
        """Crea o actualiza la cuenta admin compartida del entorno."""
        if not password:
            raise ValueError('Configure PROMETEO_ADMIN_PASSWORD para crear el administrador.')
        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(rounds=self.BCRYPT_ROUNDS),
        ).decode('ascii')
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')
                ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash,
                                                    role = 'admin'
                """,
                (self.ADMIN_USERNAME, password_hash),
            )

    def authenticate(self, username: str, password: str) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT password_hash, role FROM users WHERE username = ?',
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
        self._active_sessions[token] = {
            'username': username.strip(),
            'role': row['role'],
        }
        return token

    def is_authenticated(self, token: str) -> bool:
        return bool(token and token in self._active_sessions)

    def require_authenticated(self, token: str):
        if not self.is_authenticated(token):
            raise PermissionError('La sesion no es valida o ha sido cerrada.')

    def is_admin(self, token: str) -> bool:
        return bool(
            token
            and self._active_sessions.get(token, {}).get('role') == 'admin'
        )

    def require_admin(self, token: str):
        self.require_authenticated(token)
        if not self.is_admin(token):
            raise PermissionError('Solo el administrador puede crear usuarios.')

    def logout(self, token: str):
        self._active_sessions.pop(token, None)

    def has_users(self) -> bool:
        with self._connect() as connection:
            row = connection.execute('SELECT 1 FROM users LIMIT 1').fetchone()
        return row is not None