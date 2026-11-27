"""Mensajes para las personas que usan la aplicación, sin detalles del sistema."""
import logging


class AvisoUsuario(ValueError):
    """Un problema conocido con una explicación lista para mostrar al usuario."""


def mensaje_error(error, alternativa):
    """Conserva avisos conocidos incluso cuando otra capa envuelve la excepción.

    Los fallos inesperados usan la orientación de la pantalla. No se vuelcan
    consultas, rutas, credenciales ni mensajes de controladores en un diálogo.
    """
    causa = error
    vistas = set()
    while isinstance(causa, BaseException) and id(causa) not in vistas:
        if isinstance(causa, AvisoUsuario):
            return str(causa)
        vistas.add(id(causa))
        causa = causa.__cause__
    logging.getLogger(__name__).warning(
        '%s (tipo de problema: %s)', alternativa, type(error).__name__,
    )
    return alternativa
