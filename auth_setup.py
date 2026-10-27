"""Crea el primer usuario local de Prometeo Migrator."""
import getpass
import os

from auth import AuthenticationService


def main():
    database_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth.db')
    service = AuthenticationService(database_path)
    username = input('Usuario: ').strip()
    password = getpass.getpass('Contrasena: ')
    confirmation = getpass.getpass('Repite la contrasena: ')
    if password != confirmation:
        raise SystemExit('Las contrasenas no coinciden.')
    try:
        service.create_user(username, password)
    except Exception as error:
        raise SystemExit(f'No se pudo crear el usuario: {error}') from error
    print('Usuario creado correctamente. La contrasena se almaceno como hash bcrypt.')


if __name__ == '__main__':
    main()