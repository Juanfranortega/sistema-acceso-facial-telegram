import asyncio
import logging
import os
from pathlib import Path
from threading import Thread
from uuid import uuid4
from deepface import DeepFace

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
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
    obtener_estado_contrasena,
    guardar_hash_contrasena,
    cambiar_estado_usuario,
    cambiar_rol_usuario,
    restablecer_contrasena_usuario,
    listar_usuarios,
    registrar_intento,
    registrar_perfil_facial,
    obtener_historial_autenticacion,
    obtener_historial_administrativo,
    registrar_usuario,
    contar_intentos_contrasena_fallidos,
    crear_usuario_nuevo,
    actualizar_datos_usuario,
    registrar_accion_administrativa,
    solicitar_actualizacion_facial,
    obtener_solicitud_actualizacion_facial,
    confirmar_actualizacion_facial,
    cancelar_actualizacion_facial,
    actualizar_perfil_facial_solicitado
)

from seguridad import (  # noqa: E402
    generar_hash_contrasena,
    verificar_contrasena
)

from init_db import crear_base_datos, sembrar_informacion_inicial  # noqa: E402
from reconocimiento import verificar_rostro  # noqa: E402
from web_app import configurar_bot, iniciar_servidor_web  # noqa: E402
import re

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

def crear_menu_principal(usuario):
    botones = [
        [
            InlineKeyboardButton(
                "📄 Información pública",
                callback_data="publica"
            )
        ],
        [
            InlineKeyboardButton(
                "🔐 Mis documentos",
                callback_data="privada"
            )
        ],
        [
            InlineKeyboardButton(
                "👤 Mi perfil",
                callback_data="perfil"
            )
        ],
        [
            InlineKeyboardButton(
                "❓ Ayuda",
                callback_data="ayuda"
            )
        ]
    ]

    if usuario["rol"] == "ADMIN":
        botones.append([
            InlineKeyboardButton(
                "⚙️ Panel de administración",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(botones)


def crear_boton_volver():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬅️ Menú principal",
                callback_data="menu"
            )
        ]
    ])


def crear_menu_administracion():
    botones = [
        [
            InlineKeyboardButton(
                "➕ Agregar usuario",
                callback_data="admin_agregar_usuario"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 Gestionar usuarios",
                callback_data="admin_usuarios"
            )
        ],
        [
            InlineKeyboardButton(
                "📁 Gestionar documentos",
                callback_data="admin_documentos"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Historial de accesos",
                callback_data="admin_historial"
            )
        ],

        [
            InlineKeyboardButton(
                "📝 Historial administrativo",
                callback_data="admin_historial_administrativo"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Menú principal",
                callback_data="menu"
            )
        ]
    ]

    return InlineKeyboardMarkup(botones)


