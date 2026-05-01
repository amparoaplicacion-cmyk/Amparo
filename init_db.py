from database import get_db
from werkzeug.security import generate_password_hash
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Tablas nuevas (zonas y categorias primero por las FK)
# ---------------------------------------------------------------------------

TABLAS_NUEVAS = '''
CREATE TABLE IF NOT EXISTS usuarios (
    id                      INTEGER  PRIMARY KEY AUTOINCREMENT,
    nombre                  TEXT     NOT NULL,
    apellido                TEXT     NOT NULL DEFAULT '',
    email                   TEXT     UNIQUE NOT NULL,
    telefono                TEXT,
    password_hash           TEXT     NOT NULL,
    tipo_usuario            TEXT     NOT NULL
                            CHECK(tipo_usuario IN
                                  ('admin', 'admin_financiero',
                                   'prestador', 'solicitante')),
    estado                  TEXT     DEFAULT 'ACTIVA',
    intentos_fallidos       INTEGER  DEFAULT 0,
    fecha_password          DATETIME,
    fecha_vencimiento       DATETIME,
    ultimo_ingreso          DATETIME,
    acepto_cobro_automatico INTEGER  DEFAULT 0,
    fecha_aceptacion_cobro  DATETIME,
    fecha_alta              DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_bloqueo           DATETIME,
    token_desbloqueo        TEXT,
    token_expira            DATETIME
);

CREATE TABLE IF NOT EXISTS zonas (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre   TEXT    NOT NULL UNIQUE,
    ciudad   TEXT,
    provincia TEXT,
    activa   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS categorias (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre         TEXT    NOT NULL UNIQUE,
    descripcion    TEXT,
    requisitos     TEXT,
    tarifa_minima  REAL    DEFAULT 0,
    tarifa_maxima  REAL    DEFAULT 0,
    activa         INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS prestadores (
    id                INTEGER  PRIMARY KEY AUTOINCREMENT,
    usuario_id        INTEGER  NOT NULL UNIQUE,
    categoria_id      INTEGER,
    foto_url          TEXT,
    descripcion       TEXT,
    experiencia_anios INTEGER  DEFAULT 0,
    estado_perfil     TEXT     DEFAULT 'EN_REVISION',
    dni_verificado    TEXT     DEFAULT 'PENDIENTE',
    antecedentes_ok   TEXT     DEFAULT 'PENDIENTE',
    certificados_ok   TEXT     DEFAULT 'PENDIENTE',
    motivo_rechazo    TEXT,
    fecha_aprobacion  DATETIME,
    FOREIGN KEY (usuario_id)   REFERENCES usuarios(id),
    FOREIGN KEY (categoria_id) REFERENCES categorias(id)
);

CREATE TABLE IF NOT EXISTS solicitantes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id           INTEGER NOT NULL UNIQUE,
    direccion            TEXT,
    zona_id              INTEGER,
    familiar_nombre          TEXT,
    familiar_edad            INTEGER,
    familiar_condicion       TEXT,
    familiar_necesidades     TEXT,
    latitud                  REAL,
    longitud                 REAL,
    codigo_postal            TEXT,
    localidad                TEXT,
    provincia                TEXT,
    ubicacion_actualizada    DATETIME,
    metodo_pago              TEXT,
    metodo_pago_descripcion  TEXT,
    mp_card_token            TEXT,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
    FOREIGN KEY (zona_id)    REFERENCES zonas(id)
);

CREATE TABLE IF NOT EXISTS disponibilidad (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    prestador_id INTEGER NOT NULL,
    dia_semana   TEXT    NOT NULL,
    hora_inicio  TEXT    NOT NULL,
    hora_fin     TEXT    NOT NULL,
    FOREIGN KEY (prestador_id) REFERENCES prestadores(id)
);

CREATE TABLE IF NOT EXISTS servicios (
    id                 INTEGER  PRIMARY KEY AUTOINCREMENT,
    solicitante_id         INTEGER  NOT NULL,
    prestador_id       INTEGER  NOT NULL,
    categoria_id       INTEGER,
    estado             TEXT     DEFAULT 'PENDIENTE',
    fecha_solicitud    DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_servicio     DATE     NOT NULL,
    hora_inicio        TEXT     NOT NULL,
    hora_fin           TEXT     NOT NULL,
    monto_acordado     REAL,
    mensaje_solicitante    TEXT,
    motivo_cancelacion TEXT,
    motivo_rechazo     TEXT,
    fecha_aceptacion   DATETIME,
    fecha_finalizacion DATETIME,
    FOREIGN KEY (solicitante_id)   REFERENCES solicitantes(id),
    FOREIGN KEY (prestador_id) REFERENCES prestadores(id),
    FOREIGN KEY (categoria_id) REFERENCES categorias(id)
);

CREATE TABLE IF NOT EXISTS calificaciones (
    id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    servicio_id  INTEGER  NOT NULL UNIQUE,
    solicitante_id   INTEGER  NOT NULL,
    prestador_id INTEGER  NOT NULL,
    puntaje      INTEGER  NOT NULL,
    comentario   TEXT,
    moderada     INTEGER  DEFAULT 0,
    fecha        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (servicio_id)  REFERENCES servicios(id),
    FOREIGN KEY (solicitante_id)   REFERENCES solicitantes(id),
    FOREIGN KEY (prestador_id) REFERENCES prestadores(id)
);

CREATE TABLE IF NOT EXISTS pagos (
    id                INTEGER  PRIMARY KEY AUTOINCREMENT,
    servicio_id       INTEGER  NOT NULL,
    solicitante_id        INTEGER  NOT NULL,
    prestador_id      INTEGER  NOT NULL,
    monto_bruto       REAL     NOT NULL,
    comision_pct      REAL     NOT NULL,
    comision_monto    REAL     NOT NULL,
    monto_neto        REAL     NOT NULL,
    estado            TEXT     DEFAULT 'PENDIENTE',
    metodo_pago       TEXT,
    token_externo     TEXT,
    fecha_pago        DATETIME,
    fecha_liquidacion DATETIME,
    FOREIGN KEY (servicio_id) REFERENCES servicios(id)
);

CREATE TABLE IF NOT EXISTS notificaciones (
    id         INTEGER  PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER  NOT NULL,
    tipo       TEXT     NOT NULL,
    titulo     TEXT     NOT NULL,
    mensaje    TEXT,
    leida      INTEGER  DEFAULT 0,
    fecha      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS reclamos (
    id               INTEGER  PRIMARY KEY AUTOINCREMENT,
    servicio_id      INTEGER  NOT NULL,
    iniciado_por     INTEGER  NOT NULL,
    descripcion      TEXT     NOT NULL,
    estado           TEXT     DEFAULT 'ABIERTO',
    resolucion       TEXT,
    fecha_apertura   DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_resolucion DATETIME,
    FOREIGN KEY (servicio_id)  REFERENCES servicios(id),
    FOREIGN KEY (iniciado_por) REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave              TEXT     PRIMARY KEY,
    valor              TEXT     NOT NULL,
    descripcion        TEXT,
    fecha_modificacion DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contactos (
    id               INTEGER  PRIMARY KEY AUTOINCREMENT,
    usuario_id       INTEGER  NOT NULL,
    tipo_usuario     TEXT     NOT NULL,
    tipo_contacto    TEXT     NOT NULL,
    asunto           TEXT     NOT NULL,
    descripcion      TEXT     NOT NULL,
    estado           TEXT     DEFAULT 'NUEVO',
    respuesta        TEXT,
    fecha_envio      DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_resolucion DATETIME,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS movimientos_financieros (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    fecha           DATETIME DEFAULT CURRENT_TIMESTAMP,
    tipo            TEXT     NOT NULL,
    descripcion     TEXT     NOT NULL,
    monto_entrada   REAL     DEFAULT 0,
    monto_salida    REAL     DEFAULT 0,
    saldo_acumulado REAL     DEFAULT 0,
    referencia      TEXT,
    pago_id         INTEGER,
    usuario_id      INTEGER,
    FOREIGN KEY (pago_id) REFERENCES pagos(id)
);
'''

