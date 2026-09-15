# Sistema de acceso facial mediante Telegram

Prueba de concepto que integra Telegram, Python, DeepFace y SQLite para
proteger la consulta de información empresarial.

## Funciones de la demostración

- Página pública de estado.
- Consulta de información general desde Telegram.
- Registro controlado de un usuario y su rostro de referencia.
- Comparación facial antes de mostrar información privada.
- Registro de accesos exitosos, rechazados y errores.

## Ejecución local

1. Crear y activar un entorno virtual.
2. Instalar dependencias con `pip install -r requirements.txt`.
3. Copiar `.env.example` como `.env` y configurar los valores.
4. Ejecutar `python bot.py`.
5. Abrir `http://localhost:7860`.

## Publicación

La guía [DESPLIEGUE_RAILWAY.md](DESPLIEGUE_RAILWAY.md) explica cómo conectar
el repositorio de GitHub, configurar los secretos y obtener el enlace público.

## Variables requeridas

- `TELEGRAM_BOT_TOKEN`: token generado por BotFather.
- `TELEGRAM_BOT_USERNAME`: nombre del bot sin `@`.
- `REGISTRATION_CODE`: clave privada utilizada durante la demostración.
- `FACE_MODEL`: modelo de DeepFace; para despliegue se recomienda `SFace`.
- `APP_DATA_DIR`: directorio persistente de la aplicación.
- `DATABASE_PATH`: ubicación del archivo SQLite.

## Demostración en Telegram

1. Enviar `/registrar CLAVE Nombre completo`.
2. Enviar una fotografía de referencia autorizada.
3. Enviar `/privada`.
4. Enviar una fotografía diferente de la misma persona.
5. Repetir con una persona distinta para comprobar el rechazo.

No se deben guardar tokens, bases de datos reales ni fotografías personales
en el repositorio. El proyecto es una prueba académica y no sustituye un
sistema biométrico empresarial con detección de vida.