async def manejar_boton(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    consulta = update.callback_query
    await consulta.answer()

    telegram_id = update.effective_user.id
    usuario = buscar_usuario_por_telegram(telegram_id)
    opcion = consulta.data

    if not context.user_data.get("sesion_autenticada"):
        await consulta.edit_message_text(
            "🔒 Tu sesión no está iniciada.\n\n"
            "Utiliza /start para iniciar sesión."
        )
        return

    if opcion == "editar_mi_perfil":

        if usuario is None or not usuario["activo"]:
            await consulta.edit_message_text(
                "⛔ Tu cuenta no está registrada o está inactiva."
            )
            return

        context.user_data["estado_edicion_perfil"] = "nombre"
        context.user_data["perfil_edicion_usuario_id"] = usuario["id"]
        context.user_data["perfil_edicion_nombre_actual"] = usuario["nombre"]
        context.user_data["perfil_edicion_correo_actual"] = usuario["correo"]

        await consulta.edit_message_text(
            "✏️ EDITAR MI PERFIL\n\n"
            f"Nombre actual: {usuario['nombre']}\n"
            f"Correo actual: {usuario['correo'] or 'No registrado'}\n\n"
            "Escribe tu nuevo nombre completo.\n"
            "Si deseas conservar el actual, escribe NO.\n\n"
            "Para cancelar el proceso, utiliza /cancelar."
        )
        return

    if opcion.startswith("editar_usuario|"):

        administrador = buscar_usuario_por_telegram(telegram_id)

        if (
            administrador is None
            or not administrador["activo"]
            or administrador["rol"] != "ADMIN"
        ):
            await consulta.edit_message_text(
                "⛔ No tienes autorización para editar usuarios."
            )
            return

        try:
            _, id_texto = opcion.split("|", 1)
            usuario_objetivo_id = int(id_texto)

            if usuario_objetivo_id <= 0:
                raise ValueError

        except (ValueError, TypeError):
            await consulta.edit_message_text(
                "La operación solicitada no es válida."
            )
            return

        usuarios = listar_usuarios()

        objetivo = next(
            (
                u for u in usuarios
                if u["id"] == usuario_objetivo_id
            ),
            None
        )

        if objetivo is None:
            await consulta.edit_message_text(
                "No se encontró la cuenta seleccionada."
            )
            return

        if objetivo["telegram_id"] == telegram_id:
            await consulta.edit_message_text(
                "⛔ No puedes modificar tu propia cuenta "
                "desde esta opción."
            )
            return

        context.user_data["estado_edicion_usuario_admin"] = "nombre"

        context.user_data["usuario_edicion_admin_objetivo_id"] = (
            objetivo["id"]
        )

        context.user_data["usuario_edicion_admin_nombre_actual"] = (
            objetivo["nombre"]
        )

        context.user_data["usuario_edicion_admin_correo_actual"] = (
            objetivo["correo"]
        )

        await consulta.edit_message_text(
            "✏️ EDICIÓN DE USUARIO\n\n"
            f"Usuario: {objetivo['nombre']}\n"
            f"Correo actual: {objetivo['correo'] or 'No registrado'}\n\n"
            "Escribe el nuevo nombre del usuario.\n"
            "Escribe NO para conservar el nombre actual.\n\n"
            "Para cancelar, utiliza /cancelar."
        )
        return

    if opcion.startswith("estado|"):
        if (
            not context.user_data.get("sesion_autenticada")
            or usuario is None
            or not usuario["activo"]
            or usuario["rol"] != "ADMIN"
        ):
            await consulta.edit_message_text(
                "⛔ No tienes autorización para cambiar estados."
            )
            return

        try:
            _, id_texto, estado_texto = opcion.split("|", 2)
            usuario_objetivo_id = int(id_texto)
            nuevo_estado = int(estado_texto)

            if usuario_objetivo_id <= 0 or nuevo_estado not in (0, 1):
                raise ValueError

        except (ValueError, TypeError):
            await consulta.edit_message_text(
                "La operación solicitada no es válida."
            )
            return

        usuarios = listar_usuarios()

        objetivo = next(
            (
                u for u in usuarios
                if u["id"] == usuario_objetivo_id
            ),
            None
        )

        if objetivo is None:
            await consulta.edit_message_text(
                "No se encontró la cuenta seleccionada."
            )
            return

        if objetivo["telegram_id"] == telegram_id:
            await consulta.edit_message_text(
                "⛔ No puedes cambiar el estado de tu propia cuenta."
            )
            return

        if objetivo["activo"] == nuevo_estado:
            await consulta.edit_message_text(
                "La cuenta ya tiene el estado solicitado."
            )
            return

        context.user_data.pop("accion_foto", None)
        context.user_data["accion_foto"] = "admin_cambiar_estado"
        context.user_data["usuario_estado_objetivo"] = usuario_objetivo_id
        context.user_data["nuevo_estado_usuario"] = nuevo_estado

        operacion = "desactivar" if nuevo_estado == 0 else "activar"

        await consulta.edit_message_text(
            f"🔐 Vas a {operacion} la cuenta de "
            f"{objetivo['nombre']}.\n\n"
            "Para confirmar la operación, envía una fotografía "
            "de tu rostro para verificar tu identidad.\n\n"
            "Si no deseas continuar, utiliza /cancelar.",
            reply_markup=crear_boton_volver()
        )
        return

    if opcion.startswith("rol|"):
        if (
            usuario is None
            or not usuario["activo"]
            or usuario["rol"] != "ADMIN"
        ):
            await consulta.edit_message_text(
                "⛔ No tienes autorización para cambiar roles."
            )
            return

        try:
            _, id_texto = opcion.split("|", 1)
            usuario_objetivo_id = int(id_texto)

            if usuario_objetivo_id <= 0:
                raise ValueError

        except (ValueError, TypeError):
            await consulta.edit_message_text(
                "La operación solicitada no es válida."
            )
            return

        usuarios = listar_usuarios()

        objetivo = next(
            (
                u for u in usuarios
                if u["id"] == usuario_objetivo_id
            ),
            None
        )

        if objetivo is None:
            await consulta.edit_message_text(
                "No se encontró la cuenta seleccionada."
            )
            return

        if objetivo["telegram_id"] == telegram_id:
            await consulta.edit_message_text(
                "⛔ No puedes cambiar el rol de tu propia cuenta."
            )
            return

        teclado = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👤 EMPLEADO - Nivel 1",
                    callback_data=(
                        f"rol_nuevo|{usuario_objetivo_id}|EMPLEADO"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "💼 EJECUTIVO - Nivel 2",
                    callback_data=(
                        f"rol_nuevo|{usuario_objetivo_id}|EJECUTIVO"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🛡️ ADMIN - Nivel 3",
                    callback_data=(
                        f"rol_nuevo|{usuario_objetivo_id}|ADMIN"
                    )
                )
            ]
        ])

        await consulta.edit_message_text(
            f"👤 Usuario: {objetivo['nombre']}\n"
            f"Rol actual: {objetivo['rol']}\n"
            f"Nivel de acceso actual: {objetivo['nivel_acceso']}\n\n"
            "Selecciona el nuevo rol.\n\n"
            "El cambio requerirá una verificación facial.\n"
            "Para cancelar, utiliza /cancelar.",
            reply_markup=teclado
        )
        return

    if opcion.startswith("rol_nuevo|"):
        if (
            usuario is None
            or not usuario["activo"]
            or usuario["rol"] != "ADMIN"
        ):
            await consulta.edit_message_text(
                "⛔ No tienes autorización para cambiar roles."
            )
            return

        try:
            _, id_texto, nuevo_rol = opcion.split("|", 2)
            usuario_objetivo_id = int(id_texto)
            nuevo_rol = nuevo_rol.upper()

            if (
                usuario_objetivo_id <= 0
                or nuevo_rol not in {
                    "EMPLEADO", "EJECUTIVO", "ADMIN"
                }
            ):
                raise ValueError

        except (ValueError, TypeError):
            await consulta.edit_message_text(
                "La operación solicitada no es válida."
            )
            return

        usuarios = listar_usuarios()

        objetivo = next(
            (
                u for u in usuarios
                if u["id"] == usuario_objetivo_id
            ),
            None
        )

        if objetivo is None:
            await consulta.edit_message_text(
                "No se encontró la cuenta seleccionada."
            )
            return

        if objetivo["telegram_id"] == telegram_id:
            await consulta.edit_message_text(
                "⛔ No puedes cambiar el rol de tu propia cuenta."
            )
            return

        if objetivo["rol"] == nuevo_rol:
            await consulta.edit_message_text(
                "La cuenta ya tiene el rol seleccionado."
            )
            return

        niveles_por_rol = {
            "EMPLEADO": 1,
            "EJECUTIVO": 2,
            "ADMIN": 3
        }

        # Evita solicitar la verificación si el cambio
        # dejaría al sistema sin administradores activos.
        if (
            objetivo["rol"] == "ADMIN"
            and objetivo["activo"]
            and nuevo_rol != "ADMIN"
        ):
            administradores_activos = sum(
                1 for u in usuarios
                if u["rol"] == "ADMIN" and u["activo"]
            )

            if administradores_activos <= 1:
                await consulta.edit_message_text(
                    "⛔ No puedes quitar el rol ADMIN "
                    "al último administrador activo."
                )
                return

        context.user_data.pop("accion_foto", None)

        context.user_data["accion_foto"] = "admin_cambiar_rol"
        context.user_data["usuario_rol_objetivo"] = usuario_objetivo_id
        context.user_data["nuevo_rol_usuario"] = nuevo_rol

        await consulta.edit_message_text(
            f"🔐 CONFIRMACIÓN DE CAMBIO DE ROL\n\n"
            f"Usuario: {objetivo['nombre']}\n"
            f"Rol actual: {objetivo['rol']}\n"
            f"Nuevo rol: {nuevo_rol}\n"
            f"Nuevo nivel de acceso: {niveles_por_rol[nuevo_rol]}\n\n"
            "Envía una fotografía de tu rostro para verificar "
            "tu identidad y confirmar el cambio.\n\n"
            "Si no deseas continuar, utiliza /cancelar.",
            reply_markup=crear_boton_volver()
        )
        return

    if opcion.startswith("clave|"):
        if (
            usuario is None
            or not usuario["activo"]
            or usuario["rol"] != "ADMIN"
        ):
            await consulta.edit_message_text(
                "⛔ No tienes autorización para restablecer contraseñas."
            )
            return

        try:
            _, id_texto = opcion.split("|", 1)
            usuario_objetivo_id = int(id_texto)

            if usuario_objetivo_id <= 0:
                raise ValueError

        except (ValueError, TypeError):
            await consulta.edit_message_text(
                "La operación solicitada no es válida."
            )
            return

        usuarios = listar_usuarios()

        objetivo = next(
            (
                u for u in usuarios
                if u["id"] == usuario_objetivo_id
            ),
            None
        )

        if objetivo is None:
            await consulta.edit_message_text(
                "No se encontró la cuenta seleccionada."
            )
            return

        if objetivo["telegram_id"] == telegram_id:
            await consulta.edit_message_text(
                "⛔ No puedes restablecer tu propia contraseña "
                "desde esta opción."
            )
            return

        context.user_data.pop("accion_foto", None)
        context.user_data["accion_foto"] = "admin_restablecer_clave"
        context.user_data["usuario_clave_objetivo"] = usuario_objetivo_id

        await consulta.edit_message_text(
            "🔐 RESTABLECIMIENTO DE CONTRASEÑA\n\n"
            f"Usuario: {objetivo['nombre']}\n"
            f"Rol: {objetivo['rol']}\n\n"
            "Al confirmar tu identidad mediante reconocimiento facial, "
            "la contraseña anterior quedará invalidada y el usuario "
            "deberá configurar una nueva.\n\n"
            "Envía una fotografía de tu rostro para confirmar.\n"
            "Si no deseas continuar, utiliza /cancelar.",
            reply_markup=crear_boton_volver()
        )
        return

    if opcion.startswith("rostro|"):
        if (
            usuario is None
            or not usuario["activo"]
            or usuario["rol"] != "ADMIN"
        ):
            await consulta.edit_message_text(
                "⛔ No tienes autorización para actualizar "
                "fotografías faciales."
            )
            return

        try:
            _, id_texto = opcion.split("|", 1)
            usuario_objetivo_id = int(id_texto)

            if usuario_objetivo_id <= 0:
                raise ValueError

        except (ValueError, TypeError):
            await consulta.edit_message_text(
                "La operación solicitada no es válida."
            )
            return

        usuarios = listar_usuarios()

        objetivo = next(
            (
                u for u in usuarios
                if u["id"] == usuario_objetivo_id
            ),
            None
        )

        if objetivo is None:
            await consulta.edit_message_text(
                "No se encontró la cuenta seleccionada."
            )
            return

        if objetivo["telegram_id"] == telegram_id:
            await consulta.edit_message_text(
                "⛔ No puedes actualizar tu propia fotografía "
                "desde esta opción."
            )
            return

        if not objetivo["activo"] or not objetivo["tiene_perfil_facial"]:
            await consulta.edit_message_text(
                "El usuario debe tener una cuenta activa "
                "y una fotografía facial registrada."
            )
            return

        context.user_data.pop("accion_foto", None)

        context.user_data["accion_foto"] = "admin_actualizar_rostro"
        context.user_data["usuario_rostro_objetivo"] = (
            usuario_objetivo_id
        )

        await consulta.edit_message_text(
            "📸 ACTUALIZACIÓN DE FOTOGRAFÍA FACIAL\n\n"
            f"Usuario: {objetivo['nombre']}\n"
            f"Rol: {objetivo['rol']}\n\n"
            "Para autorizar la actualización, envía una "
            "fotografía de tu rostro para verificar tu identidad.\n\n"
            "El usuario deberá confirmar su contraseña actual "
            "antes de registrar una nueva fotografía.\n\n"
            "Para cancelar, utiliza /cancelar.",
            reply_markup=crear_boton_volver()
        )
        return

    if opcion == "menu":
        campos_temporales = [
            "accion_foto",
            "estado_alta_usuario",
            "estado_alta_rostro",
            "nuevo_usuario_telegram_id",
            "nuevo_usuario_nombre",
            "nuevo_usuario_rol",
            "nuevo_usuario_correo",
            "usuario_estado_objetivo",
            "nuevo_estado_usuario",
            "usuario_rol_objetivo",
            "nuevo_rol_usuario",
            "usuario_rostro_objetivo",
            "perfil_edicion_nombre_actual",
            "perfil_edicion_correo_actual",
            "estado_edicion_usuario_admin",
            "usuario_edicion_admin_objetivo_id",
            "usuario_edicion_admin_nombre_actual",
            "usuario_edicion_admin_correo_actual",
            "usuario_edicion_admin_nombre_nuevo",
            "estado_edicion_perfil",
            "perfil_edicion_usuario_id",
            "perfil_edicion_nombre_nuevo",
            "usuario_clave_objetivo"
        ]

        for campo in campos_temporales:
            context.user_data.pop(campo, None)

        if usuario is None or not usuario["activo"]:
            await consulta.edit_message_text(
                "⛔ Tu cuenta no está registrada o está inactiva."
            )
            return

        await consulta.edit_message_text(
            f"¡Bienvenido, {usuario['nombre']}! 👋\n\n"
            f"Rol: {usuario['rol']}\n"
            "Selecciona una opción:",
            reply_markup=crear_menu_principal(usuario)
        )
        return

    if usuario is None or not usuario["activo"]:
        context.user_data.clear()
        await consulta.edit_message_text(
            "⛔ Tu cuenta no está registrada o está inactiva."
        )
        return

    if opcion == "publica":
        context.user_data.pop("accion_foto", None)

        registros = obtener_informacion_autorizada(0)

        await consulta.edit_message_text(
            formatear_informacion(registros),
            reply_markup=crear_boton_volver()
        )
        return

    if opcion == "ayuda":
        context.user_data.pop("accion_foto", None)

        await consulta.edit_message_text(
            "❓ AYUDA\n\n"
            "• Información pública: consulta información general.\n"
            "• Mis documentos: verifica tu rostro para consultar "
            "información privada.\n"
            "• Mi perfil: verifica tu rostro antes de consultar "
            "tus datos.\n"
            "• Panel de administración: opción exclusiva para ADMIN.",
            reply_markup=crear_boton_volver()
        )
        return

    acciones = {
        "privada": (
            "documentos",
            "🔐 Para consultar tus documentos, envía una fotografía "
            "de tu rostro para verificar tu identidad."
        ),
        "perfil": (
            "perfil",
            "👤 Para consultar tu perfil, envía una fotografía "
            "de tu rostro para verificar tu identidad."
        ),
        "admin": (
            "admin",
            "🔐 Panel administrativo. Envía una fotografía de tu "
            "rostro para verificar tu identidad."
        ),
        "admin_agregar_usuario": (
            "admin_agregar_usuario",
            "Para continuar con el alta de usuarios, verifica tu "
            "identidad enviando una fotografía de tu rostro."
        ),
        "admin_usuarios": (
            "admin_usuarios",
            "Para gestionar usuarios, verifica tu identidad "
            "enviando una fotografía de tu rostro."
        ),
        "admin_documentos": (
            "admin_documentos",
            "Para gestionar documentos, verifica tu identidad "
            "enviando una fotografía de tu rostro."
        ),
        "admin_historial": (
            "admin_historial",
            "Para consultar el historial, verifica tu identidad "
            "enviando una fotografía de tu rostro."
        ),
        "admin_historial_administrativo": (
            "admin_historial_administrativo",
            "Para consultar el historial administrativo, verifica "
            "tu identidad enviando una fotografía de tu rostro."
        )
    }

    if opcion not in acciones:
        await consulta.edit_message_text(
            "Opción no reconocida.",
            reply_markup=crear_boton_volver()
        )
        return

    if opcion.startswith("admin") and usuario["rol"] != "ADMIN":
        context.user_data.clear()
        await consulta.edit_message_text(
            "⛔ No tienes permisos para acceder a las funciones administrativas."
        )
        return

    ruta_referencia = usuario["ruta_referencia"]

    if not ruta_referencia or not Path(ruta_referencia).is_file():
        context.user_data.clear()
        await consulta.edit_message_text(
            "No tienes una fotografía de referencia válida. "
            "Contacta al administrador."
        )
        return

    context.user_data.pop("accion_foto", None)

    accion, mensaje = acciones[opcion]
    context.user_data["accion_foto"] = accion

    await consulta.edit_message_text(
        mensaje,
        reply_markup=crear_boton_volver()
    )



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    # Cada /start requiere iniciar sesión nuevamente.
    context.user_data.clear()

    usuario = obtener_estado_contrasena(telegram_id)

    if usuario is None or not usuario["activo"]:
        await update.message.reply_text(
            "⛔ Tu cuenta no está registrada o se encuentra inactiva.\n\n"
            "Contacta al administrador para solicitar acceso. "
            "Puedes consultar tu identificador con /id."
        )
        return

    if usuario["debe_configurar_clave"] or not usuario["password_hash"]:
        context.user_data["estado_autenticacion"] = "configurar"

        mensaje_inicio = await update.message.reply_text(
            f"¡Bienvenido, {usuario['nombre']}! 👋\n\n"
            "🔐 Antes de continuar, debes configurar tu contraseña.\n"
            "Escribe una contraseña de al menos 12 caracteres.\n\n"
            "El bot intentará eliminar el mensaje que contiene tu "
            "contraseña, pero escribir contraseñas en Telegram "
            "no es la opción más segura."
        )
        context.user_data["mensaje_autenticacion_id"] = mensaje_inicio.message_id
        return

    context.user_data["estado_autenticacion"] = "iniciar"

    mensaje_inicio = await update.message.reply_text(
        f"¡Bienvenido, {usuario['nombre']}! 👋\n\n"
        "🔐 Escribe tu contraseña para iniciar sesión.\n\n"
        "Tu contraseña no se mostrará en la respuesta del bot."
    )
    context.user_data["mensaje_autenticacion_id"] = mensaje_inicio.message_id

