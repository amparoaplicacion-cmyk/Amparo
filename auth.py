import base64
import os
import re
import secrets
import smtplib
import ssl
import requests
from datetime import date, datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import (Blueprint, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from database import get_db

_BASE_DIR                 = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER_PRESTADORES = os.path.join(_BASE_DIR, 'static', 'uploads', 'prestadores')
UPLOAD_FOLDER_DNI         = os.path.join(_BASE_DIR, 'static', 'docs', 'dni', 'prestadores')
ALLOWED_EXTS = {'jpg', 'jpeg', 'png', 'webp'}

def _subir_imagen_cloudinary(file_storage, public_id, folder):
    """Sube un FileStorage a Cloudinary si CLOUDINARY_URL está configurada.
    Retorna la URL segura (str) o None si falla / no está configurado."""
    cloudinary_url = os.environ.get('CLOUDINARY_URL', '')
    if not cloudinary_url:
        return None
    try:
        import cloudinary
        import cloudinary.uploader
        # La librería lee CLOUDINARY_URL automáticamente del entorno.
        result = cloudinary.uploader.upload(
            file_storage.stream,
            public_id=public_id,
            folder=folder,
            overwrite=True,
            resource_type='image',
        )
        return result.get('secure_url')
    except Exception:
        return None


DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
FRANJAS_REG = [
    ('manana', 'Mañana',  '08:00', '12:00'),
    ('tarde',  'Tarde',   '12:00', '18:00'),
    ('noche',  'Noche',   '18:00', '22:00'),
]

auth_bp = Blueprint('auth', __name__)

INTENTOS_MAX = 3
VIGENCIA_PASSWORD_DIAS = 90
VIGENCIA_TOKEN_HORAS = 24

RUTAS_POR_TIPO = {
    'admin':             '/admin/dashboard',
    'admin_financiero':  '/admin/dashboard',
    'prestador':         '/prestador/dashboard',
    'solicitante':       '/solicitante/dashboard',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validar_password(password):
    errores = []
    if len(password) < 8:
        errores.append("al menos 8 caracteres")
    if not re.search(r'[A-Z]', password):
        errores.append("al menos una letra mayúscula")
    if not re.search(r'[^a-zA-Z0-9]', password):
        errores.append("al menos un carácter especial (ej: # $ @ ! _)")
    return len(errores) == 0, errores


def password_vencida(fecha_cambio_str):
    if not fecha_cambio_str:
        return False
    fecha_cambio = datetime.fromisoformat(fecha_cambio_str)
    return datetime.now() > fecha_cambio + timedelta(days=VIGENCIA_PASSWORD_DIAS)


def _cfg_db(clave, default=''):
    """Lee una clave de la tabla configuracion."""
    try:
        row = get_db().execute(
            'SELECT valor FROM configuracion WHERE clave=?', (clave,)
        ).fetchone()
        return (row['valor'] if row['valor'] else default) if row else default
    except Exception:
        return default


def _get_logo_base64():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ruta = os.path.join(base_dir, 'static', 'img', 'amparo_logo.svg')
    if os.path.exists(ruta):
        with open(ruta, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    return ''


def enviar_email(destinatario, asunto, texto_cuerpo,
                 adjunto_path=None, adjunto_nombre=None):
    """
    Función central de envío de correos.
    texto_cuerpo: texto plano con saltos de línea y variables ya reemplazadas.
    Se envuelve automáticamente en la plantilla HTML con logo, diseño y footer.
    adjunto_path: ruta al archivo a adjuntar (opcional)
    adjunto_nombre: nombre del archivo en el correo (opcional)
    """
    # Nuevas claves (configuradas desde el panel admin)
    smtp_host  = _cfg_db('mail_servidor', '') or os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port  = int(_cfg_db('mail_puerto', '') or os.environ.get('SMTP_PORT', '587'))
    smtp_user  = _cfg_db('mail_usuario', '') or os.environ.get('SMTP_USER', '')
    smtp_pass  = _cfg_db('mail_password', '') or os.environ.get('SMTP_PASS', '')
    usar_tls   = bool(int(_cfg_db('mail_tls', '1') or '1'))
    remitente  = _cfg_db('mail_remitente', '') or smtp_user

    if not smtp_user or not smtp_pass:
        print(f"[AMPARO] Email '{asunto}' para {destinatario} — SMTP no configurado.")
        return False

    app_url       = _cfg_db('app_url', 'http://127.0.0.1:5000')
    logo_b64      = _get_logo_base64()
    empresa_email = _cfg_db('empresa_email', '')
    empresa_web   = _cfg_db('empresa_web', '')
    print(f"[EMAIL] Logo b64 len={len(logo_b64)} | empresa_email='{empresa_email}' | para={destinatario}")

    cuerpo_html = texto_cuerpo.replace('\n', '<br>')

    contacto_partes = []
    if empresa_email:
        contacto_partes.append(f'📧 &nbsp;{empresa_email}')
    if empresa_web:
        contacto_partes.append(f'🌐 &nbsp;{empresa_web}')
    contacto_html = '&nbsp;&nbsp;&nbsp;'.join(contacto_partes)

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#F2F3F4; font-family: Arial, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background-color:#F2F3F4; padding: 30px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="max-width:600px; width:100%;">

          <!-- LOGO -->
          <tr>
            <td align="center"
                style="background-color:#EAF4FB;
                       padding: 30px 40px 20px;
                       border-radius: 12px 12px 0 0;">
              <img src="data:image/svg+xml;base64,{logo_b64}"
                   alt="AMPARO"
                   width="280"
                   style="width:280px; height:auto; display:block; margin:0 auto;">
            </td>
          </tr>

          <!-- CUERPO DEL CORREO -->
          <tr>
            <td style="background-color:#FFFFFF;
                       padding: 36px 48px;
                       font-size: 15px;
                       line-height: 1.8;
                       color: #2C3E50;">
              {cuerpo_html}
            </td>
          </tr>

          <!-- SEPARADOR -->
          <tr>
            <td style="background-color:#FFFFFF; padding: 0 48px;">
              <hr style="border:none; border-top:1px solid #D5D8DC; margin: 0;">
            </td>
          </tr>

          <!-- CONTACTO -->
          <tr>
            <td style="background-color:#FFFFFF;
                       padding: 20px 48px;
                       font-size: 13px;
                       color: #5D6D7E;">
              {contacto_html}
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td align="center"
                style="background-color:#F2F3F4;
                       padding: 20px 40px;
                       border-radius: 0 0 12px 12px;
                       font-size: 12px;
                       color: #999999;
                       font-style: italic;">
              Este correo fue enviado automáticamente por AMPARO.
              Por favor no respondas a este mensaje.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    msg = MIMEMultipart('mixed')
    msg['Subject'] = asunto
    msg['From']    = remitente
    msg['To']      = destinatario
    msg.attach(MIMEText(html, 'html'))

    if adjunto_path and os.path.exists(adjunto_path):
        with open(adjunto_path, 'rb') as f:
            adjunto = MIMEApplication(f.read(), _subtype='pdf')
            adjunto.add_header('Content-Disposition', 'attachment',
                               filename=adjunto_nombre or os.path.basename(adjunto_path))
            msg.attach(adjunto)
        print(f"[EMAIL] Adjunto: {adjunto_nombre or os.path.basename(adjunto_path)}")

    brevo_api_key = _cfg_db('brevo_api_key', '')

    if brevo_api_key:
        # ── Envío por API HTTP de Brevo ───────────────────────────────────
        print(f"[AMPARO] Enviando via Brevo API a {destinatario}: {asunto}")
        # Extraer solo el nombre para Brevo (acepta "Nombre" pero no "Nombre <email>")
        import re as _re
        _m = _re.match(r'^(.*?)\s*<[^>]+>\s*$', remitente or '')
        sender_name = _m.group(1).strip() if _m else (remitente or 'AMPARO')
        if not sender_name:
            sender_name = 'AMPARO'
        payload = {
            'sender':      {'name': sender_name, 'email': smtp_user},
            'to':          [{'email': destinatario}],
            'subject':     asunto,
            'htmlContent': html,
        }
        if adjunto_path:
            print(f"[BREVO] adjunto_path={adjunto_path} existe={os.path.exists(adjunto_path)}")
        if adjunto_path and os.path.exists(adjunto_path):
            with open(adjunto_path, 'rb') as _f:
                payload['attachment'] = [{
                    'name':    adjunto_nombre or os.path.basename(adjunto_path),
                    'content': base64.b64encode(_f.read()).decode('utf-8'),
                }]
            print(f"[BREVO] Adjunto agregado: {adjunto_nombre}")
        try:
            resp = requests.post(
                'https://api.brevo.com/v3/smtp/email',
                headers={'api-key': brevo_api_key, 'Content-Type': 'application/json'},
                json=payload,
                timeout=15,
            )
            if not resp.ok:
                print(f"[AMPARO] Error Brevo API {resp.status_code}: {resp.text} — intentando por SMTP...")
            else:
                print(f"[AMPARO] Brevo API OK ({resp.status_code}) para {destinatario}")
                return True
        except Exception as e:
            print(f"[AMPARO] Error Brevo API '{asunto}': {e} — intentando por SMTP...")

    # ── SMTP (principal si no hay Brevo, o fallback si Brevo falló) ───────
    if not smtp_user or not smtp_pass:
        print(f"[AMPARO] SMTP no configurado — email no enviado a {destinatario}")
        return False
    print(f"[AMPARO SMTP] Server: {smtp_host}  Port: {smtp_port}  User: {smtp_user}  TLS: {usar_tls}")
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            if usar_tls:
                server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destinatario, msg.as_string())
        print(f"[AMPARO] Correo enviado a {destinatario}: {asunto}")
        return True
    except Exception as e:
        print(f"[AMPARO] Error al enviar email '{asunto}': {e}")
        return False


def enviar_email_desbloqueo(email, nombre, token):
    base_url = _cfg_db('app_url', os.environ.get('BASE_URL', 'http://127.0.0.1:5000'))
    link     = f"{base_url}/desbloquear/{token}"

    asunto = _cfg_db('mail_desbloqueo_asunto', 'AMPARO — Desbloqueo de cuenta')
    cuerpo = _cfg_db('mail_desbloqueo_cuerpo', (
        'Hola {nombre},\n\n'
        'Tu cuenta fue bloqueada por múltiples intentos de inicio de sesión fallidos.\n\n'
        'Para desbloquearla hacé clic en el siguiente enlace '
        '(válido por {horas} horas):\n'
        '{link_desbloqueo}\n\n'
        'Si no reconocés esta actividad, ignorá este mensaje.'
    ))

    cuerpo = (cuerpo
        .replace('{nombre}', nombre)
        .replace('{link_desbloqueo}', link)
        .replace('{horas}', str(VIGENCIA_TOKEN_HORAS))
    )

    if not (_cfg_db('mail_usuario') or os.environ.get('SMTP_USER')):
        print(f"[AMPARO] Email de desbloqueo para {email} -> {link}")

    return enviar_email(email, asunto, cuerpo)


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Si ya hay sesión y viene por GET, limpiar y mostrar login
    # (permite que /login funcione como "cambiar usuario" en todo momento)
    if 'usuario_id' in session and 'tipo' in session:
        if request.method == 'GET':
            session.clear()
        elif request.form.get('email') and request.form.get('password'):
            # POST con credenciales: limpiar sesión anterior y procesar el login
            session.clear()
        else:
            return redirect(RUTAS_POR_TIPO.get(session['tipo'], '/'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Completá todos los campos.', 'error')
            return render_template('login.html')

        db      = get_db()
        usuario = db.execute('SELECT * FROM usuarios WHERE email = ?', (email,)).fetchone()

        if not usuario:
            flash('Credenciales incorrectas.', 'error')
            return render_template('login.html')

        # --- Verificar estado antes de intentar la contraseña ---
        if usuario['estado'] == 'INACTIVA':
            flash('Tu cuenta está inactiva. Contactá al administrador.', 'error')
            return render_template('login.html')

        if usuario['estado'] == 'BLOQUEADA':
            return redirect(url_for('auth.cuenta_bloqueada'))

        # --- Verificar contraseña ---
        if not check_password_hash(usuario['password_hash'], password):
            nuevos_intentos = usuario['intentos_fallidos'] + 1

            if nuevos_intentos >= INTENTOS_MAX:
                token       = secrets.token_urlsafe(32)
                token_expira = (datetime.now() + timedelta(hours=VIGENCIA_TOKEN_HORAS)).isoformat()
                db.execute(
                    '''UPDATE usuarios
                       SET estado = 'BLOQUEADA', intentos_fallidos = ?,
                           token_desbloqueo = ?, token_expira = ?,
                           fecha_bloqueo = ?
                       WHERE id = ?''',
                    (nuevos_intentos, token, token_expira,
                     datetime.now().isoformat(), usuario['id'])
                )
                db.commit()
                enviar_email_desbloqueo(usuario['email'], usuario['nombre'], token)
                return redirect(url_for('auth.cuenta_bloqueada'))

            restantes = INTENTOS_MAX - nuevos_intentos
            db.execute(
                'UPDATE usuarios SET intentos_fallidos = ? WHERE id = ?',
                (nuevos_intentos, usuario['id'])
            )
            db.commit()
            flash(
                f'Credenciales incorrectas. '
                f'Te queda{"n" if restantes > 1 else ""} {restantes} intento{"s" if restantes > 1 else ""}.',
                'error'
            )
            return render_template('login.html')

        # --- Contraseña correcta: resetear intentos y registrar ingreso ---
        db.execute(
            'UPDATE usuarios SET intentos_fallidos = 0, ultimo_ingreso = ? WHERE id = ?',
            (datetime.now().isoformat(), usuario['id'])
        )
        db.commit()

        # --- Verificar vigencia de la contraseña ---
        if usuario['estado'] == 'VENCIDA' or password_vencida(usuario['fecha_password']):
            db.execute("UPDATE usuarios SET estado = 'VENCIDA' WHERE id = ?", (usuario['id'],))
            db.commit()
            session['usuario_id']      = usuario['id']
            session['cambio_requerido'] = True
            return redirect(url_for('auth.cambiar_password'))

        # --- Login exitoso ---
        session.permanent      = True
        session['usuario_id']  = usuario['id']
        session['tipo']        = usuario['tipo_usuario']
        session['nombre']      = usuario['nombre']
        session['apellido']    = usuario['apellido']
        session['email']       = usuario['email']

        # Verificar cierre diario al ingresar el admin financiero
        if usuario['tipo_usuario'] == 'admin_financiero':
            try:
                from routes.financiero import verificar_cierre_diario
                verificar_cierre_diario()
            except Exception as e:
                print(f'[AMPARO] Error en verificar_cierre_diario: {e}')

        return redirect(RUTAS_POR_TIPO.get(usuario['tipo_usuario'], '/'))

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/cambiar_password', methods=['GET', 'POST'])
def cambiar_password():
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    forzado = session.get('cambio_requerido', False)

    if request.method == 'POST':
        nueva     = request.form.get('nueva_password', '')
        confirmar = request.form.get('confirmar_password', '')

        # Verificar contraseña actual si el cambio NO es forzado
        if not forzado:
            actual = request.form.get('password_actual', '')
            db      = get_db()
            usuario = db.execute('SELECT * FROM usuarios WHERE id = ?', (session['usuario_id'],)).fetchone()
            if not check_password_hash(usuario['password_hash'], actual):
                flash('La contraseña actual es incorrecta.', 'error')
                return render_template('cambiar_password.html', forzado=forzado)

        valida, errores = validar_password(nueva)
        if not valida:
            flash('La contraseña debe tener ' + ', '.join(errores) + '.', 'error')
            return render_template('cambiar_password.html', forzado=forzado)

        if nueva != confirmar:
            flash('Las contraseñas no coinciden.', 'error')
            return render_template('cambiar_password.html', forzado=forzado)

        db      = get_db()
        usuario = db.execute('SELECT * FROM usuarios WHERE id = ?', (session['usuario_id'],)).fetchone()

        if check_password_hash(usuario['password_hash'], nueva):
            flash('La nueva contraseña no puede ser igual a la contraseña actual.', 'error')
            return render_template('cambiar_password.html', forzado=forzado)

        fecha_hoy  = date.today().isoformat()
        fecha_venc = (date.today() + timedelta(days=VIGENCIA_PASSWORD_DIAS)).isoformat()
        db.execute(
            '''UPDATE usuarios
               SET password_hash = ?, fecha_password = ?, fecha_vencimiento = ?, estado = 'ACTIVA'
               WHERE id = ?''',
            (generate_password_hash(nueva), fecha_hoy, fecha_venc, session['usuario_id'])
        )
        db.commit()

        # Si era cambio forzado, completar el login
        if forzado:
            session.pop('cambio_requerido', None)
            usuario = db.execute('SELECT * FROM usuarios WHERE id = ?', (session['usuario_id'],)).fetchone()
            session['tipo']     = usuario['tipo_usuario']
            session['nombre']   = usuario['nombre']
            session['apellido'] = usuario['apellido']
            session['email']    = usuario['email']

        flash('Contraseña actualizada correctamente.', 'success')
        return redirect(RUTAS_POR_TIPO.get(session.get('tipo'), '/'))

    return render_template('cambiar_password.html', forzado=forzado)


@auth_bp.route('/bloqueada')
def cuenta_bloqueada():
    return render_template('bloqueada.html')


@auth_bp.route('/desbloquear/<token>')
def desbloquear(token):
    db      = get_db()
    usuario = db.execute(
        'SELECT * FROM usuarios WHERE token_desbloqueo = ?', (token,)
    ).fetchone()

    if not usuario:
        flash('El enlace de desbloqueo no es válido o ya fue utilizado.', 'error')
        return redirect(url_for('auth.login'))

    if datetime.now() > datetime.fromisoformat(usuario['token_expira']):
        flash('El enlace de desbloqueo expiró. Contactá al administrador.', 'error')
        return redirect(url_for('auth.login'))

    db.execute(
        '''UPDATE usuarios
           SET estado = 'ACTIVA', intentos_fallidos = 0,
               token_desbloqueo = NULL, token_expira = NULL
           WHERE id = ?''',
        (usuario['id'],)
    )
    db.commit()

    flash('Tu cuenta fue desbloqueada exitosamente. Ya podés iniciar sesión.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/admin/desbloquear/<int:usuario_id>')
def admin_desbloquear(usuario_id):
    if 'usuario_id' not in session or session.get('tipo') not in ('admin', 'admin_financiero'):
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('auth.login'))

    db = get_db()
    db.execute(
        '''UPDATE usuarios
           SET estado = 'ACTIVA', intentos_fallidos = 0,
               token_desbloqueo = NULL, token_expira = NULL
           WHERE id = ?''',
        (usuario_id,)
    )
    db.commit()

    flash(f'Cuenta #{usuario_id} desbloqueada correctamente.', 'success')
    return redirect('/admin/dashboard')


# ---------------------------------------------------------------------------
# Helpers de registro
# ---------------------------------------------------------------------------

def _allowed_foto(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTS


def _enviar_bienvenida(email, nombre, tipo):
    if tipo == 'prestador':
        app_nom = 'AMPARO Red'
        default_cuerpo = (
            '¡Bienvenido/a, {nombre}!\n\n'
            'Tu perfil fue enviado para verificación. '
            'El equipo revisará tu documentación y te avisará cuando esté aprobado.'
        )
    else:
        app_nom = 'AMPARO Solicitantes'
        default_cuerpo = (
            '¡Bienvenido/a, {nombre}!\n\n'
            'Tu cuenta está lista. Ya podés buscar prestadores para tu familiar.\n\n'
            '{link_app}'
        )

    if tipo == 'prestador':
        clave_asunto = 'mail_registro_prestador_asunto'
        clave_cuerpo = 'mail_registro_prestador_cuerpo'
    else:
        clave_asunto = 'mail_bienvenida_asunto'
        clave_cuerpo = 'mail_bienvenida_cuerpo'

    app_url  = _cfg_db('app_url', 'http://127.0.0.1:5000')
    link_app = app_url + ('/prestador/login' if tipo == 'prestador' else '/solicitante/login')
    asunto   = _cfg_db(clave_asunto, f'¡Bienvenido/a a {app_nom}!')
    cuerpo   = _cfg_db(clave_cuerpo, default_cuerpo)

    cuerpo = (cuerpo
        .replace('{nombre}', nombre)
        .replace('{app_nom}', app_nom)
        .replace('{link_app}', link_app)
    )

    if not (_cfg_db('mail_usuario') or os.environ.get('SMTP_USER')):
        print(f"[AMPARO] Bienvenida {tipo} para {email}")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    if tipo == 'solicitante':
        ruta_manual   = os.path.join(base_dir, 'static', 'docs', 'manual_solicitante.pdf')
        nombre_manual = 'Manual_AMPARO_Solicitantes.pdf'
    else:
        ruta_manual   = os.path.join(base_dir, 'static', 'docs', 'manual_prestador.pdf')
        nombre_manual = 'Manual_AMPARO_Prestadores.pdf'
    return enviar_email(email, asunto, cuerpo,
                        adjunto_path=ruta_manual,
                        adjunto_nombre=nombre_manual)



def _login_automatico(usuario):
    session.permanent     = True
    session['usuario_id'] = usuario['id']
    session['tipo']       = usuario['tipo_usuario']
    session['nombre']     = usuario['nombre']
    session['apellido']   = usuario['apellido']
    session['email']      = usuario['email']


# ---------------------------------------------------------------------------
# Registro de Prestador
# ---------------------------------------------------------------------------

@auth_bp.route('/registro/prestador', methods=['GET', 'POST'])
def registro_prestador():
    if 'usuario_id' in session and session.get('tipo') != 'admin':
        return redirect(RUTAS_POR_TIPO.get(session.get('tipo'), '/'))

    db         = get_db()
    categorias = db.execute('SELECT id, nombre, tarifa_minima, tarifa_maxima FROM categorias WHERE activa=1 ORDER BY nombre').fetchall()
    zonas      = db.execute('SELECT id, nombre FROM zonas WHERE activa=1 ORDER BY nombre').fetchall()

    if request.method == 'POST':
        # Bloquear envíos que no llegaron al paso 2
        if request.form.get('paso_actual') != '2':
            flash('Completá todos los pasos del formulario antes de enviar.', 'error')
            return render_template('prestador/registro.html',
                                   categorias=categorias, zonas=zonas,
                                   dias=DIAS_SEMANA, franjas=FRANJAS_REG)

        # ── Paso 1: cuenta ──────────────────────────────────────────────────
        nombre     = request.form.get('nombre', '').strip()
        apellido   = request.form.get('apellido', '').strip()
        email      = request.form.get('email', '').strip().lower()
        telefono   = request.form.get('telefono', '').strip() or None
        numero_dni = request.form.get('numero_dni', '').strip()
        password   = request.form.get('password', '')
        confirmar  = request.form.get('confirmar_password', '')

        # ── Paso 2: profesional ─────────────────────────────────────────────
        categoria_id       = request.form.get('categoria_id', '').strip() or None
        zona_id            = request.form.get('zona_id', '').strip() or None
        experiencia        = request.form.get('experiencia_anios', '0').strip()
        try:
            tarifa_hora_reg = float(request.form.get('tarifa_hora_reg', '0').replace(',', '.'))
        except (ValueError, AttributeError):
            tarifa_hora_reg = 0.0
        descripcion        = request.form.get('descripcion', '').strip()
        # GPS / ubicación
        latitud            = request.form.get('latitud', '').strip() or None
        longitud           = request.form.get('longitud', '').strip() or None
        codigo_postal      = request.form.get('codigo_postal', '').strip() or None
        localidad          = request.form.get('localidad', '').strip() or None
        provincia          = request.form.get('provincia', '').strip() or None
        print(f"[GPS REGISTRO] lat={latitud} lon={longitud} cp={codigo_postal} localidad={localidad} provincia={provincia}")
        try:
            radio_cobertura_km = int(request.form.get('radio_cobertura_km', '10'))
        except ValueError:
            radio_cobertura_km = 10

        # Validaciones
        errores = []
        if not nombre:    errores.append('El nombre es obligatorio.')
        if not apellido:  errores.append('El apellido es obligatorio.')
        if not email:     errores.append('El email es obligatorio.')
        if not numero_dni or not re.match(r'^\d{7,8}$', numero_dni):
            errores.append('El número de DNI debe tener 7 u 8 dígitos.')
        if not categoria_id: errores.append('La categoría es obligatoria.')
        if not descripcion: errores.append('La descripción es obligatoria.')

        # Email duplicado
        if email and db.execute('SELECT id FROM usuarios WHERE email=?', (email,)).fetchone():
            errores.append(f'El email {email} ya está registrado. ¿Querés <a href="{url_for("auth.login")}?app=prestador">ingresar</a>?')

        # Contraseña
        valida, perr = validar_password(password)
        if not valida:
            errores.append('La contraseña debe tener: ' + ', '.join(perr) + '.')
        if password != confirmar:
            errores.append('Las contraseñas no coinciden.')

        # Disponibilidad
        disp_seleccionada = []
        for dia in DIAS_SEMANA:
            for fk, _, h_ini, h_fin in FRANJAS_REG:
                if request.form.get(f'disp_{dia}_{fk}'):
                    disp_seleccionada.append((dia, h_ini, h_fin))
        if not disp_seleccionada:
            errores.append('Seleccioná al menos una franja de disponibilidad.')

        try:
            experiencia = int(experiencia)
        except ValueError:
            experiencia = 0

        if errores:
            for e in errores:
                flash(e, 'error')
            return render_template('prestador/registro.html',
                                   categorias=categorias, zonas=zonas,
                                   dias=DIAS_SEMANA, franjas=FRANJAS_REG)

        # ── Crear usuario ────────────────────────────────────────────────────
        hoy       = date.today().isoformat()
        venc      = (date.today() + timedelta(days=VIGENCIA_PASSWORD_DIAS)).isoformat()
        pwd_hash  = generate_password_hash(password)

        cur = db.execute(
            '''INSERT INTO usuarios
               (nombre, apellido, email, password_hash, tipo_usuario,
                estado, fecha_password, fecha_vencimiento, telefono)
               VALUES (?,?,?,?,'prestador','ACTIVA',?,?,?)''',
            (nombre, apellido, email, pwd_hash, hoy, venc, telefono)
        )
        usuario_id = cur.lastrowid

        # ── Foto (opcional) ──────────────────────────────────────────────────
        import time as _time
        foto_url = None
        foto = request.files.get('foto')
        if foto and foto.filename and _allowed_foto(foto.filename):
            foto_url = _subir_imagen_cloudinary(
                foto,
                public_id=f'prestador_{usuario_id}',
                folder='amparo/prestadores',
            )
            if not foto_url:
                # Fallback: guardar localmente
                _upload_dir = UPLOAD_FOLDER_PRESTADORES
                os.makedirs(_upload_dir, exist_ok=True)
                ext      = foto.filename.rsplit('.', 1)[1].lower()
                filename = secure_filename(f'prestador_{usuario_id}.{ext}')
                foto.stream.seek(0)
                foto.save(os.path.join(_upload_dir, filename))
                foto_url = f'/static/uploads/prestadores/{filename}'

        # ── Fotos DNI (opcionales en registro, requeridas para aprobación) ───
        def _guardar_dni_foto(field_name, prefix):
            f = request.files.get(field_name)
            if not f or not f.filename:
                return None
            ext = f.filename.rsplit('.', 1)[-1].lower()
            if ext not in ALLOWED_EXTS:
                return None
            ts = int(_time.time())
            url = _subir_imagen_cloudinary(
                f,
                public_id=f'{prefix}_{usuario_id}_{ts}',
                folder='amparo/dni',
            )
            if url:
                return url
            # Fallback: guardar localmente
            os.makedirs(UPLOAD_FOLDER_DNI, exist_ok=True)
            fname = secure_filename(f'{prefix}_{usuario_id}_{ts}.{ext}')
            f.stream.seek(0)
            f.save(os.path.join(UPLOAD_FOLDER_DNI, fname))
            return f'/static/docs/dni/prestadores/{fname}'

        dni_frente_url = _guardar_dni_foto('dni_foto_frente', 'dni_frente')
        dni_selfie_url = _guardar_dni_foto('dni_foto_selfie', 'dni_selfie')

        # ── Crear prestador ──────────────────────────────────────────────────
        from datetime import datetime as _dt
        ub_dt = _dt.now().isoformat() if (latitud or codigo_postal) else None
        cur2 = db.execute(
            '''INSERT INTO prestadores
               (usuario_id, categoria_id, zona_id, descripcion,
                experiencia_anios, foto_url, numero_dni,
                dni_foto_frente_url, dni_foto_selfie_url,
                latitud, longitud, codigo_postal, localidad, provincia,
                radio_cobertura_km, ubicacion_actualizada, tarifa_hora,
                estado_perfil, dni_verificado, antecedentes_ok, certificados_ok)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'EN_REVISION','PENDIENTE','PENDIENTE','PENDIENTE')''',
            (usuario_id, categoria_id, zona_id,
             descripcion, experiencia, foto_url, numero_dni,
             dni_frente_url, dni_selfie_url,
             latitud, longitud, codigo_postal, localidad, provincia,
             radio_cobertura_km, ub_dt, tarifa_hora_reg)
        )
        prestador_id = cur2.lastrowid

        # ── Disponibilidad ───────────────────────────────────────────────────
        for dia, h_ini, h_fin in disp_seleccionada:
            db.execute(
                'INSERT INTO disponibilidad (prestador_id, dia_semana, hora_inicio, hora_fin) VALUES (?,?,?,?)',
                (prestador_id, dia, h_ini, h_fin)
            )

        # ── Notificar al admin ───────────────────────────────────────────────
        admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
        if admin:
            db.execute(
                'INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje) VALUES (?,?,?,?)',
                (admin['id'], 'nuevo_prestador',
                 'Nuevo prestador registrado',
                 f'Nuevo prestador registrado: {nombre} {apellido}. Perfil pendiente de verificación.')
            )

        db.commit()

        # ── Bienvenida y login automático ────────────────────────────────────
        _enviar_bienvenida(email, nombre, 'prestador')
        if session.get('tipo') != 'admin':
            usuario = db.execute('SELECT * FROM usuarios WHERE id=?', (usuario_id,)).fetchone()
            _login_automatico(usuario)

        return redirect(url_for('auth.registro_prestador_exitoso'))

    return render_template('prestador/registro.html',
                           categorias=categorias, zonas=zonas,
                           dias=DIAS_SEMANA, franjas=FRANJAS_REG)


@auth_bp.route('/registro/prestador/exitoso')
def registro_prestador_exitoso():
    tipo = session.get('tipo')
    if 'usuario_id' not in session or tipo not in ('prestador', 'admin', 'admin_financiero'):
        return redirect(url_for('auth.login'))
    return render_template('prestador/registro_exitoso.html',
                           nombre=session.get('nombre', ''),
                           es_admin=(tipo in ('admin', 'admin_financiero')))


# ---------------------------------------------------------------------------
# Registro de Familia
# ---------------------------------------------------------------------------

@auth_bp.route('/registro/solicitante', methods=['GET', 'POST'])
def registro_solicitante():
    if 'usuario_id' in session and session.get('tipo') != 'admin':
        return redirect(RUTAS_POR_TIPO.get(session.get('tipo'), '/'))

    db    = get_db()
    zonas = db.execute('SELECT id, nombre FROM zonas WHERE activa=1 ORDER BY nombre').fetchall()
    mp_public_key = _cfg_db('mp_public_key', '')
    mp_modo       = _cfg_db('mp_modo', 'produccion')

    if request.method == 'POST':
        # Bloquear envíos que no llegaron al paso 2
        if request.form.get('paso_actual') != '2':
            flash('Completá todos los pasos del formulario antes de enviar.', 'error')
            return render_template('solicitante/registro.html', zonas=zonas, mp_public_key=mp_public_key, mp_modo=mp_modo)

        # ── Paso 1 ───────────────────────────────────────────────────────────
        nombre    = request.form.get('nombre', '').strip()
        apellido  = request.form.get('apellido', '').strip()
        email     = request.form.get('email', '').strip().lower()
        telefono  = request.form.get('telefono', '').strip() or None
        password  = request.form.get('password', '')
        confirmar = request.form.get('confirmar_password', '')
        acepto_cobro = 1 if request.form.get('acepto_cobro_automatico') else 0

        # ── Método de pago ────────────────────────────────────────────────────
        metodo_pago    = request.form.get('metodo_pago', '').strip()
        email_mp       = request.form.get('email_mp', '').strip() or None
        card_token     = request.form.get('card_token', '').strip() or None
        card_last_four = request.form.get('card_last_four', '').strip() or None
        card_type      = request.form.get('card_type', '').strip() or None

        # ── Paso 2 ───────────────────────────────────────────────────────────
        zona_id         = request.form.get('zona_id', '').strip() or None
        direccion       = request.form.get('direccion', '').strip() or None
        fam_nombre      = request.form.get('familiar_nombre', '').strip() or None
        fam_edad        = request.form.get('familiar_edad', '').strip() or None
        fam_condicion   = request.form.get('familiar_condicion', '').strip() or None
        fam_necesidades = request.form.get('familiar_necesidades', '').strip() or None
        # GPS / ubicación
        f_latitud       = request.form.get('latitud', '').strip() or None
        f_longitud      = request.form.get('longitud', '').strip() or None
        f_cp            = request.form.get('codigo_postal', '').strip() or None
        f_localidad     = request.form.get('localidad', '').strip() or None
        f_provincia     = request.form.get('provincia', '').strip() or None

        # Validaciones
        errores = []
        if not nombre:   errores.append('El nombre es obligatorio.')
        if not apellido: errores.append('El apellido es obligatorio.')
        if not email:    errores.append('El email es obligatorio.')

        if email and db.execute('SELECT id FROM usuarios WHERE email=?', (email,)).fetchone():
            errores.append(f'El email {email} ya está registrado. ¿Querés <a href="{url_for("auth.login")}?app=solicitante">ingresar</a>?')

        valida, perr = validar_password(password)
        if not valida:
            errores.append('La contraseña debe tener: ' + ', '.join(perr) + '.')
        if password != confirmar:
            errores.append('Las contraseñas no coinciden.')

        if not acepto_cobro:
            errores.append('Debés aceptar el cobro automático para registrarte.')

        if metodo_pago not in ('mercadopago', 'tarjeta'):
            errores.append('Seleccioná un método de pago válido.')
        elif metodo_pago == 'mercadopago' and not email_mp:
            errores.append('Ingresá el email de tu cuenta de Mercado Pago.')
        elif metodo_pago == 'tarjeta' and not card_token:
            errores.append('Los datos de tarjeta no pudieron verificarse. Intentá de nuevo.')

        if errores:
            for e in errores:
                flash(e, 'error')
            return render_template('solicitante/registro.html', zonas=zonas, mp_public_key=mp_public_key, mp_modo=mp_modo)

        # ── Crear usuario ────────────────────────────────────────────────────
        hoy      = date.today().isoformat()
        venc     = (date.today() + timedelta(days=VIGENCIA_PASSWORD_DIAS)).isoformat()
        pwd_hash = generate_password_hash(password)
        ahora    = datetime.now().isoformat()

        cur = db.execute(
            '''INSERT INTO usuarios
               (nombre, apellido, email, password_hash, tipo_usuario,
                estado, fecha_password, fecha_vencimiento, telefono,
                acepto_cobro_automatico, fecha_aceptacion_cobro)
               VALUES (?,?,?,?,'solicitante','ACTIVA',?,?,?,?,?)''',
            (nombre, apellido, email, pwd_hash, hoy, venc, telefono,
             acepto_cobro, ahora if acepto_cobro else None)
        )
        usuario_id = cur.lastrowid

        # ── Crear familia ────────────────────────────────────────────────────
        from datetime import datetime as _dt
        ub_dt_f = _dt.now().isoformat() if (f_latitud or f_cp) else None

        # Construir descripción del método de pago
        if metodo_pago == 'tarjeta' and card_last_four and card_type:
            metodo_pago_desc = f'{card_type.upper()} terminada en {card_last_four}'
        elif metodo_pago == 'mercadopago' and email_mp:
            metodo_pago_desc = f'Mercado Pago — {email_mp}'
        else:
            metodo_pago_desc = None

        db.execute(
            '''INSERT INTO solicitantes
               (usuario_id, zona_id, direccion,
                familiar_nombre, familiar_edad,
                familiar_condicion, familiar_necesidades,
                latitud, longitud, codigo_postal, localidad, provincia,
                ubicacion_actualizada,
                metodo_pago, metodo_pago_descripcion, mp_card_token)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (usuario_id, zona_id, direccion,
             fam_nombre, fam_edad, fam_condicion, fam_necesidades,
             f_latitud, f_longitud, f_cp, f_localidad, f_provincia, ub_dt_f,
             metodo_pago, metodo_pago_desc,
             card_token if metodo_pago == 'tarjeta' else None)
        )

        # ── Notificar al admin ───────────────────────────────────────────────
        admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
        if admin:
            db.execute(
                'INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje) VALUES (?,?,?,?)',
                (admin['id'], 'nuevo_solicitante',
                 'Nuevo solicitante registrado',
                 f'Nuevo solicitante registrado: {nombre} {apellido}.')
            )

        db.commit()

        _enviar_bienvenida(email, nombre, 'solicitante')
        if session.get('tipo') != 'admin':
            usuario = db.execute('SELECT * FROM usuarios WHERE id=?', (usuario_id,)).fetchone()
            _login_automatico(usuario)

        return redirect(url_for('auth.registro_solicitante_exitoso'))

    return render_template('solicitante/registro.html', zonas=zonas, mp_public_key=mp_public_key, mp_modo=mp_modo)


@auth_bp.route('/registro/solicitante/exitoso')
def registro_solicitante_exitoso():
    tipo = session.get('tipo')
    if 'usuario_id' not in session or tipo not in ('solicitante', 'admin', 'admin_financiero'):
        return redirect(url_for('auth.login'))
    return render_template('solicitante/registro_exitoso.html',
                           nombre=session.get('nombre', ''),
                           es_admin=(tipo in ('admin', 'admin_financiero')))
