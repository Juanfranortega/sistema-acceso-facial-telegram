from database import (
    obtener_conexion,
    registrar_usuario,
    registrar_perfil_facial,
    guardar_informacion,
    registrar_intento
)


def base_contiene_usuarios():
    conexion = obtener_conexion()

    try:
        resultado = conexion.execute(
            "SELECT COUNT(*) AS total FROM usuarios"
        ).fetchone()

        return resultado["total"] > 0

    finally:
        conexion.close()


def insertar_datos_prueba():
    if base_contiene_usuarios():
        print("La base de datos ya contiene usuarios.")
        print("No se agregaron registros duplicados.")
        return

    # Usuarios ficticios
    empleado_id = registrar_usuario(
        telegram_id=100000001,
        nombre="Empleado de prueba",
        correo="empleado@empresa.test",
        nivel_acceso=1
    )

    administrador_id = registrar_usuario(
        telegram_id=100000002,
        nombre="Administrador de prueba",
        correo="administrador@empresa.test",
        nivel_acceso=2
    )

    # Referencias faciales ficticias
    registrar_perfil_facial(
        usuario_id=empleado_id,
        ruta_referencia="rostros/referencias/empleado_prueba.jpg"
    )

    registrar_perfil_facial(
        usuario_id=administrador_id,
        ruta_referencia="rostros/referencias/administrador_prueba.jpg"
    )

    # Información empresarial
    guardar_informacion(
        titulo="Horario general",
        contenido="El horario de atención es de lunes a viernes de 8:00 a 17:00.",
        nivel_requerido=0
    )

    guardar_informacion(
        titulo="Procedimiento interno",
        contenido="Los empleados deben registrar sus actividades al finalizar la jornada.",
        nivel_requerido=1
    )

    guardar_informacion(
        titulo="Reporte administrativo",
        contenido="Información privada disponible solamente para administradores.",
        nivel_requerido=2
    )

    # Intentos de autenticación
    registrar_intento(
        usuario_id=empleado_id,
        telegram_id=100000001,
        resultado="EXITOSO",
        distancia=0.25,
        motivo="Rostro reconocido correctamente"
    )

    registrar_intento(
        usuario_id=None,
        telegram_id=100000003,
        resultado="RECHAZADO",
        distancia=0.79,
        motivo="Usuario o rostro no reconocido"
    )

    print("Datos de prueba agregados correctamente.")
    print("Se agregaron:")
    print("- 2 usuarios")
    print("- 2 perfiles faciales")
    print("- 3 registros de información empresarial")
    print("- 2 intentos de autenticación")


if __name__ == "__main__":
    insertar_datos_prueba()