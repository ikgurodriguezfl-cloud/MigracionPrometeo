import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

import bcrypt

from auth import AuthenticationService


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / 'auth.db'
        self.service = AuthenticationService(str(self.database_path))
        self.service.create_user('admin', 'correcta-123')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_credenciales_validas_crean_una_sesion(self):
        token = self.service.authenticate('admin', 'correcta-123')
        self.assertIsNotNone(token)
        self.assertTrue(self.service.is_authenticated(token))

    def test_credenciales_invalidas_no_crean_una_sesion(self):
        self.assertIsNone(self.service.authenticate('admin', 'incorrecta'))
        self.assertIsNone(self.service.authenticate('desconocido', 'correcta-123'))

    def test_contrasena_se_guarda_como_bcrypt_coste_12_sin_texto_plano(self):
        connection = sqlite3.connect(self.database_path)
        try:
            stored_hash = connection.execute(
                'SELECT password_hash FROM users WHERE username = ?', ('admin',)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertTrue(stored_hash.startswith('$2b$12$'))
        self.assertGreaterEqual(int(stored_hash.split('$')[2]), 12)
        self.assertNotIn('correcta-123', stored_hash)
        self.assertNotEqual(
            hashlib.sha256(b'correcta-123').hexdigest(), stored_hash
        )
        self.assertTrue(bcrypt.checkpw(b'correcta-123', stored_hash.encode('ascii')))

    def test_cerrar_sesion_revoca_la_sesion_y_bloquea_acciones_protegidas(self):
        token = self.service.authenticate('admin', 'correcta-123')
        self.service.require_authenticated(token)
        self.service.logout(token)
        self.assertFalse(self.service.is_authenticated(token))
        with self.assertRaises(PermissionError):
            self.service.require_authenticated(token)

    def test_solo_admin_puede_crear_usuarios(self):
        self.service.ensure_admin('admin-compartido')
        self.service.create_user('usuario', 'usuario-123')
        admin_token = self.service.authenticate('admin', 'admin-compartido')
        user_token = self.service.authenticate('usuario', 'usuario-123')

        self.service.require_admin(admin_token)
        with self.assertRaises(PermissionError):
            self.service.require_admin(user_token)


if __name__ == '__main__':
    unittest.main()