import asyncio
import logging
import os
from pathlib import Path
from threading import Thread
from uuid import uuid4

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)


load_dotenv()

from database import (  # noqa: E402
    REFERENCES_DIR,
    TEMP_DIR,
    buscar_usuario_por_telegram,
    obtener_informacion_autorizada,
    registrar_intento,
    registrar_perfil_facial,
    registrar_usuario
)
from init_db import crear_base_datos, sembrar_informacion_inicial  # noqa: E402
from reconocimiento import verificar_rostro  # noqa: E402
from web_app import configurar_bot, iniciar_servidor_web  # noqa: E402


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
# Evita que las URL de la API de Telegram (que incluyen el token) aparezcan
# en los registros del proveedor de alojamiento.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REGISTRATION_CODE = os.getenv("REGISTRATION_CODE")
FACE_MODEL = os.getenv("FACE_MODEL", "SFace")


def formatear_informacion(registros, solo_privada=False):
    seleccionados = [
        fila for fila in registros
        if not solo_privada or fila["nivel_requerido"] > 0
    ]

    if not seleccionados:
        return "No hay información disponible para este nivel."

    return "\n\n".join(
        f"📌 {fila['titulo']}\n{fila['contenido']}"
        for fila in seleccionados
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = update.effective_user
    await update.message.reply_text(
        f"¡Hola, {usuario.first_name}! 👋\n\n"
        "Este sistema protege información empresarial mediante reconocimiento facial.\n\n"
        "Comandos disponibles:\n"
        "/publica - Consultar información general\n"
        "/registrar CLAVE Nombre - Registrar rostro de demostración\n"
        "/privada - Solicitar acceso protegido\n"
        "/id - Consultar tu identificador de Telegram\n"
        "/cancelar - Cancelar el proceso actual"
    )


async def mostrar_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Tu Telegram ID es: {update.effective_user.id}"
    )


async def informacion_publica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    registros = obtener_informacion_autorizada(0)
    await update.message.reply_text(formatear_informacion(registros))


async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not REGISTRATION_CODE:
        await update.message.reply_text(
            "El registro está deshabilitado porque falta configurar REGISTRATION_CODE."
        )
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Uso correcto: /registrar CLAVE Nombre completo"
        )
        return

    clave = context.args[0]
    nombre = " ".join(context.args[1:]).strip()

    if clave != REGISTRATION_CODE:
        await update.message.reply_text("Clave de registro incorrecta.")
        return

    context.user_data["accion_foto"] = "registro"
    context.user_data["nombre_registro"] = nombre

    await update.message.reply_text(
        "Ahora envía una fotografía clara del rostro que quedará como referencia.\n"
        "Para una prueba válida, después utiliza otra fotografía de la misma persona."
    )


