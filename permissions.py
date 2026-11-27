import logging

# El registro captura los eventos sin exponer secretos ni contraseñas
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

class AccesoDenegado(Exception):
    pass

MATRIZ_PERMISOS = {
    "iniciar_nueva_migracion": ["Ejecucion", "Aprobacion", "Administracion"],
    "validar_access": ["Ejecucion", "Aprobacion", "Administracion"],
    "validar_mysql": ["Ejecucion", "Aprobacion", "Administracion"],
    "editar_configuracion": ["Ejecucion", "Aprobacion", "Administracion"],
    "iniciar_conversion": ["Ejecucion", "Aprobacion", "Administracion"],
    "detener_conversion": ["Ejecucion", "Aprobacion", "Administracion"],
    "reprocesar_lote": ["Ejecucion", "Aprobacion", "Administracion"],
    # Aprobacion y Administracion resuelven propuestas; solo Administracion aprueba las propias.
    "revision_muestra": ["Revision", "Aprobacion", "Administracion"],
    "registrar_observacion": ["Revision", "Aprobacion", "Administracion"],
    "proponer_correccion": ["Revision", "Aprobacion", "Administracion"],
    "aprobar_correccion": ["Aprobacion", "Administracion"],
    "aprobar_correccion_propia": ["Administracion"],
    "rechazar_correccion": ["Aprobacion", "Administracion"],
    "aprobar_exportacion": ["Aprobacion", "Administracion"],
    "exportar_historial": ["Ejecucion", "Revision", "Aprobacion", "Administracion"],
    "ver_incidencias": ["Ejecucion", "Revision", "Aprobacion", "Administracion"],
    "ver_actividad": ["Ejecucion", "Aprobacion", "Administracion"],
    "gestionar_usuarios": ["Administracion"],
}


def requerir_permiso(perfil_actual: str, operacion: str):
    permitidos = MATRIZ_PERMISOS.get(operacion, [])
    
    if perfil_actual not in permitidos:
        logging.warning(f"Seguridad: Acción '{operacion}' denegada. Perfil evaluado: '{perfil_actual}'.")
        raise AccesoDenegado("Tu cuenta no tiene permiso para realizar esta acción. Pide ayuda al administrador.")
        
    logging.info(f"Seguridad: Operación '{operacion}' concedida al perfil '{perfil_actual}'.")
    return True


def tiene_permiso(perfil_actual: str, operacion: str) -> bool:
    return perfil_actual in MATRIZ_PERMISOS.get(operacion, [])


def motivo_bloqueo_correccion(perfil, usuario, autor, aprobar):
    """La misma regla alimenta los botones y la decisión dentro de la transacción."""
    permiso = 'aprobar_correccion' if aprobar else 'rechazar_correccion'
    if not tiene_permiso(perfil, permiso):
        return 'Tu cuenta no tiene permiso para decidir sobre esta corrección.'
    if usuario == autor:
        if aprobar and tiene_permiso(perfil, 'aprobar_correccion_propia'):
            return ''
        if aprobar:
            return ('Solo el administrador puede aprobar sus propias correcciones. '
                    'Pide a otra persona con permiso de aprobación que revise la tuya.')
        return 'Pide a otra persona con permiso de aprobación que rechace tu corrección.'
    return ''
