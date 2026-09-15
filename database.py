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


def registrar_usuario(telegram_id, nombre, correo=None, nivel_acceso=1):
    conexion = obtener_conexion()

    try:
        conexion.execute(
            """
            INSERT INTO usuarios (
                telegram_id,
                nombre,
                correo,
                nivel_acceso,
                activo
            )
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(telegram_id) DO UPDATE SET
                nombre = excluded.nombre,
                correo = COALESCE(excluded.correo, usuarios.correo),
                nivel_acceso = excluded.nivel_acceso,
                activo = 1
            """,
            (telegram_id, nombre, correo, nivel_acceso)
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
