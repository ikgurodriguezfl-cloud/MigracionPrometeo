import logging

# El registro captura los eventos sin exponer secretos ni contraseñas
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

class AccesoDenegado(Exception):
    pass

MATRIZ_PERMISOS = {
    "validar_access": ["Ejecucion", "Administracion"],
    "iniciar_conversion": ["Ejecucion", "Administracion"],
    "revision_muestra": ["Revision", "Administracion"],
    "aprobar_exportacion": ["Aprobacion", "Administracion"]
}

def requerir_permiso(perfil_actual: str, operacion: str):
    permitidos = MATRIZ_PERMISOS.get(operacion, [])
    
    if perfil_actual not in permitidos:
        logging.warning(f"Seguridad: Acción '{operacion}' denegada. Perfil evaluado: '{perfil_actual}'.")
        raise AccesoDenegado("Acceso denegado: El perfil no está autorizado para esta operación.")
        
    logging.info(f"Seguridad: Operación '{operacion}' concedida al perfil '{perfil_actual}'.")
    return True