async def continuar_actualizacion_facial(update, context, telegram_id):
    solicitud = obtener_solicitud_actualizacion_facial(telegram_id)

    # No existe una solicitud pendiente.
    if not solicitud:
        return False

    estado_solicitud = solicitud["estado"]

    # El usuario ya inició sesión y debe confirmar su contraseña.
    if estado_solicitud == "ESPERANDO_CLAVE":

        if not confirmar_actualizacion_facial(telegram_id):
            await update.effective_message.reply_text(
                "No fue posible confirmar la solicitud de actualización facial. "
                "Es posible que haya expirado o cambiado."
            )
            return True

    # La contraseña ya fue confirmada anteriormente.
    elif estado_solicitud != "ESPERANDO_FOTO":
        return False

    context.user_data.pop("estado_autenticacion", None)
    context.user_data["sesion_autenticada"] = True

    texto_confirmacion = (
        "✅ Contraseña confirmada correctamente.\n\n"
        "Ahora envía tu nueva fotografía facial para actualizar tu perfil.\n"
        "Tienes 10 minutos para completar este paso.\n\n"
        "Si deseas cancelar el proceso, utiliza /cancelar."
    )

    mensaje_id = context.user_data.pop(
        "mensaje_autenticacion_id",
        None
    )

    if mensaje_id:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=mensaje_id,
                text=texto_confirmacion
            )

        except Exception:
            logger.warning(
                "No se pudo editar el mensaje de autenticación. "
                "Se enviará una nueva respuesta.",
                exc_info=True
            )

            await update.effective_message.reply_text(
                texto_confirmacion
            )

    else:
        await update.effective_message.reply_text(
            texto_confirmacion
        )

    return True