async def solicitar_privada(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    usuario = buscar_usuario_por_telegram(telegram_id)

    if usuario is None or not usuario["activo"]:
        registrar_intento(
            telegram_id=telegram_id,
            resultado="RECHAZADO",
            motivo="Usuario no registrado o inactivo"
        )
        await update.message.reply_text(
            "No estás registrado. Utiliza /registrar con la clave de demostración."
        )
        return

    if not usuario["ruta_referencia"]:
        await update.message.reply_text(
            "Tu usuario no tiene un rostro de referencia registrado."
        )
        return

    context.user_data["accion_foto"] = "verificacion"
    await update.message.reply_text(
        "🔐 Acceso protegido. Envía una fotografía para verificar tu identidad."
    )


async def recibir_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accion = context.user_data.get("accion_foto")

    if not accion:
        await update.message.reply_text(
            "Primero utiliza /registrar o /privada para indicar qué deseas hacer."
        )
        return

    telegram_id = update.effective_user.id
    archivo = await update.message.photo[-1].get_file()

    if accion == "registro":
        nombre = context.user_data.get("nombre_registro", "Usuario de demostración")
        ruta_referencia = REFERENCES_DIR / f"{telegram_id}.jpg"
        await archivo.download_to_drive(custom_path=str(ruta_referencia))

        usuario_id = registrar_usuario(
            telegram_id=telegram_id,
            nombre=nombre,
            nivel_acceso=1
        )
        registrar_perfil_facial(
            usuario_id=usuario_id,
            ruta_referencia=ruta_referencia,
            modelo=FACE_MODEL
        )

        context.user_data.clear()
        await update.message.reply_text(
            "✅ Registro completado. Ahora utiliza /privada y envía una segunda "
            "fotografía de la misma persona."
        )
        return

    usuario = buscar_usuario_por_telegram(telegram_id)
    ruta_temporal = TEMP_DIR / f"{telegram_id}-{uuid4().hex}.jpg"
    await archivo.download_to_drive(custom_path=str(ruta_temporal))
    await update.message.reply_text("Procesando verificación facial…")

    try:
        resultado = await asyncio.to_thread(
            verificar_rostro,
            Path(usuario["ruta_referencia"]),
            ruta_temporal,
            usuario["modelo_utilizado"] or FACE_MODEL
        )

        if resultado["verificado"]:
            registrar_intento(
                telegram_id=telegram_id,
                usuario_id=usuario["id"],
                resultado="EXITOSO",
                distancia=resultado["distancia"],
                motivo="Coincidencia facial dentro del umbral"
            )
            informacion = obtener_informacion_autorizada(usuario["nivel_acceso"])
            await update.message.reply_text(
                "✅ Identidad verificada. Acceso permitido.\n\n"
                + formatear_informacion(informacion, solo_privada=True)
                + f"\n\nDistancia: {resultado['distancia']:.4f} | "
                  f"Umbral: {resultado['umbral']:.4f}"
            )
        else:
            registrar_intento(
                telegram_id=telegram_id,
                usuario_id=usuario["id"],
                resultado="RECHAZADO",
                distancia=resultado["distancia"],
                motivo="El rostro no coincide"
            )
            await update.message.reply_text(
                "❌ El rostro no coincide. Acceso rechazado.\n"
                f"Distancia: {resultado['distancia']:.4f} | "
                f"Umbral: {resultado['umbral']:.4f}"
            )
    except Exception as error:
        logger.exception("Error durante la verificación facial")
        registrar_intento(
            telegram_id=telegram_id,
            usuario_id=usuario["id"] if usuario else None,
            resultado="ERROR",
            motivo=str(error)[:250]
        )
        await update.message.reply_text(
            "No se pudo procesar la imagen. Asegúrate de que contenga un rostro "
            "claro y vuelve a intentarlo con /privada."
        )
    finally:
        context.user_data.clear()
        ruta_temporal.unlink(missing_ok=True)


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Proceso cancelado.")


async def post_init(aplicacion):
    await aplicacion.bot.delete_webhook(drop_pending_updates=True)
    datos_bot = await aplicacion.bot.get_me()
    configurar_bot(datos_bot.username)
    logger.info("Bot disponible en https://t.me/%s", datos_bot.username)


async def manejar_error(update, context):
    logger.exception("Error no controlado", exc_info=context.error)


def main():
    if not TOKEN:
        raise ValueError("Falta configurar TELEGRAM_BOT_TOKEN")

    crear_base_datos()
    sembrar_informacion_inicial()

    Thread(target=iniciar_servidor_web, daemon=True).start()

    aplicacion = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .concurrent_updates(False)
        .build()
    )

    aplicacion.add_handler(CommandHandler("start", start))
    aplicacion.add_handler(CommandHandler("ayuda", start))
    aplicacion.add_handler(CommandHandler("id", mostrar_id))
    aplicacion.add_handler(CommandHandler("publica", informacion_publica))
    aplicacion.add_handler(CommandHandler("registrar", registrar))
    aplicacion.add_handler(CommandHandler("privada", solicitar_privada))
    aplicacion.add_handler(CommandHandler("cancelar", cancelar))
    aplicacion.add_handler(MessageHandler(filters.PHOTO, recibir_foto))
    aplicacion.add_error_handler(manejar_error)

    logger.info("Bot y página pública iniciados")
    aplicacion.run_polling()


if __name__ == "__main__":
    main()