CATEGORIAS_INICIALES = [
    ('Cuidador Domiciliario',      'Cuidado y asistencia en el hogar',        None, 0, 0),
    ('Acompañante Terapéutico',    'Acompañamiento y apoyo terapéutico',      None, 0, 0),
    ('Enfermero Domiciliario',     'Atención de enfermería en el domicilio',  None, 0, 0),
]

CONFIGURACION_INICIAL = [
    ('password_vigencia_dias',   '90',        'Días de vigencia de contraseña'),
    ('password_min_longitud',    '8',         'Longitud mínima de contraseña'),
    ('password_max_intentos',    '3',         'Intentos fallidos antes de bloqueo'),
    ('comision_pct_default',     '15',        'Comisión por defecto (%)'),
    ('comision_tipo',            'porcentaje','Tipo de comisión: porcentaje o monto_fijo'),
    ('comision_fijo',            '0',         'Monto fijo de comisión por transacción'),
    ('empresa_nombre',           'AMPARO',    'Nombre de la empresa'),
    ('empresa_email',            '',          'Email de contacto'),
    ('empresa_telefono',         '',          'Teléfono de contacto'),
    ('app_url',                  'http://127.0.0.1:5000', 'URL base de la aplicación'),
    ('factura_monto_limite',     '200000',    'Monto mensual a partir del cual se exige factura al prestador (en pesos)'),
    ('mp_public_key',            '',          'Clave pública de Mercado Pago'),
    ('mp_access_token',          '',          'Token de acceso de Mercado Pago'),
    ('mp_modo',                  'sandbox',   'Modo de Mercado Pago: sandbox o produccion'),
    ('cancelacion_penalidad_pct','10',        'Porcentaje de penalidad por cancelación después de aceptación'),
    ('cancelacion_prestador_pct','70',        'Del 10% de penalidad, porcentaje que va al prestador'),
    ('cancelacion_amparo_pct',   '30',        'Del 10% de penalidad, porcentaje que va a AMPARO'),
    ('geofence_radio_metros',    '50',        'Radio en metros para verificar llegada del prestador'),
    ('confirmacion_horas_limite','2',         'Horas después del fin del servicio para confirmar antes de escalar al admin'),
    ('comision_solicitante_pct', '15',        'Porcentaje que paga el solicitante sobre el monto del servicio'),
    ('comision_prestador_pct',   '7',         'Porcentaje que se descuenta al prestador sobre el monto del servicio'),
    # Plantillas de correo
    ('mail_bienvenida_asunto',                '', 'Asunto del correo de bienvenida'),
    ('mail_bienvenida_cuerpo',                '', 'Cuerpo del correo de bienvenida'),
    ('mail_desbloqueo_asunto',                '', 'Asunto del correo de desbloqueo de cuenta'),
    ('mail_desbloqueo_cuerpo',                '', 'Cuerpo del correo de desbloqueo de cuenta'),
    ('mail_contrasena_temp_asunto',           '', 'Asunto del correo de contraseña temporal'),
    ('mail_contrasena_temp_cuerpo',           '', 'Cuerpo del correo de contraseña temporal'),
    ('mail_vencimiento_asunto',               '', 'Asunto del correo de vencimiento próximo'),
    ('mail_vencimiento_cuerpo',               '', 'Cuerpo del correo de vencimiento próximo'),
    ('mail_perfil_aprobado_asunto',           '', 'Asunto del correo de perfil aprobado'),
    ('mail_perfil_aprobado_cuerpo',           '', 'Cuerpo del correo de perfil aprobado'),
    ('mail_perfil_rechazado_asunto',          '', 'Asunto del correo de perfil rechazado'),
    ('mail_perfil_rechazado_cuerpo',          '', 'Cuerpo del correo de perfil rechazado'),
    ('mail_registro_prestador_asunto',        '', 'Asunto del correo al registrarse un prestador'),
    ('mail_registro_prestador_cuerpo',        '', 'Cuerpo del correo al registrarse un prestador'),
    ('mail_recibo_pago_asunto',               '', 'Asunto del recibo de pago al solicitante'),
    ('mail_recibo_pago_cuerpo',               '', 'Cuerpo del recibo de pago al solicitante'),
    ('mail_pago_liquidado_asunto',            '', 'Asunto del correo de pago liquidado al prestador'),
    ('mail_pago_liquidado_cuerpo',            '', 'Cuerpo del correo de pago liquidado al prestador'),
    ('mail_cancelacion_sin_penalidad_asunto', '', 'Asunto del correo de cancelación sin penalidad'),
    ('mail_cancelacion_sin_penalidad_cuerpo', '', 'Cuerpo del correo de cancelación sin penalidad'),
    ('mail_cancelacion_con_penalidad_asunto', '', 'Asunto del correo de cancelación con penalidad'),
    ('mail_cancelacion_con_penalidad_cuerpo', '', 'Cuerpo del correo de cancelación con penalidad'),
    ('mail_respuesta_contacto_asunto',        '', 'Asunto del correo de respuesta a mensaje de contacto'),
    ('mail_respuesta_contacto_cuerpo',        '', 'Cuerpo del correo de respuesta a mensaje de contacto'),
    # Empresa
    ('empresa_web',                  '',          'Sitio web de la empresa'),
    # Admin financiero
    ('admin_financiero_email',  'jorgeagueroar@yahoo.com.ar',
     'Email del administrador financiero para recibir el resumen diario de movimientos'),
    ('cierre_diario_hora',      '00:00',
     'Hora a la que se genera el cierre diario automático'),
    ('movimientos_backup_dias', '3650',
     'Días que se conservan los backups de movimientos (10 años = 3650 días)'),
    ('ultimo_cierre_diario',    '',
     'Fecha del último cierre diario generado (YYYY-MM-DD)'),
]

