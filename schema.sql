PRAGMA foreign_keys = ON;

-- Empleados autorizados para utilizar el bot
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    correo TEXT UNIQUE,

    rol TEXT NOT NULL DEFAULT 'EMPLEADO'
        CHECK (rol IN ('ADMIN', 'EJECUTIVO', 'EMPLEADO')),

    nivel_acceso INTEGER NOT NULL DEFAULT 1
        CHECK (nivel_acceso BETWEEN 1 AND 3),

    password_hash TEXT,

    debe_configurar_clave INTEGER NOT NULL DEFAULT 1
        CHECK (debe_configurar_clave IN (0, 1)),

    activo INTEGER NOT NULL DEFAULT 1
        CHECK (activo IN (0, 1)),

    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Rostro de referencia asociado con cada empleado
CREATE TABLE IF NOT EXISTS perfiles_faciales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL UNIQUE,
    ruta_referencia TEXT NOT NULL,
    modelo_utilizado TEXT NOT NULL DEFAULT 'Facenet512',
    fecha_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (usuario_id)
        REFERENCES usuarios(id)
        ON DELETE CASCADE
);

-- Información que será consultada mediante Telegram
CREATE TABLE IF NOT EXISTS informacion_empresarial (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    contenido TEXT NOT NULL,
    nivel_requerido INTEGER NOT NULL DEFAULT 0
        CHECK (nivel_requerido BETWEEN 0 AND 3),
    activa INTEGER NOT NULL DEFAULT 1
        CHECK (activa IN (0, 1)),
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Historial de accesos permitidos y rechazados
CREATE TABLE IF NOT EXISTS registros_autenticacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER,
    telegram_id INTEGER NOT NULL,
    resultado TEXT NOT NULL
        CHECK (resultado IN ('EXITOSO', 'RECHAZADO', 'ERROR')),
    distancia REAL,
    motivo TEXT,
    fecha_intento DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (usuario_id)
        REFERENCES usuarios(id)
        ON DELETE SET NULL
);

-- Solicitudes autorizadas para actualizar fotografías faciales
CREATE TABLE IF NOT EXISTS solicitudes_actualizacion_facial (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    usuario_id INTEGER NOT NULL UNIQUE,
    solicitada_por INTEGER NOT NULL,

    estado TEXT NOT NULL DEFAULT 'ESPERANDO_CLAVE'
        CHECK (
            estado IN ('ESPERANDO_CLAVE', 'ESPERANDO_FOTO')
        ),

    fecha_solicitud DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_confirmacion DATETIME,
    fecha_expiracion DATETIME NOT NULL,

    FOREIGN KEY (usuario_id)
        REFERENCES usuarios(id)
        ON DELETE CASCADE,

    FOREIGN KEY (solicitada_por)
        REFERENCES usuarios(id)
        ON DELETE RESTRICT
);


-- Historial de acciones administrativas y modificaciones de perfiles
CREATE TABLE IF NOT EXISTS registros_administrativos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    responsable_id INTEGER,
    responsable_telegram_id INTEGER NOT NULL,
    responsable_nombre TEXT NOT NULL,
    responsable_rol TEXT NOT NULL,

    usuario_objetivo_id INTEGER,
    usuario_objetivo_telegram_id INTEGER,
    usuario_objetivo_nombre TEXT,

    accion TEXT NOT NULL,
    detalle TEXT,

    fecha_accion DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (responsable_id)
        REFERENCES usuarios(id)
        ON DELETE SET NULL,

    FOREIGN KEY (usuario_objetivo_id)
        REFERENCES usuarios(id)
        ON DELETE SET NULL
);

-- Índice para consultar las acciones más recientes.
CREATE INDEX IF NOT EXISTS idx_registros_administrativos_fecha
ON registros_administrativos(fecha_accion);

-- Índice para consultar las operaciones de un usuario específico.
CREATE INDEX IF NOT EXISTS idx_registros_administrativos_objetivo
ON registros_administrativos(usuario_objetivo_id);