async def manejar_texto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    mensaje = update.message

    estado_alta = context.user_data.get("estado_alta_usuario")

    if estado_alta == "telegram_id":
        administrador = buscar_usuario_por_telegram(
            update.effective_user.id
        )

        if (
            not context.user_data.get("sesion_autenticada")
            or administrador is None
            or not administrador["activo"]
            or administrador["rol"] != "ADMIN"
        ):
            context.user_data.pop("estado_alta_usuario", None)
            context.user_data.pop("nuevo_usuario_telegram_id", None)

            await mensaje.reply_text(
                "⛔ No tienes autorización para registrar usuarios."
            )
            return

        texto_id = mensaje.text.strip()

        if not texto_id.isdecimal() or int(texto_id) <= 0:
            await mensaje.reply_text(
                "El Telegram ID debe ser un número positivo. "
                "Inténtalo nuevamente."
            )
            return

        nuevo_telegram_id = int(texto_id)

        if buscar_usuario_por_telegram(nuevo_telegram_id) is not None:
            await mensaje.reply_text(
                "⚠️ Ese Telegram ID ya está registrado. "
                "Introduce otro identificador."
            )
            return

        context.user_data["nuevo_usuario_telegram_id"] = (
            nuevo_telegram_id
        )
        context.user_data["estado_alta_usuario"] = "nombre"

        await mensaje.reply_text(
            "✅ Telegram ID validado.\n\n"
            "Ahora escribe el nombre completo del nuevo usuario."
        )
        return

    if estado_alta == "nombre":
        administrador = buscar_usuario_por_telegram(
            update.effective_user.id
        )

        if (
            not context.user_data.get("sesion_autenticada")
            or administrador is None
            or not administrador["activo"]
            or administrador["rol"] != "ADMIN"
        ):
            context.user_data.pop("estado_alta_usuario", None)
            context.user_data.pop("nuevo_usuario_telegram_id", None)
            context.user_data.pop("nuevo_usuario_nombre", None)

            await mensaje.reply_text(
                "⛔ No tienes autorización para registrar usuarios."
            )
            return

        nombre = mensaje.text.strip()

        if not nombre or len(nombre) > 100:
            await mensaje.reply_text(
                "El nombre no puede estar vacío ni superar "
                "los 100 caracteres. Inténtalo nuevamente."
            )
            return

        context.user_data["nuevo_usuario_nombre"] = nombre
        context.user_data["estado_alta_usuario"] = "rol"

        await mensaje.reply_text(
            "✅ Nombre registrado.\n\n"
            "Ahora escribe el rol que tendrá el usuario:\n\n"
            "• EMPLEADO\n"
            "• EJECUTIVO\n"
            "• ADMIN"
        )
        return

    if estado_alta == "rol":
        administrador = buscar_usuario_por_telegram(
            update.effective_user.id
        )

        if (
            not context.user_data.get("sesion_autenticada")
            or administrador is None
            or not administrador["activo"]
            or administrador["rol"] != "ADMIN"
        ):
            context.user_data.pop("estado_alta_usuario", None)
            context.user_data.pop("nuevo_usuario_telegram_id", None)
            context.user_data.pop("nuevo_usuario_nombre", None)

            await mensaje.reply_text(
                "⛔ No tienes autorización para registrar usuarios."
            )
            return

        rol = mensaje.text.strip().upper()

        roles_validos = {"EMPLEADO", "EJECUTIVO", "ADMIN"}

        if rol not in roles_validos:
            await mensaje.reply_text(
                "⚠️ El rol indicado no es válido.\n\n"
                "Escribe uno de los siguientes:\n"
                "• EMPLEADO\n"
                "• EJECUTIVO\n"
                "• ADMIN"
            )
            return

        context.user_data["nuevo_usuario_rol"] = rol
        context.user_data["estado_alta_usuario"] = "correo"

        await mensaje.reply_text(
            f"✅ Rol seleccionado: {rol}\n\n"
            "Ahora escribe el correo electrónico del usuario.\n"
            "Si no deseas registrar uno, escribe NO."
        )
        return

    if estado_alta == "correo":
        administrador = buscar_usuario_por_telegram(
            update.effective_user.id
        )

        if (
            not context.user_data.get("sesion_autenticada")
            or administrador is None
            or not administrador["activo"]
            or administrador["rol"] != "ADMIN"
        ):
            context.user_data.pop("estado_alta_usuario", None)
            context.user_data.pop("nuevo_usuario_telegram_id", None)
            context.user_data.pop("nuevo_usuario_nombre", None)
            context.user_data.pop("nuevo_usuario_rol", None)

            await mensaje.reply_text(
                "⛔ No tienes autorización para registrar usuarios."
            )
            return

        texto_correo = mensaje.text.strip()

        if texto_correo.upper() in {"NO", "N"}:
            correo = None
        elif (
            len(texto_correo) <= 254
            and re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                texto_correo
            )
        ):
            correo = texto_correo
        else:
            await mensaje.reply_text(
                "⚠️ El correo no tiene un formato válido.\n"
                "Escribe un correo válido o responde NO."
            )
            return

        campos_requeridos = (
            "nuevo_usuario_telegram_id",
            "nuevo_usuario_nombre",
            "nuevo_usuario_rol"
        )

        if any(
            campo not in context.user_data
            for campo in campos_requeridos
        ):
            context.user_data.pop("estado_alta_usuario", None)

            await mensaje.reply_text(
                "El proceso de registro perdió algunos datos. "
                "Vuelve a iniciar el alta desde el panel administrativo."
            )
            return

        context.user_data["nuevo_usuario_correo"] = correo
        context.user_data["estado_alta_usuario"] = "confirmar"

        await mensaje.reply_text(
            "📋 CONFIRMA LOS DATOS DEL NUEVO USUARIO\n\n"
            f"Telegram ID: "
            f"{context.user_data['nuevo_usuario_telegram_id']}\n"
            f"Nombre: {context.user_data['nuevo_usuario_nombre']}\n"
            f"Rol: {context.user_data['nuevo_usuario_rol']}\n"
            f"Correo: {correo or 'No registrado'}\n\n"
            "Si los datos son correctos, escribe CONFIRMAR.\n"
            "Para cancelar, utiliza /cancelar."
        )
        return

    if estado_alta == "confirmar":
        administrador = buscar_usuario_por_telegram(
            update.effective_user.id
        )

        if (
            not context.user_data.get("sesion_autenticada")
            or administrador is None
            or not administrador["activo"]
            or administrador["rol"] != "ADMIN"
        ):
            context.user_data.pop("estado_alta_usuario", None)
            context.user_data.pop("nuevo_usuario_telegram_id", None)
            context.user_data.pop("nuevo_usuario_nombre", None)
            context.user_data.pop("nuevo_usuario_rol", None)
            context.user_data.pop("nuevo_usuario_correo", None)

            await mensaje.reply_text(
                "⛔ No tienes autorización para registrar usuarios."
            )
            return

        if mensaje.text.strip().upper() != "CONFIRMAR":
            await mensaje.reply_text(
                "Para crear la cuenta, escribe CONFIRMAR.\n"
                "Si deseas cancelar, utiliza /cancelar."
            )
            return

        telegram_nuevo = context.user_data.get(
            "nuevo_usuario_telegram_id"
        )
        nombre_nuevo = context.user_data.get("nuevo_usuario_nombre")
        rol_nuevo = context.user_data.get("nuevo_usuario_rol")
        correo_nuevo = context.user_data.get("nuevo_usuario_correo")

        if (
            telegram_nuevo is None
            or not nombre_nuevo
            or rol_nuevo not in {"EMPLEADO", "EJECUTIVO", "ADMIN"}
        ):
            context.user_data.pop("estado_alta_usuario", None)

            await mensaje.reply_text(
                "No se encontraron todos los datos del registro. "
                "Inicia nuevamente el alta."
            )
            return

        try:
            nuevo_id = crear_usuario_nuevo(
                telegram_id=telegram_nuevo,
                nombre=nombre_nuevo,
                rol=rol_nuevo,
                correo=correo_nuevo
            )

        except ValueError as error:
            await mensaje.reply_text(
                f"⚠️ No se pudo crear la cuenta: {error}\n\n"
                "Revisa los datos o cancela el proceso con /cancelar."
            )
            return

        except Exception:
            logger.exception("Error al crear un usuario nuevo")

            await mensaje.reply_text(
                "No se pudo crear la cuenta debido a un error interno. "
                "Revisa los registros del sistema."
            )
            return


        # Registrar el alta del nuevo usuario en el historial administrativo.
        try:
            registrar_accion_administrativa(
                responsable_telegram_id=update.effective_user.id,
                accion="ALTA_USUARIO",
                usuario_objetivo_id=nuevo_id,
                detalle=(
                    f"Se creó una nueva cuenta.\n"
                    f"Nombre: {nombre_nuevo}\n"
                    f"Telegram ID: {telegram_nuevo}\n"
                    f"Rol asignado: {rol_nuevo}\n"
                    f"Nivel de acceso: "
                    f"{ {'EMPLEADO': 1, 'EJECUTIVO': 2, 'ADMIN': 3}[rol_nuevo] }\n"
                    f"Correo: {correo_nuevo or 'No registrado'}"
                )
            )

        except Exception:
            logger.exception(
                "No se pudo registrar el alta del usuario %s "
                "en el historial administrativo.",
                nuevo_id
            )


        context.user_data.pop("estado_alta_usuario", None)
        context.user_data.pop("nuevo_usuario_telegram_id", None)
        context.user_data.pop("nuevo_usuario_nombre", None)
        context.user_data.pop("nuevo_usuario_rol", None)
        context.user_data.pop("nuevo_usuario_correo", None)

        await mensaje.reply_text(
            "✅ USUARIO REGISTRADO CORRECTAMENTE\n\n"
            f"ID interno: {nuevo_id}\n"
            f"Nombre: {nombre_nuevo}\n"
            f"Telegram ID: {telegram_nuevo}\n"
            f"Rol: {rol_nuevo}\n"
            f"Correo: {correo_nuevo or 'No registrado'}\n\n"
            "La cuenta está activa y debe configurar su contraseña "
            "al iniciar con /start.\n\n"
            "⚠️ Todavía falta registrar su fotografía de referencia "
            "para habilitar las operaciones que requieren "
            "reconocimiento facial.",
            reply_markup=crear_menu_administracion()
        )
        return

    # PROCESO DE EDICIÓN DEL PERFIL PERSONAL
    estado_edicion = context.user_data.get("estado_edicion_perfil")

    if estado_edicion in {"nombre", "correo"}:

        telegram_id = update.effective_user.id
        usuario_actual = buscar_usuario_por_telegram(telegram_id)

        usuario_objetivo_id = context.user_data.get(
            "perfil_edicion_usuario_id"
        )

        # Comprobar que el usuario solamente edite su propia cuenta.
        if (
            not context.user_data.get("sesion_autenticada")
            or usuario_actual is None
            or not usuario_actual["activo"]
            or usuario_actual["id"] != usuario_objetivo_id
        ):
            campos_edicion = (
                "estado_edicion_perfil",
                "perfil_edicion_usuario_id",
                "perfil_edicion_nombre_actual",
                "perfil_edicion_correo_actual",
                "perfil_edicion_nombre_nuevo"
            )

            for campo in campos_edicion:
                context.user_data.pop(campo, None)

            await mensaje.reply_text(
                "⛔ No tienes autorización para modificar este perfil."
            )
            return

        # PRIMER PASO: recibir el nuevo nombre.
        if estado_edicion == "nombre":

            texto_nombre = mensaje.text.strip()

            if texto_nombre.upper() == "NO":
                nombre_nuevo = context.user_data.get(
                    "perfil_edicion_nombre_actual"
                )

            elif not texto_nombre or len(texto_nombre) > 100:
                await mensaje.reply_text(
                    "⚠️ El nombre no puede estar vacío ni superar "
                    "los 100 caracteres.\n\n"
                    "Inténtalo nuevamente."
                )
                return

            else:
                nombre_nuevo = texto_nombre

            context.user_data["perfil_edicion_nombre_nuevo"] = (
                nombre_nuevo
            )

            context.user_data["estado_edicion_perfil"] = "correo"

            await mensaje.reply_text(
                f"✅ Nombre seleccionado: {nombre_nuevo}\n\n"
                "Ahora escribe tu nuevo correo electrónico.\n\n"
                "• Escribe NO para conservar el correo actual.\n"
                "• Escribe SIN CORREO para eliminarlo.\n"
                "• También puedes introducir un correo nuevo.\n\n"
                "Para cancelar, utiliza /cancelar."
            )
            return

        # SEGUNDO PASO: recibir el nuevo correo.
        if estado_edicion == "correo":

            texto_correo = mensaje.text.strip()

            if texto_correo.upper() == "NO":
                correo_nuevo = context.user_data.get(
                    "perfil_edicion_correo_actual"
                )

            elif texto_correo.upper() == "SIN CORREO":
                correo_nuevo = None

            elif (
                len(texto_correo) <= 254
                and re.fullmatch(
                    r"[^@\s]+@[^@\s]+\.[^@\s]+",
                    texto_correo
                )
            ):
                correo_nuevo = texto_correo

            else:
                await mensaje.reply_text(
                    "⚠️ El correo electrónico no tiene un formato válido.\n\n"
                    "Escribe un correo válido, NO o SIN CORREO."
                )
                return

            nombre_nuevo = context.user_data.get(
                "perfil_edicion_nombre_nuevo"
            )

            try:
                actualizado = actualizar_datos_usuario(
                    usuario_actual["id"],
                    nombre_nuevo,
                    correo_nuevo
                )

            except ValueError as error:
                await mensaje.reply_text(
                    f"⚠️ No se pudieron actualizar los datos:\n{error}\n\n"
                    "Puedes introducir otro correo o cancelar con /cancelar."
                )
                return

            except Exception:
                logger.exception(
                    "Error al actualizar el perfil del usuario %s.",
                    telegram_id
                )

                await mensaje.reply_text(
                    "No se pudo actualizar tu perfil debido "
                    "a un error interno. Inténtalo nuevamente."
                )
                return

            if not actualizado:
                campos_edicion = (
                    "estado_edicion_perfil",
                    "perfil_edicion_usuario_id",
                    "perfil_edicion_nombre_actual",
                    "perfil_edicion_correo_actual",
                    "perfil_edicion_nombre_nuevo"
                )

                for campo in campos_edicion:
                    context.user_data.pop(campo, None)

                await mensaje.reply_text(
                    "No se realizaron cambios en el perfil."
                )
                return

            # Registrar la modificación del perfil propio.
            nombre_anterior = context.user_data.get(
                "perfil_edicion_nombre_actual"
            )

            correo_anterior = context.user_data.get(
                "perfil_edicion_correo_actual"
            )

            try:
                registrar_accion_administrativa(
                    responsable_telegram_id=telegram_id,
                    accion="EDICION_PERFIL_PROPIO",
                    usuario_objetivo_id=usuario_actual["id"],
                    detalle=(
                        f"Nombre anterior: {nombre_anterior}\n"
                        f"Nombre nuevo: {nombre_nuevo}\n"
                        f"Correo anterior: {correo_anterior or 'No registrado'}\n"
                        f"Correo nuevo: {correo_nuevo or 'No registrado'}"
                    )
                )

            except Exception:
                logger.exception(
                    "No se pudo registrar la edición del perfil propio "
                    "del usuario %s.",
                    telegram_id
                )

            # Limpiar los datos temporales de edición.
            campos_edicion = (
                "estado_edicion_perfil",
                "perfil_edicion_usuario_id",
                "perfil_edicion_nombre_actual",
                "perfil_edicion_correo_actual",
                "perfil_edicion_nombre_nuevo"
            )

            for campo in campos_edicion:
                context.user_data.pop(campo, None)

            usuario_actual = buscar_usuario_por_telegram(telegram_id)

            await mensaje.reply_text(
                "✅ PERFIL ACTUALIZADO CORRECTAMENTE\n\n"
                f"Nombre: {usuario_actual['nombre']}\n"
                f"Correo: {usuario_actual['correo'] or 'No registrado'}\n"
                f"Rol: {usuario_actual['rol']}\n"
                f"Nivel de acceso: {usuario_actual['nivel_acceso']}\n\n"
                "Tus demás datos de seguridad permanecen sin cambios.",
                reply_markup=crear_boton_volver()
            )
            return

    # PROCESO DE EDICIÓN ADMINISTRATIVA DE USUARIOS
    estado_edicion_admin = context.user_data.get(
        "estado_edicion_usuario_admin"
    )

    if estado_edicion_admin in {"nombre", "correo"}:

        telegram_id = update.effective_user.id
        administrador = buscar_usuario_por_telegram(telegram_id)

        objetivo_id = context.user_data.get(
            "usuario_edicion_admin_objetivo_id"
        )

        # Comprobar que quien realiza la operación siga siendo ADMIN.
        if (
            not context.user_data.get("sesion_autenticada")
            or administrador is None
            or not administrador["activo"]
            or administrador["rol"] != "ADMIN"
        ):
            campos = (
                "estado_edicion_usuario_admin",
                "usuario_edicion_admin_objetivo_id",
                "usuario_edicion_admin_nombre_actual",
                "usuario_edicion_admin_correo_actual",
                "usuario_edicion_admin_nombre_nuevo"
            )

            for campo in campos:
                context.user_data.pop(campo, None)

            await mensaje.reply_text(
                "⛔ No tienes autorización para editar usuarios."
            )
            return

        # Recuperar nuevamente al usuario que se desea modificar.
        usuarios = listar_usuarios()

        objetivo = next(
            (
                u for u in usuarios
                if u["id"] == objetivo_id
            ),
            None
        )

        if objetivo is None or objetivo["telegram_id"] == telegram_id:
            context.user_data.clear()

            await mensaje.reply_text(
                "No se encontró una cuenta válida para modificar."
            )
            return

        # PRIMER PASO: recibir el nuevo nombre.
        if estado_edicion_admin == "nombre":

            texto_nombre = mensaje.text.strip()

            if texto_nombre.upper() == "NO":
                nombre_nuevo = context.user_data.get(
                    "usuario_edicion_admin_nombre_actual"
                )

            elif not texto_nombre or len(texto_nombre) > 100:
                await mensaje.reply_text(
                    "⚠️ El nombre no puede estar vacío ni superar "
                    "los 100 caracteres.\n\n"
                    "Inténtalo nuevamente."
                )
                return

            else:
                nombre_nuevo = texto_nombre

            context.user_data["usuario_edicion_admin_nombre_nuevo"] = (
                nombre_nuevo
            )

            context.user_data["estado_edicion_usuario_admin"] = "correo"

            await mensaje.reply_text(
                f"✅ Nombre seleccionado: {nombre_nuevo}\n\n"
                f"Ahora escribe el nuevo correo de "
                f"{objetivo['nombre']}.\n\n"
                "• Escribe NO para conservar el correo actual.\n"
                "• Escribe SIN CORREO para eliminarlo.\n"
                "• También puedes introducir un correo nuevo.\n\n"
                "Para cancelar, utiliza /cancelar."
            )
            return

        # SEGUNDO PASO: recibir el nuevo correo.
        if estado_edicion_admin == "correo":

            texto_correo = mensaje.text.strip()

            if texto_correo.upper() == "NO":
                correo_nuevo = context.user_data.get(
                    "usuario_edicion_admin_correo_actual"
                )

            elif texto_correo.upper() == "SIN CORREO":
                correo_nuevo = None

            elif (
                len(texto_correo) <= 254
                and re.fullmatch(
                    r"[^@\s]+@[^@\s]+\.[^@\s]+",
                    texto_correo
                )
            ):
                correo_nuevo = texto_correo

            else:
                await mensaje.reply_text(
                    "⚠️ El correo electrónico no tiene "
                    "un formato válido.\n\n"
                    "Escribe un correo válido, NO o SIN CORREO."
                )
                return

            nombre_nuevo = context.user_data.get(
                "usuario_edicion_admin_nombre_nuevo"
            )

            try:
                actualizado = actualizar_datos_usuario(
                    objetivo["id"],
                    nombre_nuevo,
                    correo_nuevo
                )

            except ValueError as error:
                await mensaje.reply_text(
                    f"⚠️ No se pudieron actualizar los datos:\n{error}\n\n"
                    "Introduce otro correo o cancela con /cancelar."
                )
                return

            except Exception:
                logger.exception(
                    "Error al editar los datos del usuario %s.",
                    objetivo["id"]
                )

                await mensaje.reply_text(
                    "No se pudo actualizar la cuenta debido "
                    "a un error interno. Inténtalo nuevamente."
                )
                return

            if not actualizado:
                campos = (
                    "estado_edicion_usuario_admin",
                    "usuario_edicion_admin_objetivo_id",
                    "usuario_edicion_admin_nombre_actual",
                    "usuario_edicion_admin_correo_actual",
                    "usuario_edicion_admin_nombre_nuevo"
                )

                for campo in campos:
                    context.user_data.pop(campo, None)

                await mensaje.reply_text(
                    "No se realizaron cambios en la cuenta."
                )
                return

            # Registrar la modificación en el historial administrativo.
            nombre_anterior = context.user_data.get(
                "usuario_edicion_admin_nombre_actual"
            )

            correo_anterior = context.user_data.get(
                "usuario_edicion_admin_correo_actual"
            )

            try:
                registrar_accion_administrativa(
                    responsable_telegram_id=telegram_id,
                    accion="EDICION_PERFIL_ADMIN",
                    usuario_objetivo_id=objetivo["id"],
                    detalle=(
                        f"Nombre anterior: {nombre_anterior}\n"
                        f"Nombre nuevo: {nombre_nuevo}\n"
                        f"Correo anterior: {correo_anterior or 'No registrado'}\n"
                        f"Correo nuevo: {correo_nuevo or 'No registrado'}"
                    )
                )

            except Exception:
                logger.exception(
                    "No se pudo registrar la edición administrativa "
                    "del usuario %s.",
                    objetivo["id"]
                )

            # Limpiar los datos temporales de la edición.
            campos = (
                "estado_edicion_usuario_admin",
                "usuario_edicion_admin_objetivo_id",
                "usuario_edicion_admin_nombre_actual",
                "usuario_edicion_admin_correo_actual",
                "usuario_edicion_admin_nombre_nuevo"
            )

            for campo in campos:
                context.user_data.pop(campo, None)

            # Recuperar los datos actualizados.
            usuarios_actualizados = listar_usuarios()

            objetivo_actualizado = next(
                (
                    u for u in usuarios_actualizados
                    if u["id"] == objetivo["id"]
                ),
                None
            )

            await mensaje.reply_text(
                "✅ USUARIO ACTUALIZADO CORRECTAMENTE\n\n"
                f"Nombre: {objetivo_actualizado['nombre']}\n"
                f"Correo: "
                f"{objetivo_actualizado['correo'] or 'No registrado'}\n"
                f"Rol: {objetivo_actualizado['rol']}\n"
                f"Nivel de acceso: "
                f"{objetivo_actualizado['nivel_acceso']}\n\n"
                "Los demás datos de seguridad permanecen sin cambios.",
                reply_markup=crear_menu_administracion()
            )
            return

    estado = context.user_data.get("estado_autenticacion")

    if estado not in {"configurar", "iniciar"}:
        if context.user_data.get("sesion_autenticada"):
            await mensaje.reply_text(
                "Utiliza los botones del menú para continuar."
            )
        else:
            await mensaje.reply_text(
                "Para iniciar sesión, utiliza el comando /start."
            )
        return

    telegram_id = update.effective_user.id
    clave = mensaje.text

    # Intentar eliminar el mensaje recibido por privacidad.
    try:
        await mensaje.delete()
    except Exception:
        logger.debug("No se pudo eliminar el mensaje de contraseña.")

    usuario = obtener_estado_contrasena(telegram_id)

    if usuario is None or not usuario["activo"]:
        context.user_data.clear()
        await mensaje.reply_text(
            "⛔ Tu cuenta no está registrada o está inactiva."
        )
        return

    if estado == "configurar":
        try:
            hash_clave = generar_hash_contrasena(clave)
        except ValueError:
            await mensaje.reply_text(
                "La contraseña debe tener al menos 12 caracteres. "
                "Inténtalo nuevamente."
            )
            return

        if not guardar_hash_contrasena(telegram_id, hash_clave):
            context.user_data.clear()
            await mensaje.reply_text(
                "No se pudo configurar la contraseña. "
                "Contacta al administrador."
            )
            return

        context.user_data.pop("estado_autenticacion", None)
        context.user_data["sesion_autenticada"] = True

        usuario_actual = buscar_usuario_por_telegram(telegram_id)

        if usuario_actual is None or not usuario_actual["activo"]:
            context.user_data.clear()

            await mensaje.reply_text(
                "⛔ Tu cuenta no está registrada o está inactiva."
            )
            return

        if await continuar_actualizacion_facial(update, context, telegram_id):
            return

        if (
                not usuario_actual["ruta_referencia"]
                or not Path(usuario_actual["ruta_referencia"]).is_file()
        ):
            context.user_data["estado_alta_rostro"] = "esperar_foto"

            await mensaje.reply_text(
                "✅ Contraseña configurada correctamente.\n\n"
                "📸 Ahora registra tu fotografía de referencia.\n"
                "Envía una fotografía donde tu rostro sea claramente visible, "
                "con buena iluminación y sin otras personas."
            )
            return

        await mensaje.reply_text(
            "✅ Contraseña configurada correctamente.\n"
            "Tu sesión ha comenzado.\n\n"
            f"¡Bienvenido, {usuario_actual['nombre']}! 👋\n"
            f"Rol: {usuario_actual['rol']}\n"
            "Selecciona una opción:",
            reply_markup=crear_menu_principal(usuario_actual)
        )
        return

    intentos_fallidos = contar_intentos_contrasena_fallidos(
        telegram_id,
        minutos=15
    )

    if intentos_fallidos >= 5:
        await mensaje.reply_text(
            "🔒 Has alcanzado el límite de intentos fallidos.\n"
            "Por seguridad, espera 15 minutos antes de volver a intentarlo."
        )
        return

    if not verificar_contrasena(clave, usuario["password_hash"]):
        registrar_intento(
            telegram_id=telegram_id,
            usuario_id=usuario["id"],
            resultado="RECHAZADO",
            motivo="Contraseña incorrecta"
        )

        await mensaje.reply_text(
            "❌ Contraseña incorrecta.\n"
            "Inténtalo nuevamente."
        )
        return

    context.user_data.pop("estado_autenticacion", None)
    context.user_data["sesion_autenticada"] = True

    usuario_actual = buscar_usuario_por_telegram(telegram_id)

    if usuario_actual is None or not usuario_actual["activo"]:
        context.user_data.clear()

        await mensaje.reply_text(
            "⛔ Tu cuenta no está registrada o está inactiva."
        )
        return

    if await continuar_actualizacion_facial(update, context, telegram_id):
        return

    if (
            not usuario_actual["ruta_referencia"]
            or not Path(usuario_actual["ruta_referencia"]).is_file()
    ):
        context.user_data["estado_alta_rostro"] = "esperar_foto"

        await mensaje.reply_text(
            "✅ Inicio de sesión correcto.\n\n"
            "📸 Todavía necesitas registrar tu fotografía de referencia.\n"
            "Envía una fotografía con buena iluminación, tu rostro "
            "claramente visible y sin otras personas."
        )
        return


    await mensaje.reply_text(
        "✅ Inicio de sesión correcto.\n\n"
        f"¡Bienvenido, {usuario_actual['nombre']}! 👋\n"
        f"Rol: {usuario_actual['rol']}\n"
        "Selecciona una opción:",
        reply_markup=crear_menu_principal(usuario_actual)
    )

