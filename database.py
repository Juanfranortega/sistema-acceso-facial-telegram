import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _ruta_absoluta(valor, predeterminada):
    ruta = Path(valor) if valor else Path(predeterminada)
    if not ruta.is_absolute():
        ruta = BASE_DIR / ruta
    return ruta.resolve()


APP_DATA_DIR = _ruta_absoluta(os.getenv("APP_DATA_DIR"), BASE_DIR / "data")
DATABASE_PATH = _ruta_absoluta(
    os.getenv("DATABASE_PATH"),
    APP_DATA_DIR / "sistema.db"
)
REFERENCES_DIR = _ruta_absoluta(
    os.getenv("REFERENCES_DIR"),
    APP_DATA_DIR / "rostros" / "referencias"
)
TEMP_DIR = _ruta_absoluta(
    os.getenv("TEMP_DIR"),
    BASE_DIR / "temp"
)


def preparar_directorios():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def obtener_conexion():
    preparar_directorios()
    conexion = sqlite3.connect(DATABASE_PATH, timeout=30)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion




def registrar_usuario(
    telegram_id,
    nombre,
    correo=None,
    nivel_acceso=1,
    rol=None
):
    niveles_por_rol = {
        "EMPLEADO": 1,
        "EJECUTIVO": 2,
        "ADMIN": 3
    }

    if rol is not None:
        rol = rol.upper()

        if rol not in niveles_por_rol:
            raise ValueError(
                "Rol inválido. Usa EMPLEADO, EJECUTIVO o ADMIN."
            )

        nivel_acceso = niveles_por_rol[rol]

    if rol is not None:
        rol_inicial = rol
    elif nivel_acceso >= 3:
        rol_inicial = "ADMIN"
    elif nivel_acceso >= 2:
        rol_inicial = "EJECUTIVO"
    else:
        rol_inicial = "EMPLEADO"

    cambiar_rol = rol is not None
    conexion = obtener_conexion()

    try:
        conexion.execute(
            """
            INSERT INTO usuarios (
                telegram_id,
                nombre,
                correo,
                rol,
                nivel_acceso,
                activo
            )
            VALUES (?, ?, ?, ?, ?, 1)

            ON CONFLICT(telegram_id) DO UPDATE SET
                nombre = excluded.nombre,
                correo = COALESCE(
                    excluded.correo,
                    usuarios.correo
                ),
                rol = CASE
                    WHEN ? THEN excluded.rol
                    ELSE usuarios.rol
                END,
                nivel_acceso = CASE
                    WHEN ? THEN excluded.nivel_acceso
                    ELSE usuarios.nivel_acceso
                END,
                activo = 1
            """,
            (
                telegram_id,
                nombre,
                correo,
                rol_inicial,
                nivel_acceso,
                cambiar_rol,
                cambiar_rol
            )
        )

        conexion.commit()

        fila = conexion.execute(
            "SELECT id FROM usuarios WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()

        return fila["id"]

    finally:
        conexion.close()



def registrar_perfil_facial(usuario_id, ruta_referencia, modelo="SFace"):
    conexion = obtener_conexion()

    try:
        conexion.execute(
            """
            INSERT INTO perfiles_faciales (
                usuario_id,
                ruta_referencia,
                modelo_utilizado,
                fecha_actualizacion
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(usuario_id) DO UPDATE SET
                ruta_referencia = excluded.ruta_referencia,
                modelo_utilizado = excluded.modelo_utilizado,
                fecha_actualizacion = CURRENT_TIMESTAMP
            """,
            (usuario_id, str(ruta_referencia), modelo)
        )
        conexion.commit()
    finally:
        conexion.close()


def buscar_usuario_por_telegram(telegram_id):
    conexion = obtener_conexion()

    try:
        return conexion.execute(
            """
            SELECT
                u.id,
                u.telegram_id,
                u.nombre,
                u.correo,
                u.rol,
                u.nivel_acceso,
                u.activo,
                p.ruta_referencia,
                p.modelo_utilizado
            FROM usuarios AS u
            LEFT JOIN perfiles_faciales AS p
                ON p.usuario_id = u.id
            WHERE u.telegram_id = ?
            """,
            (telegram_id,)
        ).fetchone()
    finally:
        conexion.close()


def guardar_informacion(titulo, contenido, nivel_requerido=0):
    conexion = obtener_conexion()

    try:
        existente = conexion.execute(
            "SELECT id FROM informacion_empresarial WHERE titulo = ?",
            (titulo,)
        ).fetchone()

        if existente:
            conexion.execute(
                """
                UPDATE informacion_empresarial
                SET contenido = ?, nivel_requerido = ?, activa = 1
                WHERE id = ?
                """,
                (contenido, nivel_requerido, existente["id"])
            )
            informacion_id = existente["id"]
        else:
            cursor = conexion.execute(
                """
                INSERT INTO informacion_empresarial (
                    titulo,
                    contenido,
                    nivel_requerido
                )
                VALUES (?, ?, ?)
                """,
                (titulo, contenido, nivel_requerido)
            )
            informacion_id = cursor.lastrowid

        conexion.commit()
        return informacion_id
    finally:
        conexion.close()


def obtener_informacion_autorizada(nivel_usuario):
    conexion = obtener_conexion()

    try:
        return conexion.execute(
            """
            SELECT id, titulo, contenido, nivel_requerido
            FROM informacion_empresarial
            WHERE activa = 1
              AND nivel_requerido <= ?
            ORDER BY nivel_requerido, titulo
            """,
            (nivel_usuario,)
        ).fetchall()
    finally:
        conexion.close()


def registrar_intento(
    telegram_id,
    resultado,
    usuario_id=None,
    distancia=None,
    motivo=None
):
    conexion = obtener_conexion()

    try:
        conexion.execute(
            """
            INSERT INTO registros_autenticacion (
                usuario_id,
                telegram_id,
                resultado,
                distancia,
                motivo
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (usuario_id, telegram_id, resultado, distancia, motivo)
        )
        conexion.commit()
    finally:
        conexion.close()


def obtener_estadisticas():
    conexion = obtener_conexion()

    try:
        return {
            "usuarios": conexion.execute(
                "SELECT COUNT(*) FROM usuarios"
            ).fetchone()[0],
            "informacion": conexion.execute(
                "SELECT COUNT(*) FROM informacion_empresarial WHERE activa = 1"
            ).fetchone()[0],
            "intentos": conexion.execute(
                "SELECT COUNT(*) FROM registros_autenticacion"
            ).fetchone()[0]
        }
    finally:
        conexion.close()


def guardar_hash_contrasena(telegram_id, hash_contrasena):
    conexion = obtener_conexion()

    try:
        cursor = conexion.execute(
            """
            UPDATE usuarios
            SET password_hash = ?,
                debe_configurar_clave = 0
            WHERE telegram_id = ?
              AND activo = 1
            """,
            (hash_contrasena, telegram_id)
        )

        conexion.commit()
        return cursor.rowcount == 1

    finally:
        conexion.close()


def obtener_estado_contrasena(telegram_id):
    conexion = obtener_conexion()

    try:
        return conexion.execute(
            """
            SELECT
                id,
                nombre,
                rol,
                activo,
                password_hash,
                debe_configurar_clave
            FROM usuarios
            WHERE telegram_id = ?
            """,
            (telegram_id,)
        ).fetchone()

    finally:
        conexion.close()

def contar_intentos_contrasena_fallidos(telegram_id, minutos=15):
    if not isinstance(minutos, int) or minutos < 1:
        raise ValueError("El periodo debe ser un entero positivo.")

    conexion = obtener_conexion()

    try:
        fila = conexion.execute(
            """
            SELECT COUNT(*) AS total
            FROM registros_autenticacion
            WHERE telegram_id = ?
              AND resultado = 'RECHAZADO'
              AND motivo = 'Contraseña incorrecta'
              AND fecha_intento >= datetime('now', ?)
            """,
            (telegram_id, f"-{minutos} minutes")
        ).fetchone()

        return fila["total"]

    finally:
        conexion.close()

def crear_usuario_nuevo(telegram_id, nombre, rol, correo=None):
    niveles_por_rol = {
        "EMPLEADO": 1,
        "EJECUTIVO": 2,
        "ADMIN": 3
    }

    if not isinstance(telegram_id, int) or telegram_id <= 0:
        raise ValueError("El Telegram ID no es válido.")

    if not isinstance(nombre, str) or not nombre.strip():
        raise ValueError("El nombre no puede estar vacío.")

    if not isinstance(rol, str):
        raise ValueError("El rol no es válido.")

    nombre = nombre.strip()
    rol = rol.upper().strip()

    if rol not in niveles_por_rol:
        raise ValueError("El rol debe ser EMPLEADO, EJECUTIVO o ADMIN.")

    if correo is not None:
        correo = correo.strip() or None

    conexion = obtener_conexion()

    try:
        existente = conexion.execute(
            """
            SELECT id
            FROM usuarios
            WHERE telegram_id = ?
            """,
            (telegram_id,)
        ).fetchone()

        if existente:
            raise ValueError(
                "Ya existe un usuario con ese Telegram ID."
            )

        if correo:
            existente_correo = conexion.execute(
                """
                SELECT id
                FROM usuarios
                WHERE correo = ?
                """,
                (correo,)
            ).fetchone()

            if existente_correo:
                raise ValueError(
                    "Ya existe un usuario con ese correo."
                )

        cursor = conexion.execute(
            """
            INSERT INTO usuarios (
                telegram_id,
                nombre,
                correo,
                rol,
                nivel_acceso,
                activo,
                password_hash,
                debe_configurar_clave
            )
            VALUES (?, ?, ?, ?, ?, 1, NULL, 1)
            """,
            (
                telegram_id,
                nombre,
                correo,
                rol,
                niveles_por_rol[rol]
            )
        )

        conexion.commit()
        return cursor.lastrowid

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()


def actualizar_datos_usuario(usuario_id, nombre, correo=None):
    # Validar el identificador del usuario.
    if (
        isinstance(usuario_id, bool)
        or not isinstance(usuario_id, int)
        or usuario_id <= 0
    ):
        raise ValueError("El identificador del usuario no es válido.")

    # Validar el nombre.
    if not isinstance(nombre, str):
        raise ValueError("El nombre no es válido.")

    nombre = nombre.strip()

    if not nombre or len(nombre) > 100:
        raise ValueError(
            "El nombre no puede estar vacío ni superar los 100 caracteres."
        )

    # Normalizar el correo.
    if correo is not None:
        if not isinstance(correo, str):
            raise ValueError("El correo electrónico no es válido.")

        correo = correo.strip() or None

        if correo is not None and len(correo) > 254:
            raise ValueError("El correo supera la longitud permitida.")

    conexion = obtener_conexion()

    try:
        # Recuperar los datos actuales del usuario.
        usuario = conexion.execute(
            """
            SELECT id, nombre, correo
            FROM usuarios
            WHERE id = ?
            """,
            (usuario_id,)
        ).fetchone()

        if usuario is None:
            raise ValueError("No se encontró el usuario seleccionado.")

        # Comprobar que el correo no pertenezca a otra cuenta.
        if correo is not None:
            correo_existente = conexion.execute(
                """
                SELECT id
                FROM usuarios
                WHERE correo = ?
                  AND id != ?
                """,
                (correo, usuario_id)
            ).fetchone()

            if correo_existente:
                raise ValueError(
                    "Ese correo electrónico ya está registrado "
                    "en otra cuenta."
                )

        # Evitar actualizaciones cuando los datos son iguales.
        if (
            usuario["nombre"] == nombre
            and usuario["correo"] == correo
        ):
            return False

        # Actualizar exclusivamente nombre y correo.
        cursor = conexion.execute(
            """
            UPDATE usuarios
            SET nombre = ?,
                correo = ?
            WHERE id = ?
            """,
            (nombre, correo, usuario_id)
        )

        conexion.commit()

        return cursor.rowcount == 1

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()



def registrar_accion_administrativa(
    responsable_telegram_id,
    accion,
    usuario_objetivo_id=None,
    detalle=None
):
    # Validar Telegram ID del responsable.
    if (
        isinstance(responsable_telegram_id, bool)
        or not isinstance(responsable_telegram_id, int)
        or responsable_telegram_id <= 0
    ):
        raise ValueError("El Telegram ID del responsable no es válido.")

    # Validar el tipo de acción.
    if not isinstance(accion, str) or not accion.strip():
        raise ValueError("La acción administrativa no es válida.")

    accion = accion.strip().upper()

    if len(accion) > 100:
        raise ValueError("El nombre de la acción es demasiado largo.")

    # Validar el detalle.
    if detalle is not None:
        if not isinstance(detalle, str):
            raise ValueError("El detalle debe ser texto.")

        if len(detalle) > 2000:
            raise ValueError("El detalle supera los 2000 caracteres.")

    # Validar el usuario objetivo, si existe.
    if usuario_objetivo_id is not None:
        if (
            isinstance(usuario_objetivo_id, bool)
            or not isinstance(usuario_objetivo_id, int)
            or usuario_objetivo_id <= 0
        ):
            raise ValueError("El identificador del usuario objetivo no es válido.")

    conexion = obtener_conexion()

    try:
        # Recuperar los datos históricos del responsable.
        responsable = conexion.execute(
            """
            SELECT id, telegram_id, nombre, rol
            FROM usuarios
            WHERE telegram_id = ?
            """,
            (responsable_telegram_id,)
        ).fetchone()

        if responsable is None:
            raise ValueError("No se encontró al responsable de la operación.")

        # Recuperar los datos del usuario afectado.
        objetivo = None

        if usuario_objetivo_id is not None:
            objetivo = conexion.execute(
                """
                SELECT id, telegram_id, nombre
                FROM usuarios
                WHERE id = ?
                """,
                (usuario_objetivo_id,)
            ).fetchone()

            if objetivo is None:
                raise ValueError("No se encontró al usuario objetivo.")

        cursor = conexion.execute(
            """
            INSERT INTO registros_administrativos (
                responsable_id,
                responsable_telegram_id,
                responsable_nombre,
                responsable_rol,
                usuario_objetivo_id,
                usuario_objetivo_telegram_id,
                usuario_objetivo_nombre,
                accion,
                detalle
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                responsable["id"],
                responsable["telegram_id"],
                responsable["nombre"],
                responsable["rol"],
                objetivo["id"] if objetivo else None,
                objetivo["telegram_id"] if objetivo else None,
                objetivo["nombre"] if objetivo else None,
                accion,
                detalle
            )
        )

        conexion.commit()

        return cursor.lastrowid

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()

def listar_usuarios():
    conexion = obtener_conexion()

    try:
        filas = conexion.execute(
            """
            SELECT
                u.id,
                u.telegram_id,
                u.nombre,
                u.correo,
                u.rol,
                u.nivel_acceso,
                u.activo,
                u.fecha_registro,
                CASE
                    WHEN p.usuario_id IS NOT NULL THEN 1
                    ELSE 0
                END AS tiene_perfil_facial
            FROM usuarios AS u
            LEFT JOIN perfiles_faciales AS p
                ON p.usuario_id = u.id
            ORDER BY u.activo DESC, u.nombre COLLATE NOCASE
            """
        ).fetchall()

        return [dict(fila) for fila in filas]

    finally:
        conexion.close()


def cambiar_estado_usuario(usuario_id, activo):
    # Validar el identificador del usuario.
    if (
        isinstance(usuario_id, bool)
        or not isinstance(usuario_id, int)
        or usuario_id <= 0
    ):
        raise ValueError("El ID interno del usuario no es válido.")

    # Validar el nuevo estado.
    if (
        not isinstance(activo, (int, bool))
        or activo not in (0, 1)
    ):
        raise ValueError("El estado debe ser activo (1) o inactivo (0).")

    nuevo_estado = int(activo)

    conexion = obtener_conexion()

    try:
        cursor = conexion.execute(
            """
            UPDATE usuarios
            SET activo = ?
            WHERE id = ?
              AND activo != ?
            """,
            (nuevo_estado, usuario_id, nuevo_estado)
        )

        conexion.commit()

        # True únicamente si se modificó una cuenta.
        return cursor.rowcount == 1

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()


def obtener_historial_autenticacion(limite=20):
    if not isinstance(limite, int) or not 1 <= limite <= 100:
        raise ValueError("El límite debe estar entre 1 y 100.")

    conexion = obtener_conexion()

    try:
        filas = conexion.execute(
            """
            SELECT
                r.id,
                r.fecha_intento,
                r.telegram_id,
                r.usuario_id,
                COALESCE(u.nombre, 'Usuario no disponible') AS nombre,
                COALESCE(u.rol, 'SIN CUENTA') AS rol,
                r.resultado,
                r.distancia,
                r.motivo
            FROM registros_autenticacion AS r
            LEFT JOIN usuarios AS u
                ON r.usuario_id = u.id
            ORDER BY r.fecha_intento DESC, r.id DESC
            LIMIT ?
            """,
            (limite,)
        ).fetchall()

        return [dict(fila) for fila in filas]

    finally:
        conexion.close()


def obtener_historial_administrativo(limite=20):
    if (
        isinstance(limite, bool)
        or not isinstance(limite, int)
        or not 1 <= limite <= 100
    ):
        raise ValueError("El límite debe estar entre 1 y 100.")

    conexion = obtener_conexion()

    try:
        filas = conexion.execute(
            """
            SELECT
                id,
                fecha_accion,
                responsable_telegram_id,
                responsable_nombre,
                responsable_rol,
                usuario_objetivo_id,
                usuario_objetivo_telegram_id,
                usuario_objetivo_nombre,
                accion,
                detalle
            FROM registros_administrativos
            ORDER BY fecha_accion DESC, id DESC
            LIMIT ?
            """,
            (limite,)
        ).fetchall()

        return [dict(fila) for fila in filas]

    finally:
        conexion.close()



def cambiar_rol_usuario(usuario_id, rol):
    niveles_por_rol = {
        "EMPLEADO": 1,
        "EJECUTIVO": 2,
        "ADMIN": 3
    }

    # Validar el identificador del usuario.
    if (
        isinstance(usuario_id, bool)
        or not isinstance(usuario_id, int)
        or usuario_id <= 0
    ):
        raise ValueError("El ID interno del usuario no es válido.")

    # Validar el rol.
    if not isinstance(rol, str):
        raise ValueError("El rol indicado no es válido.")

    rol = rol.strip().upper()

    if rol not in niveles_por_rol:
        raise ValueError(
            "El rol debe ser EMPLEADO, EJECUTIVO o ADMIN."
        )

    nuevo_nivel = niveles_por_rol[rol]

    conexion = obtener_conexion()

    try:
        usuario = conexion.execute(
            """
            SELECT rol, nivel_acceso, activo
            FROM usuarios
            WHERE id = ?
            """,
            (usuario_id,)
        ).fetchone()

        if usuario is None:
            return False

        # Evitar modificaciones cuando el rol y el nivel
        # ya corresponden a los valores solicitados.
        if (
            usuario["rol"] == rol
            and usuario["nivel_acceso"] == nuevo_nivel
        ):
            return False

        # Evitar eliminar al último administrador activo.
        if (
            usuario["rol"] == "ADMIN"
            and usuario["activo"]
            and rol != "ADMIN"
        ):
            fila = conexion.execute(
                """
                SELECT COUNT(*) AS total
                FROM usuarios
                WHERE rol = 'ADMIN'
                  AND activo = 1
                """
            ).fetchone()

            if fila["total"] <= 1:
                raise ValueError(
                    "No puedes quitar el rol ADMIN "
                    "al último administrador activo."
                )

        # Actualizar únicamente si los valores actuales
        # siguen siendo los mismos que acabamos de consultar.
        cursor = conexion.execute(
            """
            UPDATE usuarios
            SET rol = ?,
                nivel_acceso = ?
            WHERE id = ?
              AND rol = ?
              AND nivel_acceso = ?
            """,
            (
                rol,
                nuevo_nivel,
                usuario_id,
                usuario["rol"],
                usuario["nivel_acceso"]
            )
        )

        conexion.commit()

        return cursor.rowcount == 1

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()




def restablecer_contrasena_usuario(usuario_id):
    # Validar el identificador del usuario.
    if (
        isinstance(usuario_id, bool)
        or not isinstance(usuario_id, int)
        or usuario_id <= 0
    ):
        raise ValueError("El ID interno del usuario no es válido.")

    conexion = obtener_conexion()

    try:
        cursor = conexion.execute(
            """
            UPDATE usuarios
            SET password_hash = NULL,
                debe_configurar_clave = 1
            WHERE id = ?
              AND (
                  password_hash IS NOT NULL
                  OR debe_configurar_clave != 1
              )
            """,
            (usuario_id,)
        )

        conexion.commit()

        # True únicamente si realmente cambió la información.
        return cursor.rowcount == 1

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()


def solicitar_actualizacion_facial(usuario_id, solicitada_por):
    for valor, nombre in (
        (usuario_id, "ID del usuario"),
        (solicitada_por, "ID del administrador")
    ):
        if (
            isinstance(valor, bool)
            or not isinstance(valor, int)
            or valor <= 0
        ):
            raise ValueError(f"El {nombre} no es válido.")

    if usuario_id == solicitada_por:
        raise ValueError(
            "No puedes solicitar la actualización de tu propio rostro."
        )

    conexion = obtener_conexion()

    try:
        usuario = conexion.execute(
            """
            SELECT id, activo
            FROM usuarios
            WHERE id = ?
            """,
            (usuario_id,)
        ).fetchone()

        administrador = conexion.execute(
            """
            SELECT id, activo, rol
            FROM usuarios
            WHERE id = ?
            """,
            (solicitada_por,)
        ).fetchone()

        if usuario is None or not usuario["activo"]:
            raise ValueError(
                "El usuario no existe o está inactivo."
            )

        if (
            administrador is None
            or not administrador["activo"]
            or administrador["rol"] != "ADMIN"
        ):
            raise ValueError(
                "El solicitante no es un administrador activo."
            )

        conexion.execute(
            """
            INSERT INTO solicitudes_actualizacion_facial (
                usuario_id,
                solicitada_por,
                estado,
                fecha_solicitud,
                fecha_confirmacion,
                fecha_expiracion
            )
            VALUES (
                ?, ?,
                'ESPERANDO_CLAVE',
                CURRENT_TIMESTAMP,
                NULL,
                datetime('now', '+24 hours')
            )
            ON CONFLICT(usuario_id) DO UPDATE SET
                solicitada_por = excluded.solicitada_por,
                estado = 'ESPERANDO_CLAVE',
                fecha_solicitud = CURRENT_TIMESTAMP,
                fecha_confirmacion = NULL,
                fecha_expiracion = datetime('now', '+24 hours')
            """,
            (usuario_id, solicitada_por)
        )

        conexion.commit()
        return True

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()

def obtener_solicitud_actualizacion_facial(telegram_id):
    conexion = obtener_conexion()

    try:
        # Eliminar solicitudes vencidas.
        conexion.execute(
            """
            DELETE FROM solicitudes_actualizacion_facial
            WHERE usuario_id = (
                SELECT id
                FROM usuarios
                WHERE telegram_id = ?
            )
            AND fecha_expiracion <= CURRENT_TIMESTAMP
            """,
            (telegram_id,)
        )

        conexion.commit()

        return conexion.execute(
            """
            SELECT
                s.usuario_id,
                s.solicitada_por,
                s.estado,
                s.fecha_solicitud,
                s.fecha_confirmacion,
                s.fecha_expiracion,
                u.telegram_id,
                u.nombre
            FROM solicitudes_actualizacion_facial AS s
            INNER JOIN usuarios AS u
                ON u.id = s.usuario_id
            WHERE u.telegram_id = ?
              AND u.activo = 1
            """,
            (telegram_id,)
        ).fetchone()

    finally:
        conexion.close()

def confirmar_actualizacion_facial(telegram_id):
    conexion = obtener_conexion()

    try:
        cursor = conexion.execute(
            """
            UPDATE solicitudes_actualizacion_facial
            SET estado = 'ESPERANDO_FOTO',
                fecha_confirmacion = CURRENT_TIMESTAMP,
                fecha_expiracion = datetime('now', '+10 minutes')
            WHERE usuario_id = (
                SELECT id
                FROM usuarios
                WHERE telegram_id = ?
                  AND activo = 1
            )
              AND estado = 'ESPERANDO_CLAVE'
              AND fecha_expiracion > CURRENT_TIMESTAMP
            """,
            (telegram_id,)
        )

        conexion.commit()
        return cursor.rowcount == 1

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()

def cancelar_actualizacion_facial(telegram_id):
    conexion = obtener_conexion()

    try:
        cursor = conexion.execute(
            """
            DELETE FROM solicitudes_actualizacion_facial
            WHERE usuario_id = (
                SELECT id
                FROM usuarios
                WHERE telegram_id = ?
            )
            """,
            (telegram_id,)
        )

        conexion.commit()
        return cursor.rowcount == 1

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()

def actualizar_perfil_facial_solicitado(
    usuario_id,
    ruta_referencia,
    modelo="SFace"
):
    if (
        isinstance(usuario_id, bool)
        or not isinstance(usuario_id, int)
        or usuario_id <= 0
    ):
        raise ValueError("El ID interno del usuario no es válido.")

    if not ruta_referencia:
        raise ValueError("La ruta de la fotografía no es válida.")

    conexion = obtener_conexion()

    try:
        usuario = conexion.execute(
            """
            SELECT activo
            FROM usuarios
            WHERE id = ?
            """,
            (usuario_id,)
        ).fetchone()

        if usuario is None or not usuario["activo"]:
            raise ValueError(
                "El usuario no existe o está inactivo."
            )

        solicitud = conexion.execute(
            """
            SELECT id
            FROM solicitudes_actualizacion_facial
            WHERE usuario_id = ?
              AND estado = 'ESPERANDO_FOTO'
              AND fecha_expiracion > CURRENT_TIMESTAMP
            """,
            (usuario_id,)
        ).fetchone()

        if solicitud is None:
            raise ValueError(
                "No existe una solicitud vigente con contraseña confirmada."
            )

        perfil_anterior = conexion.execute(
            """
            SELECT ruta_referencia
            FROM perfiles_faciales
            WHERE usuario_id = ?
            """,
            (usuario_id,)
        ).fetchone()

        ruta_anterior = (
            perfil_anterior["ruta_referencia"]
            if perfil_anterior else None
        )

        conexion.execute(
            """
            INSERT INTO perfiles_faciales (
                usuario_id,
                ruta_referencia,
                modelo_utilizado,
                fecha_actualizacion
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(usuario_id) DO UPDATE SET
                ruta_referencia = excluded.ruta_referencia,
                modelo_utilizado = excluded.modelo_utilizado,
                fecha_actualizacion = CURRENT_TIMESTAMP
            """,
            (usuario_id, str(ruta_referencia), modelo)
        )

        conexion.execute(
            """
            DELETE FROM solicitudes_actualizacion_facial
            WHERE usuario_id = ?
            """,
            (usuario_id,)
        )

        conexion.commit()
        return ruta_anterior

    except Exception:
        conexion.rollback()
        raise

    finally:
        conexion.close()
