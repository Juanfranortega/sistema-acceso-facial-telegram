# Publicar la demostración en Railway

La publicación genera dos enlaces para la entrega:

- Página del proyecto: `https://TU-DOMINIO.up.railway.app`
- Bot de Telegram: `https://t.me/TU_BOT`

## 1. Subir esta versión a GitHub

Desde la carpeta del proyecto:

```powershell
git add .
git commit -m "Preparar demostración para despliegue"
git push origin main
```

Comprueba en GitHub que aparezcan `Dockerfile`, `requirements.txt`,
`railway.toml`, `bot.py`, `web_app.py` y `reconocimiento.py`.

## 2. Crear el servicio

1. Entra a `https://railway.com` e inicia sesión con GitHub.
2. Selecciona **New Project** y después **Deploy from GitHub repo**.
3. Elige el repositorio `sistema-acceso-facial-telegram`.
4. Railway detectará el `Dockerfile` y comenzará la construcción.

## 3. Configurar variables

En el servicio abre **Variables** y agrega:

| Variable | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token real entregado por BotFather |
| `TELEGRAM_BOT_USERNAME` | Usuario del bot sin `@` |
| `REGISTRATION_CODE` | Una clave privada para la demostración |
| `FACE_MODEL` | `SFace` |
| `APP_DATA_DIR` | `data` |
| `DATABASE_PATH` | `data/sistema.db` |

No escribas el token ni la clave en GitHub. Railway volverá a desplegar el
servicio después de guardar las variables.

## 4. Generar el enlace público

1. Abre **Settings** o **Networking** en el servicio.
2. Selecciona **Generate Domain**.
3. Abre el dominio generado. Debe aparecer la página de estado del proyecto.
4. También puedes comprobar `https://TU-DOMINIO/estado`; debe responder con
   `"estado": "activo"`.

## 5. Probar la demostración

En Telegram:

1. Envía `/start`.
2. Envía `/publica`.
3. Envía `/registrar TU_CLAVE Nombre de prueba`.
4. Envía la primera imagen del banco como rostro de referencia.
5. Envía `/privada`.
6. Envía una imagen diferente de la misma persona; debe permitir el acceso.
7. Repite `/privada` con el rostro de otra persona; debe rechazarlo.

La primera comparación puede tardar porque DeepFace descarga e inicializa el
modelo. Usa fotografías frontales, claras y de una sola persona.

## Persistencia opcional

Sin un volumen, los registros y rostros pueden perderse al reconstruir el
servicio. Para conservarlos, agrega un volumen de Railway montado en
`/home/appuser/app/data` y cambia estas variables:

```text
APP_DATA_DIR=/home/appuser/app/data
DATABASE_PATH=/home/appuser/app/data/sistema.db
```

Para la demostración inmediata también puedes registrar de nuevo el rostro
después de cada despliegue.

## Si el despliegue falla

- Revisa **Deployments > View Logs**.
- `Falta configurar TELEGRAM_BOT_TOKEN`: falta la variable o el token.
- `Conflict: terminated by other getUpdates request`: el bot está ejecutándose
  al mismo tiempo en otra computadora; cierra el proceso local.
- Servicio reiniciado por memoria: aumenta los recursos del servicio, ya que
  DeepFace y TensorFlow requieren más memoria que un bot sencillo.
