from database import buscar_usuario_por_telegram
from reconocimiento import verificar_rostro


def procesar_acceso_telegram(telegram_id, ruta_foto_nueva):
    print(f"Buscando al usuario con Telegram ID: {telegram_id}...")
    usuario = buscar_usuario_por_telegram(telegram_id)
    if usuario is None:
        print("ACCESO DENEGADO: Usuario no encontrado en la base de datos.")
        return

    nombre = usuario["nombre"]
    ruta_referencia = usuario["ruta_referencia"]
    modelo = usuario["modelo_utilizado"]

    print(f"Usuario localizado: {nombre}")
    print(f"Ruta en BD: {ruta_referencia}")
    print(f"Iniciando procesamiento biométrico con {modelo}...")

    try:
        resultado = verificar_rostro(
            ruta_referencia,
            ruta_foto_nueva,
            modelo
        )

        es_mismo = resultado["verificado"]
        distancia = resultado["distancia"]

        print("-" * 40)
        if es_mismo:
            print(f"¡ACCESO CONCEDIDO! El rostro coincide perfectamente.")
        else:
            print(f"ACCESO DENEGADO. El rostro no coincide.")

        print(f"Métrica de distancia: {distancia:.4f}")
        print("-" * 40)

    except Exception as e:
        print(f"Error interno durante la verificación facial: {e}")


if __name__ == "__main__":
    id_prueba = 100000001
    foto_intento = "rostros/pruebas/josue2.jpeg"

    procesar_acceso_telegram(id_prueba, foto_intento)
