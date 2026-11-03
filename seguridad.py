
from werkzeug.security import generate_password_hash, check_password_hash


LONGITUD_MINIMA = 12


def generar_hash_contrasena(contrasena):
    if not isinstance(contrasena, str):
        raise TypeError("La contraseña debe ser texto.")

    if len(contrasena) < LONGITUD_MINIMA:
        raise ValueError(
            f"La contraseña debe tener al menos "
            f"{LONGITUD_MINIMA} caracteres."
        )

    return generate_password_hash(
        contrasena,
        method="scrypt",
        salt_length=16
    )


def verificar_contrasena(contrasena, hash_guardado):
    if not isinstance(contrasena, str) or not hash_guardado:
        return False

    try:
        return check_password_hash(hash_guardado, contrasena)
    except (ValueError, TypeError):
        return False