USUARIOS_PRUEBA = [
    ('Administrador', 'AMPARO',  'admin@amparo.com',      'Admin123!',  'admin'),
]

# Emails de usuarios de prueba que NUNCA deben existir en producción
USUARIOS_PRUEBA_ELIMINAR = [
    'prestador@amparo.com',
    'solicitante@amparo.com',
    'familia@amparo.com',
    'prestador1@amparo.com',
    'solicitante1@amparo.com',
]


# ---------------------------------------------------------------------------
# Migración de la tabla usuarios existente
# ---------------------------------------------------------------------------

def migrar_usuarios(db):
    cols = {row[1] for row in db.execute('PRAGMA table_info(usuarios)')}

    # Renombrar columnas
    if 'tipo' in cols and 'tipo_usuario' not in cols:
        db.execute('ALTER TABLE usuarios RENAME COLUMN tipo TO tipo_usuario')
        cols.add('tipo_usuario')
        cols.discard('tipo')

    if 'fecha_cambio_password' in cols and 'fecha_password' not in cols:
        db.execute('ALTER TABLE usuarios RENAME COLUMN fecha_cambio_password TO fecha_password')
        cols.add('fecha_password')
        cols.discard('fecha_cambio_password')

    if 'fecha_creacion' in cols and 'fecha_alta' not in cols:
        db.execute('ALTER TABLE usuarios RENAME COLUMN fecha_creacion TO fecha_alta')
        cols.add('fecha_alta')
        cols.discard('fecha_creacion')

    # Agregar columnas nuevas
    if 'apellido' not in cols:
        db.execute("ALTER TABLE usuarios ADD COLUMN apellido TEXT NOT NULL DEFAULT ''")

    if 'telefono' not in cols:
        db.execute('ALTER TABLE usuarios ADD COLUMN telefono TEXT')

    if 'fecha_vencimiento' not in cols:
        db.execute("ALTER TABLE usuarios ADD COLUMN fecha_vencimiento DATE")
        db.execute("""
            UPDATE usuarios
            SET fecha_vencimiento = date(fecha_password, '+90 days')
            WHERE fecha_password IS NOT NULL
        """)

    if 'fecha_bloqueo' not in cols:
        db.execute('ALTER TABLE usuarios ADD COLUMN fecha_bloqueo DATETIME')

    if 'ultimo_ingreso' not in cols:
        db.execute('ALTER TABLE usuarios ADD COLUMN ultimo_ingreso DATETIME')

    if 'fecha_alta' not in cols:
        db.execute("ALTER TABLE usuarios ADD COLUMN fecha_alta DATETIME DEFAULT CURRENT_TIMESTAMP")


