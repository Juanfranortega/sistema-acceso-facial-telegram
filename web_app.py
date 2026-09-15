import os

from flask import Flask, jsonify, render_template_string

from database import obtener_estadisticas


app = Flask(__name__)
_bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "").lstrip("@")


def configurar_bot(username):
    global _bot_username
    _bot_username = (username or "").lstrip("@")


@app.get("/")
def inicio():
    estadisticas = obtener_estadisticas()
    enlace_bot = f"https://t.me/{_bot_username}" if _bot_username else "#"
    boton_deshabilitado = "" if _bot_username else "disabled"

    return render_template_string(
        """
        <!doctype html>
        <html lang="es">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Acceso Facial Empresarial</title>
          <style>
            :root { color-scheme: dark; --azul:#58a6ff; --verde:#3fb950; }
            * { box-sizing:border-box; }
            body { margin:0; min-height:100vh; font-family:Arial,sans-serif;
              background:linear-gradient(135deg,#07111f,#101d36); color:#eef4ff;
              display:grid; place-items:center; padding:24px; }
            main { width:min(920px,100%); background:rgba(13,27,49,.92);
              border:1px solid #29496e; border-radius:24px; padding:38px;
              box-shadow:0 24px 70px rgba(0,0,0,.38); }
            .estado { display:inline-flex; gap:9px; align-items:center; color:#bdf5c7;
              background:#153c27; padding:8px 13px; border-radius:999px; font-weight:700; }
            .punto { width:10px; height:10px; border-radius:50%; background:var(--verde);
              box-shadow:0 0 14px var(--verde); }
            h1 { font-size:clamp(30px,5vw,52px); margin:22px 0 14px; line-height:1.05; }
            .lead { color:#b8c8dd; font-size:19px; line-height:1.6; max-width:760px; }
            .grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:28px 0; }
            .tarjeta { background:#0a172a; border:1px solid #243e60; border-radius:16px;
              padding:19px; }
            .numero { display:block; color:var(--azul); font-size:30px; font-weight:800; }
            .etiqueta { color:#9eb1c9; }
            .pasos { background:#0a172a; border-radius:16px; padding:18px 22px; line-height:1.8; }
            a.boton { display:inline-block; margin-top:24px; color:#06121f; background:#62b0ff;
              text-decoration:none; font-weight:800; padding:14px 22px; border-radius:12px; }
            a.disabled { pointer-events:none; opacity:.5; }
            footer { color:#8195ad; margin-top:24px; font-size:14px; }
            @media (max-width:650px) { main{padding:25px}.grid{grid-template-columns:1fr} }
          </style>
        </head>
        <body>
          <main>
            <span class="estado"><span class="punto"></span>Sistema en línea</span>
            <h1>Acceso seguro mediante reconocimiento facial</h1>
            <p class="lead">Prueba de concepto que integra Telegram, Python, DeepFace y SQLite
              para proteger la consulta de información empresarial.</p>
            <section class="grid">
              <div class="tarjeta"><span class="numero">{{ usuarios }}</span><span class="etiqueta">Usuarios registrados</span></div>
              <div class="tarjeta"><span class="numero">{{ informacion }}</span><span class="etiqueta">Elementos informativos</span></div>
              <div class="tarjeta"><span class="numero">{{ intentos }}</span><span class="etiqueta">Intentos registrados</span></div>
            </section>
            <section class="pasos">
              <strong>Demostración:</strong><br>
              1. Abre el bot de Telegram.<br>
              2. Registra una fotografía facial autorizada.<br>
              3. Solicita información privada.<br>
              4. Envía una segunda fotografía para verificar la identidad.
            </section>
            <a class="boton {{ boton_deshabilitado }}" href="{{ enlace_bot }}" target="_blank" rel="noopener">Abrir bot en Telegram</a>
            <footer>Proyecto académico · Ingeniería de Software II · UPSLP</footer>
          </main>
        </body>
        </html>
        """,
        **estadisticas,
        enlace_bot=enlace_bot,
        boton_deshabilitado=boton_deshabilitado
    )


@app.get("/estado")
def estado():
    return jsonify({"estado": "activo", **obtener_estadisticas()})


def iniciar_servidor_web():
    puerto = int(os.getenv("PORT", "7860"))
    app.run(host="0.0.0.0", port=puerto, use_reloader=False)