async def mostrar_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Tu Telegram ID es: {update.effective_user.id}"
    )

async def ayuda(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    telegram_id = update.effective_user.id
    usuario = buscar_usuario_por_telegram(telegram_id)

    if (
        not context.user_data.get("sesion_autenticada")
        or usuario is None
        or not usuario["activo"]
    ):
        await update.message.reply_text(
            "🔒 Primero inicia sesión con /start."
        )
        return

    await update.message.reply_text(
        "❓ AYUDA\n\n"
        "• Información pública: consulta información general.\n"
        "• Mis documentos: requiere verificación facial.\n"
        "• Mi perfil: requiere verificación facial.\n"
        "• Panel de administración: exclusivo para ADMIN.\n\n"
        "Usa los botones del menú para navegar.",
        reply_markup=crear_boton_volver()
    )


async def informacion_publica(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    telegram_id = update.effective_user.id
    usuario = buscar_usuario_por_telegram(telegram_id)

    if (
        not context.user_data.get("sesion_autenticada")
        or usuario is None
        or not usuario["activo"]
    ):
        await update.message.reply_text(
            "🔒 Primero inicia sesión con /start."
        )
        return

    registros = obtener_informacion_autorizada(0)
    await update.message.reply_text(formatear_informacion(registros))


async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "El autorregistro está deshabilitado por seguridad.\n\n"
        "Contacta al administrador para solicitar el alta de tu cuenta."
    )


async def solicitar_privada(    update: Update,
    context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    if not context.user_data.get("sesion_autenticada"):
        await update.message.reply_text(
            "🔒 Primero inicia sesión con /start."
        )
        return

    usuario = buscar_usuario_por_telegram(telegram_id)

    if usuario is None or not usuario["activo"]:
        registrar_intento(
            telegram_id=telegram_id,
            resultado="RECHAZADO",
            motivo="Usuario no registrado o inactivo"
        )
        await update.message.reply_text(
            "⛔ Tu cuenta no está registrada o está inactiva.\n\n"
            "Contacta al administrador para solicitar acceso."
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

async def registrar_fotografia_referencia(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    telegram_id = update.effective_user.id
    usuario = buscar_usuario_por_telegram(telegram_id)

    if (
        not context.user_data.get("sesion_autenticada")
        or usuario is None
        or not usuario["activo"]
    ):
        context.user_data.pop("estado_alta_rostro", None)

        await update.message.reply_text(
            "⛔ Debes iniciar sesión con una cuenta activa."
        )
        return

    ruta_temporal = (
        TEMP_DIR / f"{telegram_id}-alta-{uuid4().hex}.jpg"
    )
    ruta_referencia = REFERENCES_DIR / f"{telegram_id}.jpg"

    try:
        archivo = await update.message.photo[-1].get_file()

        await archivo.download_to_drive(
            custom_path=str(ruta_temporal)
        )

        await update.message.reply_text(
            "🔎 Validando la fotografía. Espera un momento..."
        )

        try:
            rostros = await asyncio.to_thread(
                DeepFace.extract_faces,
                img_path=str(ruta_temporal),
                detector_backend="opencv",
                enforce_detection=True
            )
        except Exception:
            logger.info(
                "La fotografía no pudo validarse como rostro "
                "para Telegram ID %s.",
                telegram_id
            )

            await update.message.reply_text(
                "❌ No pudimos detectar un rostro válido.\n\n"
                "Envía otra fotografía con buena iluminación, "
                "tu rostro claramente visible y sin otras personas."
            )
            return

        if len(rostros) != 1:
            await update.message.reply_text(
                "❌ La fotografía debe contener exactamente "
                "un rostro.\n\n"
                "Inténtalo nuevamente."
            )
            return

        REFERENCES_DIR.mkdir(parents=True, exist_ok=True)

        ruta_temporal.replace(ruta_referencia)

        try:
            registrar_perfil_facial(
                usuario["id"],
                str(ruta_referencia),
                FACE_MODEL
            )
        except Exception:
            ruta_referencia.unlink(missing_ok=True)
            raise


        # Registrar el primer registro facial del usuario.
        try:
            registrar_accion_administrativa(
                responsable_telegram_id=telegram_id,
                accion="REGISTRO_FACIAL_INICIAL",
                usuario_objetivo_id=usuario["id"],
                detalle=(
                    "El usuario completó el registro inicial "
                    "de su fotografía facial.\n"
                    f"Modelo utilizado: {FACE_MODEL}"
                )
            )

        except Exception:
            logger.exception(
                "No se pudo registrar el alta facial inicial "
                "del usuario %s.",
                usuario["id"]
            )

        context.user_data.pop("estado_alta_rostro", None)

        usuario_actual = buscar_usuario_por_telegram(telegram_id)

        await update.message.reply_text(
            "✅ Fotografía de referencia registrada correctamente.\n\n"
            "Ya puedes utilizar las funciones que requieren "
            "verificación facial.",
            reply_markup=crear_menu_principal(usuario_actual)
        )

    except Exception:
        logger.exception(
            "Error al registrar la fotografía de referencia."
        )

        await update.message.reply_text(
            "No se pudo completar el registro de tu rostro. "
            "Inténtalo nuevamente."
        )

    finally:
        ruta_temporal.unlink(missing_ok=True)

async def actualizar_fotografia_referencia(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    solicitud
):
    telegram_id = update.effective_user.id

    usuario = buscar_usuario_por_telegram(telegram_id)

    if (
        not context.user_data.get("sesion_autenticada")
        or usuario is None
        or not usuario["activo"]
    ):
        await update.message.reply_text(
            "⛔ Debes iniciar sesión con una cuenta activa."
        )
        return

    if (
        solicitud is None
        or solicitud["estado"] != "ESPERANDO_FOTO"
    ):
        await update.message.reply_text(
            "La solicitud de actualización facial no está activa."
        )
        return

    ruta_temporal = (
        TEMP_DIR / f"{telegram_id}-actualizacion-temp-{uuid4().hex}.jpg"
    )

    # La nueva fotografía tendrá un nombre diferente a la anterior.
    ruta_nueva = (
        REFERENCES_DIR / f"{telegram_id}-actualizacion-{uuid4().hex}.jpg"
    )

    actualizacion_guardada = False

    try:
        archivo = await update.message.photo[-1].get_file()

        await archivo.download_to_drive(
            custom_path=str(ruta_temporal)
        )

        await update.message.reply_text(
            "🔎 Validando tu nueva fotografía. Espera un momento..."
        )

        try:
            rostros = await asyncio.to_thread(
                DeepFace.extract_faces,
                img_path=str(ruta_temporal),
                detector_backend="opencv",
                enforce_detection=True
            )
        except Exception:
            logger.info(
                "No se pudo detectar un rostro para actualizar "
                "el perfil del usuario %s.",
                telegram_id
            )

            await update.message.reply_text(
                "❌ No pudimos detectar un rostro válido.\n\n"
                "Envía otra fotografía con buena iluminación, "
                "tu rostro claramente visible y sin otras personas."
            )
            return

        if len(rostros) != 1:
            await update.message.reply_text(
                "❌ La fotografía debe contener exactamente un rostro.\n\n"
                "Inténtalo nuevamente."
            )
            return

        REFERENCES_DIR.mkdir(parents=True, exist_ok=True)

        # Mover la nueva fotografía a su ubicación definitiva.
        ruta_temporal.replace(ruta_nueva)

        # Actualizar la base de datos y recuperar la ruta anterior.
        ruta_anterior = actualizar_perfil_facial_solicitado(
            usuario["id"],
            str(ruta_nueva),
            usuario["modelo_utilizado"] or FACE_MODEL
        )

        actualizacion_guardada = True

    except Exception:
        logger.exception(
            "Error al actualizar la fotografía facial del usuario %s.",
            telegram_id
        )

        await update.message.reply_text(
            "No se pudo completar la actualización facial.\n\n"
            "La fotografía anterior se conserva. "
            "Inténtalo nuevamente si tu solicitud sigue vigente."
        )
        return

    finally:
        ruta_temporal.unlink(missing_ok=True)

        # Si la base de datos no confirmó el cambio,
        # eliminar la nueva fotografía sin tocar la anterior.
        if not actualizacion_guardada:
            ruta_nueva.unlink(missing_ok=True)

    # La base de datos confirmó el cambio.
    # Ahora podemos eliminar la fotografía anterior.
    if ruta_anterior:
        try:
            ruta_antigua = Path(ruta_anterior).resolve()
            directorio_referencias = REFERENCES_DIR.resolve()

            if ruta_antigua != ruta_nueva.resolve():
                try:
                    ruta_antigua.relative_to(directorio_referencias)
                except ValueError:
                    logger.warning(
                        "La fotografía anterior está fuera del directorio "
                        "de referencias y no se eliminará."
                    )
                else:
                    ruta_antigua.unlink(missing_ok=True)

        except OSError:
            logger.warning(
                "No se pudo eliminar la fotografía facial anterior.",
                exc_info=True
            )

    # Registrar la actualización facial completada.
    try:
        registrar_accion_administrativa(
            responsable_telegram_id=telegram_id,
            accion="ACTUALIZACION_FACIAL",
            usuario_objetivo_id=usuario["id"],
            detalle=(
                "El usuario completó la actualización de su "
                "fotografía de referencia después de confirmar "
                "su contraseña y enviar una fotografía válida."
            )
        )

    except Exception:
        logger.exception(
            "No se pudo registrar la actualización facial "
            "del usuario %s en el historial administrativo.",
            usuario["id"]
        )

    context.user_data.pop(
        "actualizacion_facial_en_proceso",
        None
    )

    usuario_actual = buscar_usuario_por_telegram(telegram_id)

    await update.message.reply_text(
        "✅ FOTOGRAFÍA FACIAL ACTUALIZADA\n\n"
        "Tu nueva fotografía de referencia fue registrada correctamente.\n"
        "Ya puedes continuar utilizando las funciones del sistema.",
        reply_markup=crear_menu_principal(usuario_actual)
    )

async def recibir_foto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.user_data.get("sesion_autenticada"):
        await update.message.reply_text(
            "🔒 Primero inicia sesión con /start."
        )
        return

    telegram_id = update.effective_user.id

    solicitud = obtener_solicitud_actualizacion_facial(telegram_id)

    if solicitud and solicitud["estado"] == "ESPERANDO_FOTO":
        await actualizar_fotografia_referencia(
            update,
            context,
            solicitud
        )
        return

    if solicitud and solicitud["estado"] == "ESPERANDO_CLAVE":
        await update.message.reply_text(
            "🔒 Primero debes confirmar tu contraseña.\n\n"
            "Utiliza /start para iniciar el proceso de autenticación."
        )
        return

    if context.user_data.get("estado_alta_rostro") == "esperar_foto":
        await registrar_fotografia_referencia(update, context)
        return

    accion = context.user_data.get("accion_foto")

    if not accion:
        await update.message.reply_text(
            "Primero selecciona una opción del menú."
        )
        return

    if accion == "registro":
        context.user_data.clear()
        await update.message.reply_text(
            "El registro directo está deshabilitado. "
            "Contacta al administrador."
        )
        return

    usuario = buscar_usuario_por_telegram(telegram_id)

    if usuario is None or not usuario["activo"]:
        context.user_data.clear()
        registrar_intento(
            telegram_id=telegram_id,
            resultado="RECHAZADO",
            motivo="Usuario no registrado o inactivo"
        )
        await update.message.reply_text(
            "⛔ Tu cuenta no está registrada o está inactiva."
        )
        return

    acciones_validas = {
        "verificacion",
        "documentos",
        "perfil",
        "admin",
        "admin_agregar_usuario",
        "admin_usuarios",
        "admin_documentos",
        "admin_historial",
        "admin_historial_administrativo",
        "admin_cambiar_rol",
        "admin_restablecer_clave",
        "admin_actualizar_rostro",
        "admin_cambiar_estado"
    }

    if accion not in acciones_validas:
        context.user_data.clear()
        await update.message.reply_text(
            "La operación solicitada no es válida."
        )
        return

    if accion.startswith("admin") and usuario["rol"] != "ADMIN":
        context.user_data.clear()
        await update.message.reply_text(
            "⛔ No tienes permisos para realizar esta operación."
        )
        return

    ruta_referencia = usuario["ruta_referencia"]

    if (
        not ruta_referencia
        or not Path(ruta_referencia).is_file()
    ):
        context.user_data.clear()
        await update.message.reply_text(
            "No existe una fotografía de referencia válida. "
            "Contacta al administrador."
        )
        return

    ruta_temporal = (
        TEMP_DIR / f"{telegram_id}-{uuid4().hex}.jpg"
    )

    try:
        archivo = await update.message.photo[-1].get_file()

        await archivo.download_to_drive(
            custom_path=str(ruta_temporal)
        )

        await update.message.reply_text(
            "Procesando verificación facial…"
        )

        resultado = await asyncio.to_thread(
            verificar_rostro,
            Path(ruta_referencia),
            ruta_temporal,
            usuario["modelo_utilizado"] or FACE_MODEL
        )

        distancia = resultado["distancia"]
        umbral = resultado["umbral"]

        if not resultado["verificado"]:
            registrar_intento(
                telegram_id=telegram_id,
                usuario_id=usuario["id"],
                resultado="RECHAZADO",
                distancia=distancia,
                motivo="El rostro no coincide"
            )

            await update.message.reply_text(
                "❌ El rostro no coincide. Acceso denegado.\n"
                f"Distancia: {distancia:.4f} | "
                f"Umbral: {umbral:.4f}",
                reply_markup=crear_boton_volver()
            )
            return

        registrar_intento(
            telegram_id=telegram_id,
            usuario_id=usuario["id"],
            resultado="EXITOSO",
            distancia=distancia,
            motivo=f"Identidad verificada para la operación: {accion}"

        )

        if accion == "admin_cambiar_estado":
            administrador_actual = buscar_usuario_por_telegram(
                telegram_id
            )

            if (
                administrador_actual is None
                or not administrador_actual["activo"]
                or administrador_actual["rol"] != "ADMIN"
            ):
                await update.message.reply_text(
                    "⛔ Tu cuenta ya no tiene permisos administrativos."
                )
                return

            objetivo_id = context.user_data.get(
                "usuario_estado_objetivo"
            )
            nuevo_estado = context.user_data.get(
                "nuevo_estado_usuario"
            )

            if (
                not isinstance(objetivo_id, int)
                or not isinstance(nuevo_estado, int)
                or nuevo_estado not in (0, 1)
            ):
                await update.message.reply_text(
                    "La operación no es válida. "
                    "Vuelve a seleccionarla desde el menú."
                )
                return

            usuarios_actuales = listar_usuarios()

            objetivo = next(
                (
                    u for u in usuarios_actuales
                    if u["id"] == objetivo_id
                ),
                None
            )

            if objetivo is None:
                await update.message.reply_text(
                    "No se encontró la cuenta seleccionada."
                )
                return

            if objetivo["telegram_id"] == telegram_id:
                await update.message.reply_text(
                    "⛔ No puedes cambiar el estado de tu propia cuenta."
                )
                return

            if objetivo["activo"] == nuevo_estado:
                await update.message.reply_text(
                    "La cuenta ya tiene el estado solicitado."
                )
                return

            if (
                objetivo["rol"] == "ADMIN"
                and nuevo_estado == 0
            ):
                administradores_activos = sum(
                    1 for u in usuarios_actuales
                    if u["rol"] == "ADMIN" and u["activo"]
                )

                if administradores_activos <= 1:
                    await update.message.reply_text(
                        "⛔ No puedes desactivar al último "
                        "administrador activo."
                    )
                    return

            cambiado = cambiar_estado_usuario(
                objetivo_id,
                nuevo_estado
            )

            if not cambiado:
                await update.message.reply_text(
                    "No se pudo cambiar el estado de la cuenta."
                )
                return

            # Registrar el cambio en el historial administrativo.
            estado_anterior = (
                "ACTIVA" if objetivo["activo"] else "INACTIVA"
            )

            estado_nuevo = (
                "ACTIVA" if nuevo_estado == 1 else "INACTIVA"
            )

            try:
                registrar_accion_administrativa(
                    responsable_telegram_id=telegram_id,
                    accion="CAMBIO_ESTADO",
                    usuario_objetivo_id=objetivo_id,
                    detalle=(
                        f"Estado anterior: {estado_anterior}\n"
                        f"Estado nuevo: {estado_nuevo}"
                    )
                )

            except Exception:
                logger.exception(
                    "No se pudo registrar el cambio de estado "
                    "del usuario %s en el historial administrativo.",
                    objetivo_id
                )

            nombre_estado = (
                "ACTIVADA" if nuevo_estado == 1 else "DESACTIVADA"
            )

            context.user_data.pop("usuario_estado_objetivo", None)
            context.user_data.pop("nuevo_estado_usuario", None)

            await update.message.reply_text(
                f"✅ Cuenta {nombre_estado} correctamente.\n\n"
                f"Usuario: {objetivo['nombre']}\n"
                f"Telegram ID: {objetivo['telegram_id']}",
                reply_markup=crear_menu_administracion()
            )

        elif accion == "admin_cambiar_rol":
            administrador_actual = buscar_usuario_por_telegram(
                telegram_id
            )

            if (
                administrador_actual is None
                or not administrador_actual["activo"]
                or administrador_actual["rol"] != "ADMIN"
            ):
                await update.message.reply_text(
                    "⛔ Tu cuenta ya no tiene permisos administrativos."
                )
                return

            objetivo_id = context.user_data.get(
                "usuario_rol_objetivo"
            )
            nuevo_rol = context.user_data.get(
                "nuevo_rol_usuario"
            )

            niveles_por_rol = {
                "EMPLEADO": 1,
                "EJECUTIVO": 2,
                "ADMIN": 3
            }

            if (
                isinstance(objetivo_id, bool)
                or not isinstance(objetivo_id, int)
                or objetivo_id <= 0
                or nuevo_rol not in niveles_por_rol
            ):
                await update.message.reply_text(
                    "La operación no es válida. "
                    "Vuelve a seleccionarla desde el panel."
                )
                return

            usuarios_actuales = listar_usuarios()

            objetivo = next(
                (
                    u for u in usuarios_actuales
                    if u["id"] == objetivo_id
                ),
                None
            )

            if objetivo is None:
                await update.message.reply_text(
                    "No se encontró la cuenta seleccionada."
                )
                return

            if objetivo["telegram_id"] == telegram_id:
                await update.message.reply_text(
                    "⛔ No puedes cambiar el rol de tu propia cuenta."
                )
                return

            if objetivo["rol"] == nuevo_rol:
                await update.message.reply_text(
                    "La cuenta ya tiene el rol solicitado."
                )
                return

            try:
                cambiado = cambiar_rol_usuario(
                    objetivo_id,
                    nuevo_rol
                )

            except ValueError as error:
                await update.message.reply_text(
                    f"⛔ No se pudo cambiar el rol: {error}",
                    reply_markup=crear_menu_administracion()
                )
                return

            if not cambiado:
                await update.message.reply_text(
                    "No se pudo cambiar el rol de la cuenta.",
                    reply_markup=crear_menu_administracion()
                )
                return

            # Registrar el cambio de rol en el historial administrativo.
            try:
                registrar_accion_administrativa(
                    responsable_telegram_id=telegram_id,
                    accion="CAMBIO_ROL",
                    usuario_objetivo_id=objetivo_id,
                    detalle=(
                        f"Rol anterior: {objetivo['rol']}\n"
                        f"Nivel anterior: {niveles_por_rol[objetivo['rol']]}\n"
                        f"Rol nuevo: {nuevo_rol}\n"
                        f"Nivel nuevo: {niveles_por_rol[nuevo_rol]}"
                    )
                )

            except Exception:
                logger.exception(
                    "No se pudo registrar el cambio de rol "
                    "del usuario %s en el historial administrativo.",
                    objetivo_id
                )

            context.user_data.pop("usuario_rol_objetivo", None)
            context.user_data.pop("nuevo_rol_usuario", None)

            await update.message.reply_text(
                "✅ ROL ACTUALIZADO CORRECTAMENTE\n\n"
                f"Usuario: {objetivo['nombre']}\n"
                f"Rol anterior: {objetivo['rol']}\n"
                f"Nuevo rol: {nuevo_rol}\n"
                f"Nuevo nivel de acceso: "
                f"{niveles_por_rol[nuevo_rol]}",
                reply_markup=crear_menu_administracion()
            )

        elif accion == "admin_restablecer_clave":
            administrador_actual = buscar_usuario_por_telegram(
                telegram_id
            )

            if (
                administrador_actual is None
                or not administrador_actual["activo"]
                or administrador_actual["rol"] != "ADMIN"
            ):
                await update.message.reply_text(
                    "⛔ Tu cuenta ya no tiene permisos administrativos."
                )
                return

            objetivo_id = context.user_data.get(
                "usuario_clave_objetivo"
            )

            if (
                isinstance(objetivo_id, bool)
                or not isinstance(objetivo_id, int)
                or objetivo_id <= 0
            ):
                await update.message.reply_text(
                    "La operación no es válida. "
                    "Vuelve a seleccionarla desde el panel."
                )
                return

            usuarios_actuales = listar_usuarios()

            objetivo = next(
                (
                    u for u in usuarios_actuales
                    if u["id"] == objetivo_id
                ),
                None
            )

            if objetivo is None:
                await update.message.reply_text(
                    "No se encontró la cuenta seleccionada."
                )
                return

            if objetivo["telegram_id"] == telegram_id:
                await update.message.reply_text(
                    "⛔ No puedes restablecer tu propia contraseña "
                    "desde esta opción."
                )
                return

            try:
                restablecido = restablecer_contrasena_usuario(
                    objetivo_id
                )
            except Exception:
                logger.exception(
                    "Error al restablecer la contraseña del usuario %s",
                    objetivo_id
                )

                await update.message.reply_text(
                    "No se pudo restablecer la contraseña. "
                    "Inténtalo nuevamente."
                )
                return

            if not restablecido:
                await update.message.reply_text(
                    "No se pudo restablecer la contraseña "
                    "de la cuenta seleccionada."
                )
                return

            # Registrar el restablecimiento en el historial administrativo.
            try:
                registrar_accion_administrativa(
                    responsable_telegram_id=telegram_id,
                    accion="RESTABLECIMIENTO_CONTRASENA",
                    usuario_objetivo_id=objetivo_id,
                    detalle=(
                        "La contraseña anterior fue invalidada. "
                        "El usuario debe configurar una nueva contraseña "
                        "para recuperar el acceso."
                    )
                )

            except Exception:
                logger.exception(
                    "No se pudo registrar el restablecimiento de contraseña "
                    "del usuario %s en el historial administrativo.",
                    objetivo_id
                )

            # Invalida los datos de sesión del usuario objetivo.
            sesion_objetivo = context.application.user_data.get(
                objetivo["telegram_id"]
            )

            if sesion_objetivo is not None:
                sesion_objetivo.clear()

            # Notifica al usuario; un error de notificación
            # no revierte el restablecimiento ya realizado.
            try:
                await context.bot.send_message(
                    chat_id=objetivo["telegram_id"],
                    text=(
                        "🔐 Se ha restablecido el acceso a tu cuenta "
                        "por solicitud del administrador.\n\n"
                        "Tu contraseña anterior ya no es válida. "
                        "Utiliza /start y configura una nueva "
                        "contraseña para continuar.\n\n"
                        "Si no esperabas este cambio, contacta "
                        "al administrador."
                    )
                )
                notificado = True

            except Exception:
                notificado = False
                logger.warning(
                    "No se pudo notificar el restablecimiento "
                    "al usuario %s",
                    objetivo["telegram_id"],
                    exc_info=True
                )

            context.user_data.pop("usuario_clave_objetivo", None)

            mensaje_final = (
                "✅ CONTRASEÑA RESTABLECIDA\n\n"
                f"Usuario: {objetivo['nombre']}\n"
                f"Telegram ID: {objetivo['telegram_id']}\n\n"
                "La contraseña anterior fue invalidada. "
                "El usuario deberá configurar una nueva "
                "al iniciar sesión."
            )

            if notificado:
                mensaje_final += "\n\nSe envió una notificación al usuario."
            else:
                mensaje_final += (
                    "\n\n⚠️ No se pudo enviar la notificación. "
                    "Comunica el cambio al usuario por otro medio."
                )

            await update.message.reply_text(
                mensaje_final,
                reply_markup=crear_menu_administracion()
            )


        elif accion == "admin_actualizar_rostro":
            administrador_actual = buscar_usuario_por_telegram(
                telegram_id
            )

            if (
                administrador_actual is None
                or not administrador_actual["activo"]
                or administrador_actual["rol"] != "ADMIN"
            ):
                await update.message.reply_text(
                    "⛔ Tu cuenta ya no tiene permisos administrativos."
                )
                return

            objetivo_id = context.user_data.get(
                "usuario_rostro_objetivo"
            )

            if (
                isinstance(objetivo_id, bool)
                or not isinstance(objetivo_id, int)
                or objetivo_id <= 0
            ):
                await update.message.reply_text(
                    "La operación no es válida. "
                    "Vuelve a seleccionarla desde el panel."
                )
                return

            usuarios_actuales = listar_usuarios()

            objetivo = next(
                (
                    u for u in usuarios_actuales
                    if u["id"] == objetivo_id
                ),
                None
            )

            if (
                objetivo is None
                or not objetivo["activo"]
                or not objetivo["tiene_perfil_facial"]
            ):
                await update.message.reply_text(
                    "No se encontró un usuario activo "
                    "con fotografía facial registrada."
                )
                return

            if objetivo["telegram_id"] == telegram_id:
                await update.message.reply_text(
                    "No puedes actualizar tu propia fotografía."
                )
                return

            try:
                solicitar_actualizacion_facial(
                    objetivo_id,
                    administrador_actual["id"]
                )

            except Exception:
                logger.exception(
                    "Error al autorizar actualización facial."
                )

                await update.message.reply_text(
                    "No se pudo autorizar la actualización facial."
                )
                return

            # Registrar la autorización en el historial administrativo.
            try:
                registrar_accion_administrativa(
                    responsable_telegram_id=telegram_id,
                    accion="AUTORIZACION_ACTUALIZACION_FACIAL",
                    usuario_objetivo_id=objetivo_id,
                    detalle=(
                        "El administrador autorizó al usuario "
                        "a actualizar su fotografía de referencia. "
                        "Se requiere confirmar la contraseña actual."
                    )
                )

            except Exception:
                logger.exception(
                    "No se pudo registrar la autorización facial "
                    "del usuario %s.",
                    objetivo_id
                )

            try:
                await context.bot.send_message(
                    chat_id=objetivo["telegram_id"],
                    text=(
                        "📸 ACTUALIZACIÓN DE FOTOGRAFÍA AUTORIZADA\n\n"
                        "El administrador ha autorizado actualizar "
                        "tu fotografía de referencia.\n\n"
                        "Para continuar:\n"
                        "1. Inicia sesión con /start.\n"
                        "2. Confirma tu contraseña actual.\n"
                        "3. Envía tu nueva fotografía facial.\n\n"
                        "Tienes 24 horas para iniciar el proceso. "
                        "Después de confirmar tu contraseña, "
                        "dispondrás de 10 minutos para enviar la fotografía."
                    )
                )
                notificado = True

            except Exception:
                notificado = False

                logger.warning(
                    "No se pudo notificar la actualización facial "
                    "al usuario %s.",
                    objetivo["telegram_id"],
                    exc_info=True
                )

            mensaje_final = (
                "✅ ACTUALIZACIÓN FACIAL AUTORIZADA\n\n"
                f"Usuario: {objetivo['nombre']}\n"
                f"Telegram ID: {objetivo['telegram_id']}\n\n"
                "La solicitud quedó registrada correctamente."
            )

            if notificado:
                mensaje_final += "\nSe notificó al usuario."
            else:
                mensaje_final += (
                    "\n⚠️ No se pudo notificar al usuario. "
                    "Comunícale la autorización por otro medio."
                )

            await update.message.reply_text(
                mensaje_final,
                reply_markup=crear_menu_administracion()
            )

        elif accion in {"documentos", "verificacion"}:
            informacion = obtener_informacion_autorizada(
                usuario["nivel_acceso"]
            )

            await update.message.reply_text(
                "✅ Identidad verificada. Acceso permitido.\n\n"
                + formatear_informacion(
                    informacion,
                    solo_privada=True
                )
                + f"\n\nDistancia: {distancia:.4f} | "
                  f"Umbral: {umbral:.4f}",
                reply_markup=crear_boton_volver()
            )

        elif accion == "perfil":
            teclado_perfil = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✏️ Editar mi perfil",
                        callback_data="editar_mi_perfil"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Menú principal",
                        callback_data="menu"
                    )
                ]
            ])

            await update.message.reply_text(
                "✅ Identidad verificada.\n\n"
                "👤 MI PERFIL\n"
                f"Nombre: {usuario['nombre']}\n"
                f"Correo: {usuario['correo'] or 'No registrado'}\n"
                f"Rol: {usuario['rol']}\n"
                f"Nivel de acceso: {usuario['nivel_acceso']}\n"
                "Estado: Activo",
                reply_markup=teclado_perfil
            )

        elif accion == "admin":
            await update.message.reply_text(
                "✅ Identidad verificada.\n"
                "Bienvenido al panel de administración.",
                reply_markup=crear_menu_administracion()
            )

        elif accion == "admin_usuarios":
            usuarios = listar_usuarios()

            if not usuarios:
                await update.message.reply_text(
                    "No hay usuarios registrados.",
                    reply_markup=crear_menu_administracion()
                )
                return

            await update.message.reply_text(
                f"👥 USUARIOS REGISTRADOS: {len(usuarios)}"
            )

            for u in usuarios:
                estado = "Activa" if u["activo"] else "Inactiva"
                rostro = (
                    "Registrado"
                    if u["tiene_perfil_facial"]
                    else "Pendiente"
                )

                ficha = (
                    f"🆔 ID interno: {u['id']}\n"
                    f"👤 Nombre: {u['nombre']}\n"
                    f"Telegram ID: {u['telegram_id']}\n"
                    f"Rol: {u['rol']}\n"
                    f"Nivel de acceso: {u['nivel_acceso']}\n"
                    f"Estado: {estado}\n"
                    f"Fotografía facial: {rostro}\n"
                )

                if u["correo"]:
                    ficha += f"Correo: {u['correo']}\n"

                teclado = None

                if u["telegram_id"] != telegram_id:
                    nuevo_estado = 0 if u["activo"] else 1

                    texto_boton = (
                        "⛔ Desactivar cuenta"
                        if u["activo"]
                        else "✅ Activar cuenta"
                    )

                    botones_usuario = [
                        [
                            InlineKeyboardButton(
                                texto_boton,
                                callback_data=(
                                    f"estado|{u['id']}|{nuevo_estado}"
                                )
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🔄 Cambiar rol",
                                callback_data=f"rol|{u['id']}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🔑 Restablecer contraseña",
                                callback_data=f"clave|{u['id']}"
                            )
                        ],

                        [
                            InlineKeyboardButton(
                                "✏️ Editar datos",
                                callback_data=f"editar_usuario|{u['id']}"
                            )
                        ]
                    ]

                    if u["activo"] and u["tiene_perfil_facial"]:
                        botones_usuario.append([
                            InlineKeyboardButton(
                                "📸 Actualizar fotografía facial",
                                callback_data=f"rostro|{u['id']}"
                            )
                        ])

                    teclado = InlineKeyboardMarkup(botones_usuario)

                else:
                    ficha += (
                        "\n🔒 Esta es tu cuenta de administrador. "
                        "No puedes modificar tu propia cuenta desde aquí.\n"
                    )

                await update.message.reply_text(
                    ficha,
                    reply_markup=teclado
                )

            await update.message.reply_text(
                "Selecciona una cuenta para continuar.",
                reply_markup=crear_menu_administracion()
            )

        elif accion == "admin_agregar_usuario":
            context.user_data["estado_alta_usuario"] = "telegram_id"

            await update.message.reply_text(
                "✅ Identidad del administrador verificada.\n\n"
                "Vamos a registrar un usuario nuevo.\n\n"
                "Envía el Telegram ID numérico del usuario "
                "que deseas registrar.\n\n"
                "El usuario puede obtenerlo enviando /id "
                "a este bot.",
                reply_markup=crear_boton_volver()
            )

        elif accion == "admin_historial":
            historial = obtener_historial_autenticacion(limite=20)

            if not historial:
                await update.message.reply_text(
                    "📋 No hay intentos de acceso registrados.",
                    reply_markup=crear_menu_administracion()
                )
                return

            mensajes = []
            actual = (
                f"📋 HISTORIAL DE ACCESOS\n"
                f"Últimos {len(historial)} registros\n\n"
            )

            for registro in historial:
                distancia = (
                    f"{registro['distancia']:.4f}"
                    if registro["distancia"] is not None
                    else "No disponible"
                )

                motivo = (
                    registro["motivo"] or "Sin motivo registrado"
                ).replace("\n", " ")

                entrada = (
                    f"Registro: #{registro['id']}\n"
                    f"Fecha: {registro['fecha_intento']}\n"
                    f"Usuario: {registro['nombre']}\n"
                    f"Rol: {registro['rol']}\n"
                    f"Telegram ID: {registro['telegram_id']}\n"
                    f"Resultado: {registro['resultado']}\n"
                    f"Distancia facial: {distancia}\n"
                    f"Motivo: {motivo}\n\n"
                )

                if len(actual) + len(entrada) > 3500:
                    mensajes.append(actual)
                    actual = "📋 HISTORIAL DE ACCESOS (continuación)\n\n"

                actual += entrada

            if actual.strip():
                mensajes.append(actual)

            for indice, texto in enumerate(mensajes):
                if indice == len(mensajes) - 1:
                    await update.message.reply_text(
                        texto,
                        reply_markup=crear_menu_administracion()
                    )
                else:
                    await update.message.reply_text(texto)


        elif accion == "admin_historial_administrativo":
            historial = obtener_historial_administrativo(limite=20)

            if not historial:
                await update.message.reply_text(
                    "📝 Todavía no hay acciones administrativas registradas.",
                    reply_markup=crear_menu_administracion()
                )
                return

            mensajes = []
            actual = (
                "📝 HISTORIAL ADMINISTRATIVO\n"
                f"Últimos {len(historial)} registros\n\n"
            )

            for registro in historial:
                nombre_objetivo = (
                    registro["usuario_objetivo_nombre"]
                    or "No especificado"
                )

                objetivo_id = (
                    registro["usuario_objetivo_id"]
                    if registro["usuario_objetivo_id"] is not None
                    else "No disponible"
                )

                objetivo_telegram = (
                    registro["usuario_objetivo_telegram_id"]
                    if registro["usuario_objetivo_telegram_id"] is not None
                    else "No disponible"
                )

                detalle = (
                    registro["detalle"] or "Sin detalle registrado"
                )

                entrada = (
                    f"Registro: #{registro['id']}\n"
                    f"Fecha: {registro['fecha_accion']}\n\n"
                    f"Responsable: {registro['responsable_nombre']}\n"
                    f"Rol: {registro['responsable_rol']}\n"
                    f"Telegram ID responsable: "
                    f"{registro['responsable_telegram_id']}\n\n"
                    f"Usuario afectado: {nombre_objetivo}\n"
                    f"ID interno afectado: {objetivo_id}\n"
                    f"Telegram ID afectado: {objetivo_telegram}\n\n"
                    f"Acción: {registro['accion']}\n"
                    f"Detalle:\n{detalle}\n\n"
                    "--------------------------------\n\n"
                )

                if len(actual) + len(entrada) > 3500:
                    mensajes.append(actual)
                    actual = (
                        "📝 HISTORIAL ADMINISTRATIVO "
                        "(continuación)\n\n"
                    )

                actual += entrada

            if actual.strip():
                mensajes.append(actual)

            for indice, texto in enumerate(mensajes):
                if indice == len(mensajes) - 1:
                    await update.message.reply_text(
                        texto,
                        reply_markup=crear_menu_administracion()
                    )
                else:
                    await update.message.reply_text(texto)


        else:
            opciones_admin = {
                "admin_usuarios": "Gestionar usuarios",
                "admin_documentos": "Gestionar documentos",
                "admin_historial": "Historial de accesos"
            }

            nombre_opcion = opciones_admin[accion]

            await update.message.reply_text(
                "✅ Identidad verificada.\n\n"
                f"Seleccionaste: {nombre_opcion}.\n"
                "Esta función todavía está en desarrollo.",
                reply_markup=crear_menu_administracion()
            )

    except Exception as error:
        logger.exception("Error durante la verificación facial")

        try:
            registrar_intento(
                telegram_id=telegram_id,
                usuario_id=usuario["id"],
                resultado="ERROR",
                motivo=str(error)[:250]
            )
        except Exception:
            logger.exception("No se pudo registrar el error")

        await update.message.reply_text(
            "No se pudo procesar la imagen. Comprueba que "
            "contenga un rostro claro e inténtalo nuevamente.",
            reply_markup=crear_boton_volver()
        )


    finally:
        context.user_data.pop("accion_foto", None)

        for campo in (
            "usuario_estado_objetivo",
            "nuevo_estado_usuario",
            "usuario_rol_objetivo",
            "nuevo_rol_usuario",
            "usuario_clave_objetivo",
            "usuario_rostro_objetivo"
        ):
            context.user_data.pop(campo, None)

        ruta_temporal.unlink(missing_ok=True)


