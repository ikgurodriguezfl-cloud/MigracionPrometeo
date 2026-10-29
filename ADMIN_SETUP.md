
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