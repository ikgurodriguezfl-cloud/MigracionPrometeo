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
    "revision_muestra": ["Revision", "Aprobacion", "Administracion"],
    "registrar_observacion": ["Revision", "Aprobacion", "Administracion"],
    "proponer_correccion": ["Revision", "Aprobacion", "Administracion"],
    "aprobar_correccion": ["Aprobacion", "Administracion"],
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
        raise AccesoDenegado("Acceso denegado: El perfil no está autorizado para esta operación.")
        
    logging.info(f"Seguridad: Operación '{operacion}' concedida al perfil '{perfil_actual}'.")
    return True


def tiene_permiso(perfil_actual: str, operacion: str) -> bool:
    return perfil_actual in MATRIZ_PERMISOS.get(operacion, [])