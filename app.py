import os
from flask import Flask, redirect, session, url_for
from werkzeug.security import generate_password_hash
from database import get_db
from auth import auth_bp
from routes.admin import admin_bp
from routes.prestador import prestador_bp
from routes.solicitante import solicitante_bp
from routes.financiero import financiero_bp
from init_db import init_db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'amparo-clave-secreta-cambiar-en-produccion')

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(prestador_bp)
app.register_blueprint(solicitante_bp)
app.register_blueprint(financiero_bp)


@app.after_request
def remove_csp_header(response):
    """Elimina cualquier header CSP para evitar bloqueos en desarrollo."""
    response.headers.pop('Content-Security-Policy', None)
    response.headers.pop('X-Content-Security-Policy', None)
    response.headers.pop('X-WebKit-CSP', None)
    return response


@app.template_filter('fmt_tel')
def fmt_tel(tel):
    if not tel:
        return '—'
    t = tel.strip()
    return t if t.startswith('+') else f'+54 {t}'


with app.app_context():
    init_db()


# ---------------------------------------------------------------------------
# Raíz
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if 'tipo' not in session:
        return redirect(url_for('auth.login'))
    destinos = {
        'admin':            '/admin/dashboard',
        'admin_financiero': '/admin/dashboard',
        'prestador':        '/prestador/dashboard',
        'solicitante':      '/solicitante/dashboard',
    }
    return redirect(destinos.get(session['tipo'], url_for('auth.login')))


# ---------------------------------------------------------------------------
# Inicialización de admin
# ---------------------------------------------------------------------------

@app.route('/init')
def init_admin():
    from datetime import datetime
    db = get_db()
    admin = db.execute(
        "SELECT id FROM usuarios WHERE tipo_usuario IN ('admin', 'admin_financiero') LIMIT 1"
    ).fetchone()
    if admin:
        return 'Ya existe un administrador', 200
    pw_hash = generate_password_hash('Nahuel33#')
    db.execute(
        """INSERT INTO usuarios (nombre, apellido, email, password_hash, tipo_usuario, estado, fecha_password)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            'Jorge',
            'Agüero',
            'jorgeagueroar@yahoo.com.ar',
            pw_hash,
            'admin_financiero',
            'ACTIVA',
            datetime.now().isoformat(),
        )
    )
    db.commit()
    return (
        'Admin creado exitosamente.<br>'
        'Email: jorgeagueroar@yahoo.com.ar<br>'
        'Contraseña: Nahuel33#<br>'
        f'Hash generado: {pw_hash}<br><br>'
        '<a href="/login">Ir al login</a>'
    ), 200


@app.route('/reset-admin')
def reset_admin():
    from datetime import datetime
    from werkzeug.security import check_password_hash
    db = get_db()
    pw_hash = generate_password_hash('Nahuel33#')
    now = datetime.now().isoformat()
    existing = db.execute(
        "SELECT id FROM usuarios WHERE email='jorgeagueroar@yahoo.com.ar'"
    ).fetchone()
    if existing:
        db.execute(
            """UPDATE usuarios
               SET password_hash=?, intentos_fallidos=0, estado='ACTIVA', fecha_password=?
               WHERE email='jorgeagueroar@yahoo.com.ar'""",
            (pw_hash, now)
        )
        accion = 'Contraseña actualizada.'
    else:
        db.execute(
            """INSERT INTO usuarios (nombre, apellido, email, password_hash, tipo_usuario, estado, intentos_fallidos, fecha_password)
               VALUES ('Jorge', 'Aguero', ?, ?, 'admin_financiero', 'ACTIVA', 0, ?)""",
            ('jorgeagueroar@yahoo.com.ar', pw_hash, now)
        )
        accion = 'Usuario creado.'
    db.commit()
    u = db.execute(
        "SELECT password_hash, estado, intentos_fallidos, tipo_usuario FROM usuarios WHERE email='jorgeagueroar@yahoo.com.ar'"
    ).fetchone()
    verificacion = check_password_hash(u['password_hash'], 'Nahuel33#')
    return (
        f'{accion}<br>'
        'Email: jorgeagueroar@yahoo.com.ar<br>'
        'Contraseña: Nahuel33#<br>'
        f'Tipo: {u["tipo_usuario"]}<br>'
        f'Hash: {u["password_hash"]}<br>'
        f'Verificación: {verificacion}<br>'
        f'Estado: {u["estado"]}<br>'
        f'Intentos fallidos: {u["intentos_fallidos"]}<br><br>'
        '<a href="/login">Ir al login</a>'
    ), 200


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