# ---------------------------------------------------------------------------
# Inicialización principal
# ---------------------------------------------------------------------------

def migrar_prestadores(db):
    cols = {row[1] for row in db.execute('PRAGMA table_info(prestadores)')}
    if 'zona_id' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN zona_id INTEGER REFERENCES zonas(id)')
    if 'numero_dni' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN numero_dni TEXT')
    if 'certificado_url' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN certificado_url TEXT')
    if 'cbu' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN cbu TEXT')
    if 'alias_mp' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN alias_mp TEXT')
    if 'email_mp' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN email_mp TEXT')
    if 'metodo_cobro' not in cols:
        db.execute("ALTER TABLE prestadores ADD COLUMN metodo_cobro TEXT DEFAULT 'mercadopago'")
    if 'cuit' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN cuit TEXT')
    if 'condicion_fiscal' not in cols:
        db.execute("ALTER TABLE prestadores ADD COLUMN condicion_fiscal TEXT DEFAULT 'no_informada'")
    if 'factura_requerida' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN factura_requerida INTEGER DEFAULT 0')
    if 'cv_url' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN cv_url TEXT')
    if 'cv_email_enviado' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN cv_email_enviado INTEGER DEFAULT 0')
    if 'dni_foto_frente_url' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN dni_foto_frente_url TEXT')
    if 'dni_foto_selfie_url' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN dni_foto_selfie_url TEXT')
    if 'latitud' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN latitud REAL')
    if 'longitud' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN longitud REAL')
    if 'codigo_postal' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN codigo_postal TEXT')
    if 'localidad' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN localidad TEXT')
    if 'provincia' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN provincia TEXT')
    if 'radio_cobertura_km' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN radio_cobertura_km INTEGER DEFAULT 10')
    if 'ubicacion_actualizada' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN ubicacion_actualizada DATETIME')
    if 'tarifa_hora' not in cols:
        db.execute('ALTER TABLE prestadores ADD COLUMN tarifa_hora REAL DEFAULT 0')


