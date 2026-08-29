import os
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)


load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    usuario = update.effective_user

    await update.message.reply_text(
        f"¡Hola, {usuario.first_name}! 👋\n\n"
        "Bienvenido al sistema de autenticación empresarial.\n"
        "Para continuar, próximamente deberás verificar tu identidad."
    )

def main():
    if not TOKEN:
        raise ValueError(
            "No se encontró TELEGRAM_BOT_TOKEN en el archivo .env"
        )

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    print("Bot iniciado correctamente...")
    print("Esperando mensajes de Telegram...")

    app.run_polling()


if __name__ == "__main__":
    main()