async def cancelar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        cancelar_actualizacion_facial(update.effective_user.id)

    except Exception:
        logger.exception(
            "Error al cancelar la solicitud de actualización facial."
        )

        await update.message.reply_text(
            "No se pudo cancelar la solicitud facial. "
            "Inténtalo nuevamente."
        )
        return

    campos_temporales = [
        "accion_foto",
        "estado_autenticacion",
        "estado_alta_usuario",
        "estado_alta_rostro",
        "nuevo_usuario_telegram_id",
        "nuevo_usuario_nombre",
        "nuevo_usuario_rol",
        "nuevo_usuario_correo",
        "usuario_estado_objetivo",
        "nuevo_estado_usuario",
        "usuario_rol_objetivo",
        "nuevo_rol_usuario",
        "usuario_rostro_objetivo",
        "usuario_clave_objetivo",
        "estado_edicion_perfil",
        "perfil_edicion_usuario_id",
        "perfil_edicion_nombre_nuevo",
        "perfil_edicion_nombre_actual",
        "perfil_edicion_correo_actual",
        "estado_edicion_usuario_admin",
        "usuario_edicion_admin_objetivo_id",
        "usuario_edicion_admin_nombre_actual",
        "usuario_edicion_admin_correo_actual",
        "usuario_edicion_admin_nombre_nuevo",
        "actualizacion_facial_en_proceso"
    ]

    for campo in campos_temporales:
        context.user_data.pop(campo, None)

    if context.user_data.get("sesion_autenticada"):
        await update.message.reply_text(
            "✅ Proceso cancelado. Tu sesión sigue activa."
        )
    else:
        context.user_data.clear()

        await update.message.reply_text(
            "Proceso cancelado. Utiliza /start para comenzar."
        )


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
    aplicacion.add_handler(CommandHandler("ayuda", ayuda))
    aplicacion.add_handler(CommandHandler("id", mostrar_id))
    aplicacion.add_handler(CommandHandler("publica", informacion_publica))
    aplicacion.add_handler(CommandHandler("registrar", registrar))
    aplicacion.add_handler(CommandHandler("privada", solicitar_privada))
    aplicacion.add_handler(CallbackQueryHandler(manejar_boton))
    aplicacion.add_handler(CommandHandler("cancelar", cancelar))
    aplicacion.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto)
    )
    aplicacion.add_handler(MessageHandler(filters.PHOTO, recibir_foto))
    aplicacion.add_error_handler(manejar_error)

    logger.info("Bot y página pública iniciados")
    aplicacion.run_polling()


if __name__ == "__main__":
    main()