def migrar_categorias(db):
    cols = {row[1] for row in db.execute('PRAGMA table_info(categorias)')}
    if 'tarifa_hora' not in cols:
        db.execute('ALTER TABLE categorias ADD COLUMN tarifa_hora REAL DEFAULT 0')


def migrar_servicios(db):
    cols = {row[1] for row in db.execute('PRAGMA table_info(servicios)')}
    if 'tarifa_hora' not in cols:
        db.execute('ALTER TABLE servicios ADD COLUMN tarifa_hora REAL')
    if 'horas_estimadas' not in cols:
        db.execute('ALTER TABLE servicios ADD COLUMN horas_estimadas REAL')
    if 'monto_estimado' not in cols:
        db.execute('ALTER TABLE servicios ADD COLUMN monto_estimado REAL')
    if 'comision_estimada' not in cols:
        db.execute('ALTER TABLE servicios ADD COLUMN comision_estimada REAL')
    if 'total_estimado' not in cols:
        db.execute('ALTER TABLE servicios ADD COLUMN total_estimado REAL')


def migrar_servicios_confirmacion(db):
    cols = {row[1] for row in db.execute('PRAGMA table_info(servicios)')}
    nuevas = [
        ('prestador_confirmo_llegada',    'INTEGER DEFAULT 0'),
        ('prestador_lat_llegada',         'REAL'),
        ('prestador_lon_llegada',         'REAL'),
        ('fecha_llegada',                 'DATETIME'),
        ('distancia_llegada_metros',      'REAL'),
        ('prestador_confirmo_fin',        'INTEGER DEFAULT 0'),
        ('fecha_confirmacion_prestador',  'DATETIME'),
        ('solicitante_confirmo_fin',          'INTEGER DEFAULT 0'),
        ('fecha_confirmacion_solicitante',    'DATETIME'),
        ('conflicto',                     'INTEGER DEFAULT 0'),
        ('motivo_conflicto',              'TEXT'),
    ]
    for col, tipo in nuevas:
        if col not in cols:
            db.execute(f'ALTER TABLE servicios ADD COLUMN {col} {tipo}')


