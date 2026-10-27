# Registro de pruebas de autenticacion

## Entorno

- Fecha: 2026-10-26
- Sistema: Windows
- Python: 3.14
- Entorno virtual: `.venv`
- Dependencia: `bcrypt 5.0.0`
- Coste bcrypt configurado: 12

## Casos ejecutados

| Caso | Resultado |
| --- | --- |
| Credenciales validas crean una sesion | PASS |
| Contrasena incorrecta no autentica | PASS |
| Usuario inexistente no autentica | PASS |
| Hash bcrypt con coste minimo 12 | PASS |
| La contrasena no se almacena en texto plano | PASS |
| Cerrar sesion revoca el token | PASS |
| Una accion protegida rechaza el token revocado | PASS |
| Validaciones existentes de archivo Access | PASS |

## Comando reproducible

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_authentication.py
```

Resultado verificado: 4 pruebas, todas correctas.

La ejecucion global con `python -m unittest discover -v` produjo 8 pruebas correctas y un error en `test_nuevos_campos.py`. Ese archivo ejecuta una migracion real al importarse y depende de un archivo `.mdb` y del driver ODBC de Access que no estan disponibles en el entorno de prueba; no forma parte de la suite aislada de autenticacion.