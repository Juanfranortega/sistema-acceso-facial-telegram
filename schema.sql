PRAGMA foreign_keys = ON;

-- Empleados autorizados para utilizar el bot
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    correo TEXT UNIQUE,
    nivel_acceso INTEGER NOT NULL DEFAULT 1
        CHECK (nivel_acceso BETWEEN 1 AND 2),
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
        CHECK (nivel_requerido BETWEEN 0 AND 2),
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