def migrar_pagos(db):
    cols = {row[1] for row in db.execute('PRAGMA table_info(pagos)')}
    if 'tipo_pago' not in cols:
        db.execute("ALTER TABLE pagos ADD COLUMN tipo_pago TEXT DEFAULT 'servicio'")
    if 'metodo_cobro_prestador' not in cols:
        db.execute('ALTER TABLE pagos ADD COLUMN metodo_cobro_prestador TEXT')
    if 'referencia_pago' not in cols:
        db.execute('ALTER TABLE pagos ADD COLUMN referencia_pago TEXT')
    if 'comision_solicitante' not in cols:
        db.execute('ALTER TABLE pagos ADD COLUMN comision_solicitante REAL DEFAULT 0')
    if 'comision_prestador' not in cols:
        db.execute('ALTER TABLE pagos ADD COLUMN comision_prestador REAL DEFAULT 0')
    if 'disbursement_id' not in cols:
        db.execute('ALTER TABLE pagos ADD COLUMN disbursement_id TEXT')
    if 'disbursement_estado' not in cols:
        db.execute("ALTER TABLE pagos ADD COLUMN disbursement_estado TEXT DEFAULT 'PENDIENTE'")
    if 'disbursement_fecha' not in cols:
        db.execute('ALTER TABLE pagos ADD COLUMN disbursement_fecha DATETIME')
    if 'disbursement_error' not in cols:
        db.execute('ALTER TABLE pagos ADD COLUMN disbursement_error TEXT')


def migrar_solicitantes(db):
    cols = {row[1] for row in db.execute('PRAGMA table_info(solicitantes)')}
    if 'latitud' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN latitud REAL')
    if 'longitud' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN longitud REAL')
    if 'codigo_postal' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN codigo_postal TEXT')
    if 'localidad' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN localidad TEXT')
    if 'provincia' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN provincia TEXT')
    if 'ubicacion_actualizada' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN ubicacion_actualizada DATETIME')
    if 'metodo_pago' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN metodo_pago TEXT')
    if 'metodo_pago_descripcion' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN metodo_pago_descripcion TEXT')
    if 'mp_card_token' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN mp_card_token TEXT')
    if 'mp_card_payment_method' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN mp_card_payment_method TEXT')
    if 'mp_customer_id' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN mp_customer_id TEXT')
    if 'mp_card_id' not in cols:
        db.execute('ALTER TABLE solicitantes ADD COLUMN mp_card_id TEXT')


