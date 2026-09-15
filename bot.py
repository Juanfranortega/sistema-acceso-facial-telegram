import os
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

from deepface import DeepFace

os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

FOTO_DE_REFERENCIA = "rostros/referencias/referencia1.jpeg" 


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Identifiquese con una foto"
    )


async def manejar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje_espera = await update.message.reply_text("Foto recibida, por favor espera...")

   
    os.makedirs("temp", exist_ok=True)
    ruta_temporal = "temp/foto_recibida.jpg"
    
    archivo_foto = await update.message.photo[-1].get_file()
    await archivo_foto.download_to_drive(ruta_temporal)

    try:
        resultado = DeepFace.verify(
            img1_path=ruta_temporal,
            img2_path=FOTO_DE_REFERENCIA,
            model_name="Facenet512", 
            enforce_detection=False  
        )

        es_mismo = resultado["verified"]
        distancia = resultado["distance"]

        if es_mismo:
            await mensaje_espera.edit_text(f"Acceso concedido")
        else:
            await mensaje_espera.edit_text(f"Acceso denegado")

    except Exception as e:
        await mensaje_espera.edit_text(f"Hubo un error al analizar la foto")

    finally:
        if os.path.exists(ruta_temporal):
            os.remove(ruta_temporal)


def main():
    if not TOKEN:
        raise ValueError("No se encontró el token en el archivo .env")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, manejar_foto))

    print("Bot encendido...")
    app.run_polling()


if __name__ == "__main__":
    main()