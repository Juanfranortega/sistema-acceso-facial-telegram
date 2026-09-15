import sqlite3
from pathlib import Path

from database import DATABASE_PATH, guardar_informacion, preparar_directorios


BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "schema.sql"


def crear_base_datos():
    preparar_directorios()

    with sqlite3.connect(DATABASE_PATH) as conexion:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as archivo:
            conexion.executescript(archivo.read())

    print("Base de datos preparada correctamente.")
    print(f"Ubicación: {DATABASE_PATH}")


def sembrar_informacion_inicial():
    guardar_informacion(
        "Horario general",
        "El horario de atención es de lunes a viernes de 8:00 a 17:00.",
        0
    )
    guardar_informacion(
        "Procedimiento interno",
        "Los empleados deben registrar sus actividades al finalizar la jornada.",
        1
    )
    guardar_informacion(
        "Reporte administrativo",
        "Información reservada para usuarios con nivel de administrador.",
        2
    )
    print("Información empresarial de demostración preparada.")


if __name__ == "__main__":
    crear_base_datos()
    sembrar_informacion_inicial()