def migrar_usuarios_cobro_automatico(db):
    cols = {row[1] for row in db.execute('PRAGMA table_info(usuarios)')}
    if 'acepto_cobro_automatico' not in cols:
        db.execute("ALTER TABLE usuarios ADD COLUMN acepto_cobro_automatico INTEGER DEFAULT 0")
    if 'fecha_aceptacion_cobro' not in cols:
        db.execute("ALTER TABLE usuarios ADD COLUMN fecha_aceptacion_cobro DATETIME")


def migrar_usuarios_check_constraint(db):
    """
    Actualiza el CHECK constraint de tipo_usuario para incluir 'admin_financiero'.
    SQLite no permite ALTER TABLE en constraints: hay que recrear la tabla.
    """
    schema_row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='usuarios'"
    ).fetchone()
    if schema_row and 'admin_financiero' in (schema_row[0] or ''):
        return  # Ya está actualizado

    # Obtener columnas reales de la tabla actual
    col_names = [row[1] for row in db.execute('PRAGMA table_info(usuarios)').fetchall()]

    # Crear tabla nueva con CHECK constraint actualizado
    db.execute('''CREATE TABLE usuarios_nueva (
        id                      INTEGER  PRIMARY KEY AUTOINCREMENT,
        nombre                  TEXT     NOT NULL,
        apellido                TEXT     NOT NULL DEFAULT '',
        email                   TEXT     UNIQUE NOT NULL,
        telefono                TEXT,
        password_hash           TEXT     NOT NULL,
        tipo_usuario            TEXT     NOT NULL
                                CHECK(tipo_usuario IN
                                      ('admin', 'admin_financiero',
                                       'prestador', 'solicitante')),
        estado                  TEXT     DEFAULT 'ACTIVA',
        intentos_fallidos       INTEGER  DEFAULT 0,
        fecha_password          DATETIME,
        fecha_vencimiento       DATETIME,
        ultimo_ingreso          DATETIME,
        acepto_cobro_automatico INTEGER  DEFAULT 0,
        fecha_aceptacion_cobro  DATETIME,
        fecha_alta              DATETIME DEFAULT CURRENT_TIMESTAMP,
        fecha_bloqueo           DATETIME,
        token_desbloqueo        TEXT,
        token_expira            DATETIME
    )''')

    # Copiar solo las columnas que existen en la tabla actual
    known_cols = {
        'id', 'nombre', 'apellido', 'email', 'telefono', 'password_hash',
        'tipo_usuario', 'estado', 'intentos_fallidos', 'fecha_password',
        'fecha_vencimiento', 'ultimo_ingreso', 'acepto_cobro_automatico',
        'fecha_aceptacion_cobro', 'fecha_alta', 'fecha_bloqueo',
        'token_desbloqueo', 'token_expira',
    }
    common = [c for c in col_names if c in known_cols]
    cols_str = ', '.join(common)
    db.execute(
        f'INSERT INTO usuarios_nueva ({cols_str}) SELECT {cols_str} FROM usuarios'
    )
    db.execute('DROP TABLE usuarios')
    db.execute('ALTER TABLE usuarios_nueva RENAME TO usuarios')
    db.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)'
    )


