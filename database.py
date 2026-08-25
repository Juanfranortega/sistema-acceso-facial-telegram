import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "data" / "sistema.db"


def obtener_conexion():
    conexion = sqlite3.connect(DATABASE_PATH)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def registrar_usuario(
    telegram_id,
    nombre,
    correo,
    nivel_acceso=1
):
    conexion = obtener_conexion()

    try:
        cursor = conexion.execute(
            """
            INSERT INTO usuarios (
                telegram_id,
                nombre,
                correo,
                nivel_acceso
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                telegram_id,
                nombre,
                correo,
                nivel_acceso
            )
        )

        conexion.commit()
        return cursor.lastrowid

    finally:
        conexion.close()


def registrar_perfil_facial(
    usuario_id,
    ruta_referencia,
    modelo="Facenet512"
):
    conexion = obtener_conexion()

    try:
        conexion.execute(
            """
            INSERT INTO perfiles_faciales (
                usuario_id,
                ruta_referencia,
                modelo_utilizado
            )
            VALUES (?, ?, ?)
            """,
            (
                usuario_id,
                ruta_referencia,
                modelo
            )
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


def guardar_informacion(
    titulo,
    contenido,
    nivel_requerido=0
):
    conexion = obtener_conexion()

    try:
        cursor = conexion.execute(
            """
            INSERT INTO informacion_empresarial (
                titulo,
                contenido,
                nivel_requerido
            )
            VALUES (?, ?, ?)
            """,
            (
                titulo,
                contenido,
                nivel_requerido
            )
        )

        conexion.commit()
        return cursor.lastrowid

    finally:
        conexion.close()


def obtener_informacion_autorizada(nivel_usuario):
    conexion = obtener_conexion()

    try:
        return conexion.execute(
            """
            SELECT
                id,
                titulo,
                contenido,
                nivel_requerido
            FROM informacion_empresarial
            WHERE activa = 1
              AND nivel_requerido <= ?
            ORDER BY titulo
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
            (
                usuario_id,
                telegram_id,
                resultado,
                distancia,
                motivo
            )
        )

        conexion.commit()

    finally:
        conexion.close()