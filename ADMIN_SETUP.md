
$env:PROMETEO_ADMIN_PASSWORD = 'CONTRASENA_COMPARTIDA'
.venv\Scripts\python.exe main.py
```

Para conservarla entre sesiones de PowerShell:

```powershell
[Environment]::SetEnvironmentVariable('PROMETEO_ADMIN_PASSWORD', 'CONTRASENA_COMPARTIDA', 'User')
```

Al iniciar, la aplicacion crea o actualiza `admin` con rol `admin` en el
`auth.db` local. La contrasena se guarda como hash bcrypt con costo 12.

Los usuarios normales se crean desde `Crear usuario` dentro de la aplicacion.

Perfiles disponibles:

- `Ejecucion`: validar Access y MySQL, migrar/reprocesar lotes, consultar
  incidencias y descargar reportes. No puede revisar registros ni aprobar
  correcciones o exportaciones.
- `Revision`: consultar lotes y registros, registrar observaciones por ficha,
  proponer correcciones y descargar reportes. No puede ejecutar ni reprocesar
  migraciones.
- `Aprobacion`: mismas operaciones que `Administracion`, excepto crear usuarios.
- `Administracion`: acceso operativo completo y gestion de usuarios.

El reprocesamiento crea un lote vinculado al original, conserva los registros
MARC ya existentes y vuelve a intentar los faltantes; tambien puede completar
ejemplares que hayan quedado pendientes. Las observaciones de Revision se
guardan en MySQL con ficha, lote, autor y fecha.