def init_db():
    db = get_db()

    # 1. Crear / asegurar todas las tablas (incluye usuarios)
    db.executescript(TABLAS_NUEVAS)

    # 2. Migrar tablas existentes (solo aplica si hay columnas viejas)
    migrar_usuarios(db)
    migrar_prestadores(db)
    migrar_solicitantes(db)
    migrar_categorias(db)
    migrar_servicios(db)
    migrar_servicios_confirmacion(db)
    migrar_pagos(db)
    migrar_usuarios_cobro_automatico(db)
    migrar_usuarios_check_constraint(db)
    db.commit()

    # 3. Insertar categorías iniciales
    for nombre, desc, req, t_min, t_max in CATEGORIAS_INICIALES:
        existe = db.execute('SELECT id FROM categorias WHERE nombre = ?', (nombre,)).fetchone()
        if not existe:
            db.execute(
                'INSERT OR IGNORE INTO categorias (nombre, descripcion, requisitos, tarifa_minima, tarifa_maxima) VALUES (?, ?, ?, ?, ?)',
                (nombre, desc, req, t_min, t_max)
            )

    # 4. Insertar configuración inicial
    for clave, valor, desc in CONFIGURACION_INICIAL:
        existe = db.execute('SELECT clave FROM configuracion WHERE clave = ?', (clave,)).fetchone()
        if not existe:
            db.execute(
                'INSERT OR IGNORE INTO configuracion (clave, valor, descripcion) VALUES (?, ?, ?)',
                (clave, valor, desc)
            )

    # 5. Insertar usuarios de prueba
    fecha_hoy       = date.today().isoformat()
    fecha_venc      = (date.today() + timedelta(days=90)).isoformat()

    # 5a. Eliminar usuarios de prueba que no deben existir en producción
    for email_prueba in USUARIOS_PRUEBA_ELIMINAR:
        u = db.execute('SELECT id FROM usuarios WHERE email=?', (email_prueba,)).fetchone()
        if u:
            uid_p = u['id']
            pre = db.execute('SELECT id FROM prestadores WHERE usuario_id=?', (uid_p,)).fetchone()
            if pre:
                db.execute('DELETE FROM disponibilidad WHERE prestador_id=?', (pre['id'],))
                db.execute('DELETE FROM prestadores WHERE id=?', (pre['id'],))
            db.execute('DELETE FROM solicitantes WHERE usuario_id=?', (uid_p,))
            db.execute('DELETE FROM notificaciones WHERE usuario_id=?', (uid_p,))
            db.execute('DELETE FROM usuarios WHERE id=?', (uid_p,))
            print(f"  [LIMPIEZA] Usuario de prueba eliminado: {email_prueba}")
    db.commit()

    # 5b. Insertar usuarios necesarios (solo admin)
    for nombre, apellido, email, password, tipo in USUARIOS_PRUEBA:
        existe = db.execute('SELECT id FROM usuarios WHERE email = ?', (email,)).fetchone()
        if not existe:
            uid = db.execute(
                '''INSERT OR IGNORE INTO usuarios
                   (nombre, apellido, email, password_hash, tipo_usuario,
                    fecha_password, fecha_vencimiento)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (nombre, apellido, email, generate_password_hash(password),
                 tipo, fecha_hoy, fecha_venc)
            ).lastrowid

            # Crear perfil en prestadores o solicitantes si corresponde
            if tipo == 'prestador':
                db.execute(
                    '''INSERT OR IGNORE INTO prestadores
                       (usuario_id, estado_perfil,
                        dni_verificado, antecedentes_ok, certificados_ok)
                       VALUES (?, 'EN_REVISION', 'PENDIENTE', 'PENDIENTE', 'PENDIENTE')''',
                    (uid,)
                )
            elif tipo == 'solicitante':
                db.execute('INSERT OR IGNORE INTO solicitantes (usuario_id) VALUES (?)', (uid,))

    db.commit()

    # 6. Reporte final
    tablas = [row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]

    print("\n" + "=" * 55)
    print("  AMPARO - Base de datos lista")
    print("=" * 55)
    print(f"\n  Tablas creadas/verificadas ({len(tablas)}):")
    for t in tablas:
        print(f"    OK  {t}")

    print("\n  Usuarios de prueba:")
    print(f"  {'Tipo':<12} {'Email':<30} {'Password'}")
    print(f"  {'-'*12} {'-'*30} {'-'*10}")
    for nombre, apellido, email, password, tipo in USUARIOS_PRUEBA:
        print(f"  {tipo:<12} {email:<30} {password}")
    print("=" * 55 + "\n")

    db.close()


if __name__ == '__main__':
    init_db()
