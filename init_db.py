import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "sistema.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


def crear_base_datos():
    try:
        DATA_DIR.mkdir(exist_ok=True)

        with sqlite3.connect(DATABASE_PATH) as conexion:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as archivo:
                conexion.executescript(archivo.read())

        print("Base de datos creada correctamente.")
        print(f"Ubicación: {DATABASE_PATH}")

    except sqlite3.Error as error:
        print(f"Error de SQLite: {error}")

    except OSError as error:
        print(f"Error al leer los archivos: {error}")


if __name__ == "__main__":
    crear_base_datos()