import os
from datetime import date, datetime, timedelta

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.utils import secure_filename

from database import get_db, ahora_argentina


def _comprimir_imagen(ruta, max_px=1200, calidad=78):
    """Redimensiona y comprime una imagen JPG/PNG al guardarla."""
    try:
        from PIL import Image, ExifTags
        img = Image.open(ruta)
        # Corregir orientación EXIF (fotos de celular suelen estar rotadas)
        try:
            for tag, val in img._getexif().items():
                if ExifTags.TAGS.get(tag) == 'Orientation':
                    if val == 3:   img = img.rotate(180, expand=True)
                    elif val == 6: img = img.rotate(270, expand=True)
                    elif val == 8: img = img.rotate(90,  expand=True)
                    break
        except Exception:
            pass
        # Redimensionar si supera max_px
        w, h = img.size
        if max(w, h) > max_px:
            ratio = max_px / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        # Convertir a RGB para guardar como JPEG
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.save(ruta, 'JPEG', quality=calidad, optimize=True)
    except Exception:
        pass  # Si falla, deja la imagen original intacta

prestador_bp = Blueprint('prestador', __name__, url_prefix='/prestador')


@prestador_bp.route('/login')
def login_prestador():
    if 'usuario_id' in session and session.get('tipo') == 'prestador':
        return redirect(url_for('prestador.dashboard'))
    return render_template('login_prestador.html')


def _calcular_horas(hora_inicio, hora_fin):
    """Calcula horas exactas entre dos horarios HH:MM (acepta también HH:MM:SS)."""
    hi = datetime.strptime(hora_inicio[:5], '%H:%M')
    hf = datetime.strptime(hora_fin[:5], '%H:%M')
    diferencia = hf - hi
    return diferencia.seconds / 3600

_BASE_DIR          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_FOLDER      = os.path.join(_BASE_DIR, 'static', 'uploads', 'prestadores')
ALLOWED_EXTS       = {'jpg', 'jpeg', 'png', 'webp'}
UPLOAD_FOLDER_DOCS = os.path.join(_BASE_DIR, 'static', 'docs', 'prestadores')
UPLOAD_FOLDER_CV   = os.path.join(_BASE_DIR, 'static', 'docs', 'cv')
UPLOAD_FOLDER_DNI  = os.path.join(_BASE_DIR, 'static', 'docs', 'dni')
ALLOWED_DOCS       = {'pdf', 'jpg', 'jpeg', 'png'}

DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
FRANJAS = [
    ('manana', 'Mañana',  '08:00', '12:00'),
    ('tarde',  'Tarde',   '12:00', '18:00'),
    ('noche',  'Noche',   '18:00', '22:00'),
]


# ─── Guards ──────────────────────────────────────────────────────────────────

@prestador_bp.before_request
def verificar_prestador():
    if request.endpoint == 'prestador.login_prestador':
        return  # Login PWA: sin autenticacion requerida
    if 'usuario_id' not in session:
        return redirect(url_for('prestador.login_prestador'))
    if session.get('tipo') != 'prestador':
        session.clear()
        return redirect(url_for('prestador.login_prestador'))
    db = get_db()
    u = db.execute("SELECT estado FROM usuarios WHERE id=?", (session['usuario_id'],)).fetchone()
    if u and u['estado'] == 'VENCIDA':
        session['cambio_requerido'] = True
        return redirect(url_for('auth.cambiar_password'))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ctx():
    db = get_db()
    notif_count = db.execute(
        'SELECT COUNT(*) as c FROM notificaciones WHERE usuario_id=? AND leida=0',
        (session['usuario_id'],)
    ).fetchone()['c']
    return {
        'nombre':       session.get('nombre', ''),
        'apellido':     session.get('apellido', ''),
        'notif_count':  notif_count,
    }


def _get_prestador_id(db):
    row = db.execute(
        'SELECT id FROM prestadores WHERE usuario_id=?', (session['usuario_id'],)
    ).fetchone()
    return row['id'] if row else None


def _get_config(db, clave, default=None):
    row = db.execute('SELECT valor FROM configuracion WHERE clave=?', (clave,)).fetchone()
    return row['valor'] if row else default


def _verificar_antecedentes_prestador(db, prestador_id):
    """Retorna 'vencido', 'ok' o 'sin_verificar'."""
    pr = db.execute(
        'SELECT antecedentes_ok, antecedentes_fecha_vencimiento, antecedentes_alerta_enviada '
        'FROM prestadores WHERE id=?',
        (prestador_id,)
    ).fetchone()
    if not pr or pr['antecedentes_ok'] != 'VERIFICADO':
        return 'sin_verificar'
    if not pr['antecedentes_fecha_vencimiento']:
        return 'ok'  # certificado viejo sin fecha, dejar pasar
    fecha_venc = date.fromisoformat(pr['antecedentes_fecha_vencimiento'])
    hoy        = date.today()
    if fecha_venc < hoy:
        return 'vencido'
    dias_alerta = int(_get_config(db, 'antecedentes_alerta_dias', 30))
    if fecha_venc <= hoy + timedelta(days=dias_alerta):
        if not pr['antecedentes_alerta_enviada']:
            _enviar_alerta_antecedentes(db, prestador_id, fecha_venc)
    return 'ok'


def _enviar_alerta_antecedentes(db, prestador_id, fecha_venc):
    pr = db.execute(
        '''SELECT p.usuario_id, u.nombre, u.apellido
           FROM prestadores p JOIN usuarios u ON p.usuario_id=u.id
           WHERE p.id=?''',
        (prestador_id,)
    ).fetchone()
    if not pr:
        return
    dias_restantes = (fecha_venc - date.today()).days
    fecha_str      = fecha_venc.strftime('%d/%m/%Y')
    _notificar(db, pr['usuario_id'], 'antecedentes_por_vencer',
               'Tu certificado de antecedentes vence pronto',
               f'Tu certificado de antecedentes penales vence el {fecha_str} '
               f'(en {dias_restantes} días). Solicitá la renovación en '
               f'argentina.gob.ar/justicia/reincidencia/antecedentespenales '
               f'y envialo a amparo.aplicacion@gmail.com')
    admins = db.execute(
        "SELECT id FROM usuarios WHERE tipo_usuario IN ('admin', 'admin_financiero')"
    ).fetchall()
    for admin in admins:
        _notificar(db, admin['id'], 'antecedentes_por_vencer',
                   f"Certificado por vencer — {pr['nombre']} {pr['apellido']}",
                   f"El certificado de antecedentes de {pr['nombre']} {pr['apellido']} "
                   f"vence el {fecha_str}. Recordale que lo renueve.")
    db.execute(
        'UPDATE prestadores SET antecedentes_alerta_enviada=1 WHERE id=?',
        (prestador_id,)
    )


def _notificar(db, usuario_id, tipo, titulo, mensaje=None):
    db.execute(
        'INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje) VALUES (?,?,?,?)',
        (usuario_id, tipo, titulo, mensaje)
    )


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTS


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@prestador_bp.route('/dashboard')
def dashboard():
    db  = get_db()
    pid = _get_prestador_id(db)
    if not pid:
        flash('Tu perfil de prestador no fue encontrado.', 'error')
        return redirect(url_for('auth.logout'))

    hoy = date.today().isoformat()

    # Indicadores
    pendientes_count = db.execute(
        "SELECT COUNT(*) as c FROM servicios WHERE prestador_id=? AND estado='PENDIENTE'", (pid,)
    ).fetchone()['c']

    proximo = db.execute(
        """SELECT s.*, u.nombre || ' ' || u.apellido AS solicitante_nombre, f.direccion
           FROM servicios s
           JOIN solicitantes fam ON fam.id = s.solicitante_id
           JOIN usuarios u ON u.id = fam.usuario_id
           LEFT JOIN solicitantes f ON f.id = s.solicitante_id
           WHERE s.prestador_id=? AND s.estado IN ('ACEPTADO','ACTIVO')
             AND s.fecha_servicio >= ?
           ORDER BY s.fecha_servicio, s.hora_inicio LIMIT 1""",
        (pid, hoy)
    ).fetchone()

    cobros_pendientes = db.execute(
        "SELECT COALESCE(SUM(monto_neto),0) as s FROM pagos WHERE prestador_id=? AND estado='PROCESADO'",
        (pid,)
    ).fetchone()['s']

    puntaje_row = db.execute(
        "SELECT AVG(puntaje) as avg, COUNT(*) as cnt FROM calificaciones WHERE prestador_id=?", (pid,)
    ).fetchone()
    puntaje = round(puntaje_row['avg'] or 0, 1)
    resenas  = puntaje_row['cnt']

    # Solicitudes nuevas (últimas 3)
    solicitudes = db.execute(
        """SELECT s.*, u.nombre || ' ' || u.apellido AS solicitante_nombre,
                  c.nombre AS categoria_nombre
           FROM servicios s
           JOIN solicitantes fam ON fam.id = s.solicitante_id
           JOIN usuarios u ON u.id = fam.usuario_id
           LEFT JOIN categorias c ON c.id = s.categoria_id
           WHERE s.prestador_id=? AND s.estado='PENDIENTE'
           ORDER BY s.fecha_solicitud DESC LIMIT 3""",
        (pid,)
    ).fetchall()

    total_pendientes = pendientes_count

    # Próximos servicios (los 3 siguientes)
    proximos = db.execute(
        """SELECT s.*, u.nombre || ' ' || u.apellido AS solicitante_nombre,
                  f.direccion
           FROM servicios s
           JOIN solicitantes fam ON fam.id = s.solicitante_id
           JOIN usuarios u ON u.id = fam.usuario_id
           LEFT JOIN solicitantes f ON f.id = s.solicitante_id
           WHERE s.prestador_id=? AND s.estado IN ('ACEPTADO','ACTIVO')
             AND s.fecha_servicio >= ?
           ORDER BY s.fecha_servicio, s.hora_inicio LIMIT 3""",
        (pid, hoy)
    ).fetchall()

    # Servicios de hoy que requieren confirmación de llegada o fin
    servicios_hoy = db.execute(
        """SELECT s.*, u.nombre || ' ' || u.apellido AS solicitante_nombre,
                  f.direccion
           FROM servicios s
           JOIN solicitantes fam ON fam.id = s.solicitante_id
           JOIN usuarios u ON u.id = fam.usuario_id
           LEFT JOIN solicitantes f ON f.id = s.solicitante_id
           WHERE s.prestador_id=? AND s.fecha_servicio=?
             AND s.estado IN ('ACEPTADO','ACTIVO')""",
        (pid, hoy)
    ).fetchall()

    return render_template('prestador/dashboard.html',
                           hoy=hoy,
                           pendientes_count=pendientes_count,
                           proximo=proximo,
                           cobros_pendientes=round(cobros_pendientes, 2),
                           puntaje=puntaje, resenas=resenas,
                           solicitudes=solicitudes,
                           total_pendientes=total_pendientes,
                           proximos=proximos,
                           servicios_hoy=servicios_hoy,
                           **_ctx())


# ─── SERVICIOS ────────────────────────────────────────────────────────────────

@prestador_bp.route('/servicios')
def servicios():
    db   = get_db()
    pid  = _get_prestador_id(db)
    tab  = request.args.get('tab', 'pendientes')
    page = max(1, int(request.args.get('page', 1)))
    PER_PAGE = 10

    if tab == 'pendientes':
        rows = db.execute(
            """SELECT s.*, u.nombre || ' ' || u.apellido AS solicitante_nombre,
                      c.nombre AS categoria_nombre, f.direccion
               FROM servicios s
               JOIN solicitantes fam ON fam.id = s.solicitante_id
               JOIN usuarios u ON u.id = fam.usuario_id
               LEFT JOIN categorias c ON c.id = s.categoria_id
               LEFT JOIN solicitantes f ON f.id = s.solicitante_id
               WHERE s.prestador_id=? AND s.estado='PENDIENTE'
               ORDER BY s.fecha_solicitud DESC""",
            (pid,)
        ).fetchall()
        total_pages = 1
    elif tab == 'activos':
        rows = db.execute(
            """SELECT s.*, u.nombre || ' ' || u.apellido AS solicitante_nombre,
                      u.telefono AS solicitante_telefono, f.direccion
               FROM servicios s
               JOIN solicitantes fam ON fam.id = s.solicitante_id
               JOIN usuarios u ON u.id = fam.usuario_id
               LEFT JOIN solicitantes f ON f.id = s.solicitante_id
               WHERE s.prestador_id=? AND s.estado IN ('ACEPTADO','ACTIVO')
               ORDER BY s.fecha_servicio, s.hora_inicio""",
            (pid,)
        ).fetchall()
        total_pages = 1
    else:  # historial
        total = db.execute(
            """SELECT COUNT(*) as c FROM servicios
               WHERE prestador_id=? AND estado IN ('FINALIZADO','CANCELADO','RECHAZADO')""",
            (pid,)
        ).fetchone()['c']
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        offset = (page - 1) * PER_PAGE
        rows = db.execute(
            """SELECT s.*, u.nombre || ' ' || u.apellido AS solicitante_nombre,
                      cal.puntaje
               FROM servicios s
               JOIN solicitantes fam ON fam.id = s.solicitante_id
               JOIN usuarios u ON u.id = fam.usuario_id
               LEFT JOIN calificaciones cal ON cal.servicio_id = s.id
               WHERE s.prestador_id=? AND s.estado IN ('FINALIZADO','CANCELADO','RECHAZADO')
               ORDER BY s.fecha_servicio DESC LIMIT ? OFFSET ?""",
            (pid, PER_PAGE, offset)
        ).fetchall()

    return render_template('prestador/servicios.html',
                           tab=tab, rows=rows,
                           page=page, total_pages=total_pages,
                           **_ctx())


@prestador_bp.route('/servicios/<int:sid>')
def servicio_detalle(sid):
    db  = get_db()
    pid = _get_prestador_id(db)

    s = db.execute(
        """SELECT s.*,
                  u.nombre || ' ' || u.apellido AS solicitante_nombre,
                  u.telefono AS solicitante_telefono, u.email AS solicitante_email,
                  f.direccion, f.familiar_nombre, f.familiar_edad,
                  f.familiar_condicion, f.familiar_necesidades,
                  c.nombre AS categoria_nombre
           FROM servicios s
           JOIN solicitantes fam ON fam.id = s.solicitante_id
           JOIN usuarios u ON u.id = fam.usuario_id
           LEFT JOIN solicitantes f ON f.id = s.solicitante_id
           LEFT JOIN categorias c ON c.id = s.categoria_id
           WHERE s.id=? AND s.prestador_id=?""",
        (sid, pid)
    ).fetchone()
    if not s:
        abort(404)

    pago = db.execute('SELECT * FROM pagos WHERE servicio_id=?', (sid,)).fetchone()
    cal  = db.execute('SELECT * FROM calificaciones WHERE servicio_id=?', (sid,)).fetchone()

    return render_template('prestador/servicio_detalle.html',
                           s=s, pago=pago, cal=cal, **_ctx())


@prestador_bp.route('/servicios/<int:sid>/aceptar', methods=['POST'])
def servicio_aceptar(sid):
    db  = get_db()
    pid = _get_prestador_id(db)
    s   = db.execute(
        "SELECT * FROM servicios WHERE id=? AND prestador_id=? AND estado='PENDIENTE'",
        (sid, pid)
    ).fetchone()
    if not s:
        flash('No se puede aceptar este servicio.', 'error')
        return redirect(url_for('prestador.servicios'))

    # Verificar antecedentes antes de aceptar
    estado_ant = _verificar_antecedentes_prestador(db, pid)
    if estado_ant == 'vencido':
        pr_data = db.execute(
            '''SELECT p.antecedentes_fecha_vencimiento, u.nombre, u.apellido
               FROM prestadores p JOIN usuarios u ON p.usuario_id=u.id
               WHERE p.id=?''', (pid,)
        ).fetchone()
        fecha_venc_str = ''
        if pr_data and pr_data['antecedentes_fecha_vencimiento']:
            fecha_venc_str = date.fromisoformat(
                pr_data['antecedentes_fecha_vencimiento']
            ).strftime('%d/%m/%Y')

        # Notificar al solicitante (mensaje genérico)
        fam = db.execute(
            "SELECT usuario_id FROM solicitantes WHERE id=?", (s['solicitante_id'],)
        ).fetchone()
        if fam:
            _notificar(db, fam['usuario_id'], 'servicio_bloqueado',
                       'No se pudo confirmar el servicio',
                       'No podemos confirmar este servicio en este momento. '
                       'Por favor intentá con otro prestador.')

        # Notificar al admin
        admins = db.execute(
            "SELECT id FROM usuarios WHERE tipo_usuario IN ('admin', 'admin_financiero')"
        ).fetchall()
        for admin in admins:
            nombre_pr = f"{pr_data['nombre']} {pr_data['apellido']}" if pr_data else f'Prestador #{pid}'
            _notificar(db, admin['id'], 'antecedentes_vencidos',
                       f'Servicio bloqueado: antecedentes vencidos — {nombre_pr}',
                       f'El certificado de antecedentes de {nombre_pr} está vencido '
                       f'desde {fecha_venc_str}. El prestador necesita renovarlo para '
                       f'seguir trabajando.')

        # Notificar al prestador
        pr_uid = db.execute('SELECT usuario_id FROM prestadores WHERE id=?', (pid,)).fetchone()
        if pr_uid:
            _notificar(db, pr_uid['usuario_id'], 'antecedentes_vencidos',
                       'Tu certificado de antecedentes está vencido',
                       f'Tu certificado de antecedentes penales venció el {fecha_venc_str}. '
                       f'Para seguir recibiendo solicitudes necesitás renovarlo y enviarlo a '
                       f'amparo.aplicacion@gmail.com')

        db.commit()
        flash('No podés aceptar este servicio porque tu certificado de antecedentes penales '
              'está vencido. Para renovarlo envialo a amparo.aplicacion@gmail.com', 'error')
        return redirect(url_for('prestador.servicios', tab='pendientes'))

    db.execute(
        "UPDATE servicios SET estado='ACEPTADO', fecha_aceptacion=? WHERE id=?",
        (ahora_argentina(), sid)
    )
    # Notificar al solicitante
    fam = db.execute(
        "SELECT usuario_id FROM solicitantes WHERE id=?", (s['solicitante_id'],)
    ).fetchone()
    if fam:
        _notificar(db, fam['usuario_id'], 'servicio_aceptado',
                   'Solicitud aceptada',
                   f'Tu solicitud para el {s["fecha_servicio"]} fue aceptada por el prestador.')
    db.commit()
    flash('Servicio aceptado correctamente.', 'success')
    return redirect(url_for('prestador.servicios', tab='activos'))


@prestador_bp.route('/servicios/<int:sid>/rechazar', methods=['POST'])
def servicio_rechazar(sid):
    db     = get_db()
    pid    = _get_prestador_id(db)
    motivo = request.form.get('motivo', '').strip()
    s      = db.execute(
        "SELECT * FROM servicios WHERE id=? AND prestador_id=? AND estado='PENDIENTE'",
        (sid, pid)
    ).fetchone()
    if not s:
        flash('No se puede rechazar este servicio.', 'error')
        return redirect(url_for('prestador.servicios'))

    db.execute(
        "UPDATE servicios SET estado='RECHAZADO', motivo_rechazo=? WHERE id=?",
        (motivo or None, sid)
    )
    fam = db.execute("SELECT usuario_id FROM solicitantes WHERE id=?", (s['solicitante_id'],)).fetchone()
    if fam:
        _notificar(db, fam['usuario_id'], 'servicio_rechazado',
                   'Solicitud rechazada',
                   f'Tu solicitud para el {s["fecha_servicio"]} fue rechazada.'
                   + (f' Motivo: {motivo}' if motivo else ''))
    db.commit()
    flash('Servicio rechazado.', 'success')
    return redirect(url_for('prestador.servicios', tab='pendientes'))


def _enviar_correos_liquidacion(db, pago_id):
    """Envía correos al solicitante (recibo) y al prestador (aviso de pago) tras procesar el cobro."""
    try:
        from auth import enviar_email, _cfg_db
        pago = db.execute('SELECT * FROM pagos WHERE id=?', (pago_id,)).fetchone()
        if not pago:
            print(f"[CORREO] Pago {pago_id} no encontrado")
            return
        servicio = db.execute('SELECT * FROM servicios WHERE id=?', (pago['servicio_id'],)).fetchone()
        sol = db.execute(
            'SELECT u.email, u.nombre FROM solicitantes s JOIN usuarios u ON s.usuario_id=u.id WHERE s.id=?',
            (pago['solicitante_id'],)
        ).fetchone()
        pre = db.execute(
            'SELECT u.email, u.nombre, p.metodo_cobro FROM prestadores p JOIN usuarios u ON p.usuario_id=u.id WHERE p.id=?',
            (pago['prestador_id'],)
        ).fetchone()

        fecha_srv = str(servicio['fecha_servicio'] if servicio else '')

        if sol:
            total = float(pago['monto_bruto'] or 0) + float(pago['comision_monto'] or 0)
            prestador_nombre = pre['nombre'] if pre else ''
            asunto = (_cfg_db('mail_recibo_pago_asunto', 'Recibo de pago — AMPARO')
                      .replace('{fecha_servicio}', fecha_srv))
            texto  = _cfg_db('mail_recibo_pago_cuerpo',
                'Hola {nombre},\n\nTe confirmamos el pago del siguiente servicio:\n\n'
                'Prestador: {prestador_nombre}\nFecha: {fecha_servicio}\n'
                'Horario: {hora_inicio} a {hora_fin}\n\n'
                'Subtotal servicio: $ {monto_servicio}\n'
                'Servicio de AMPARO: $ {comision}\n'
                'Total pagado: $ {total_pagado}')
            texto = (texto
                .replace('{nombre}',          sol['nombre'] or '')
                .replace('{prestador_nombre}', prestador_nombre)
                .replace('{fecha_servicio}',  fecha_srv)
                .replace('{hora_inicio}',     str(servicio['hora_inicio']    if servicio else ''))
                .replace('{hora_fin}',        str(servicio['hora_fin']       if servicio else ''))
                .replace('{monto_servicio}',  f"{pago['monto_bruto']:,.0f}")
                .replace('{comision}',        f"{pago['comision_monto']:,.0f}")
                .replace('{total_pagado}',    f"{total:,.0f}")
            )
            r1 = enviar_email(sol['email'], asunto, texto)
            print(f"[CORREO] Solicitante {sol['email']}: {'OK' if r1 is not False else 'ERROR/SMTP no configurado'}")

        if pre:
            fecha_liq = str(pago['fecha_liquidacion'] or pago['fecha_pago'] or '')[:10]
            asunto2 = _cfg_db('mail_pago_liquidado_asunto', 'Tu cobro fue procesado — AMPARO')
            texto2  = _cfg_db('mail_pago_liquidado_cuerpo',
                'Hola {nombre},\n\nEl cobro del servicio fue procesado correctamente.\n\n'
                'Monto a acreditar: $ {monto_neto}\n'
                'Método de cobro: {metodo_cobro}\n'
                'Fecha: {fecha_liquidacion}\n\n'
                'Podés ver el detalle en la app:\n{link_app}')
            texto2 = (texto2
                .replace('{nombre}',           pre['nombre'] or '')
                .replace('{monto_neto}',        f"{pago['monto_neto']:,.0f}")
                .replace('{metodo_cobro}',      pre['metodo_cobro'] or 'Mercado Pago')
                .replace('{fecha_liquidacion}', fecha_liq)
                .replace('{link_app}',          _cfg_db('app_url', 'http://127.0.0.1:5000') + '/prestador/dashboard')
            )
            r2 = enviar_email(pre['email'], asunto2, texto2)
            print(f"[CORREO] Prestador {pre['email']}: {'OK' if r2 is not False else 'ERROR/SMTP no configurado'}")

    except Exception as e:
        import traceback
        print(f"[ERROR] _enviar_correos_liquidacion: {e}")
        traceback.print_exc()


@prestador_bp.route('/servicios/<int:sid>/finalizar', methods=['POST'])
def servicio_finalizar(sid):
    db  = get_db()
    pid = _get_prestador_id(db)

    s = db.execute(
        """SELECT * FROM servicios
           WHERE id=? AND prestador_id=? AND estado IN ('ACEPTADO','ACTIVO')
             AND prestador_confirmo_fin=0""",
        (sid, pid)
    ).fetchone()
    if not s:
        flash('No se puede finalizar este servicio.', 'error')
        return redirect(url_for('prestador.servicios'))

    ahora = ahora_argentina()
    db.execute(
        """UPDATE servicios SET prestador_confirmo_fin=1, fecha_confirmacion_prestador=?
           WHERE id=?""",
        (ahora, sid)
    )

    # Notificar al solicitante para que confirme
    fam = db.execute("SELECT usuario_id FROM solicitantes WHERE id=?", (s['solicitante_id'],)).fetchone()
    if fam:
        _notificar(db, fam['usuario_id'], 'servicio_finalizado',
                   'El prestador confirmó el fin del servicio',
                   f'El prestador confirmó que terminó el servicio del {s["fecha_servicio"]}. '
                   f'Ingresá a la app para confirmarlo y cerrar el cobro.')

    db.commit()
    flash('Confirmaste que el servicio finalizó. El solicitante debe confirmarlo también para cerrar el cobro.', 'success')
    return redirect(url_for('prestador.servicio_detalle', sid=sid))


@prestador_bp.route('/servicios/<int:sid>/cancelar', methods=['POST'])
def servicio_cancelar(sid):
    db     = get_db()
    pid    = _get_prestador_id(db)
    motivo = request.form.get('motivo', '').strip()
    if not motivo:
        flash('El motivo de cancelación es obligatorio.', 'error')
        return redirect(url_for('prestador.servicio_detalle', sid=sid))

    s = db.execute(
        "SELECT * FROM servicios WHERE id=? AND prestador_id=? AND estado IN ('ACEPTADO','ACTIVO')",
        (sid, pid)
    ).fetchone()
    if not s:
        flash('No se puede cancelar este servicio.', 'error')
        return redirect(url_for('prestador.servicios'))

    db.execute(
        "UPDATE servicios SET estado='CANCELADO', motivo_cancelacion=? WHERE id=?",
        (motivo, sid)
    )
    fam = db.execute("SELECT usuario_id FROM solicitantes WHERE id=?", (s['solicitante_id'],)).fetchone()
    if fam:
        _notificar(db, fam['usuario_id'], 'servicio_cancelado',
                   'Servicio cancelado',
                   f'El servicio del {s["fecha_servicio"]} fue cancelado por el prestador. Motivo: {motivo}')
    db.commit()
    flash('Servicio cancelado.', 'success')
    return redirect(url_for('prestador.servicios', tab='activos'))


# ─── CONFIRMACIÓN GPS ─────────────────────────────────────────────────────────

@prestador_bp.route('/servicios/<int:sid>/confirmar-llegada', methods=['POST'])
def servicio_confirmar_llegada(sid):
    import math, traceback
    from flask import jsonify
    try:
        db  = get_db()
        pid = _get_prestador_id(db)

        if not pid:
            return jsonify({'ok': False, 'error': 'Perfil de prestador no encontrado.'}), 400

        s = db.execute(
            "SELECT s.*, fam.latitud AS fam_lat, fam.longitud AS fam_lon "
            "FROM servicios s JOIN solicitantes fam ON fam.id = s.solicitante_id "
            "WHERE s.id=? AND s.prestador_id=? AND s.estado='ACEPTADO'",
            (sid, pid)
        ).fetchone()
        if not s:
            # Check if already confirmed (ACTIVO) to give a better error
            ya = db.execute(
                "SELECT estado FROM servicios WHERE id=? AND prestador_id=?",
                (sid, pid)
            ).fetchone()
            if ya and ya['estado'] == 'ACTIVO':
                return jsonify({'ok': False, 'error': 'La llegada ya fue confirmada para este servicio.'}), 400
            return jsonify({'ok': False, 'error': 'Servicio no disponible.'}), 400

        data = request.get_json(silent=True) or {}
        try:
            lat = float(data['lat'])
            lon = float(data['lon'])
        except (KeyError, TypeError, ValueError):
            print(f"[confirmar_llegada] sid={sid} — coordenadas inválidas: {data}")
            return jsonify({'ok': False, 'error': 'Coordenadas inválidas.'}), 400

        cfg = {r['clave']: r['valor'] for r in db.execute(
            "SELECT clave, valor FROM configuracion WHERE clave='geofence_radio_metros'"
        ).fetchall()}
        radio = float(cfg.get('geofence_radio_metros', 50))

        fam_lat = s['fam_lat']
        fam_lon = s['fam_lon']

        if fam_lat and fam_lon:
            # Haversine
            R = 6371000
            phi1, phi2 = math.radians(lat), math.radians(float(fam_lat))
            dphi    = math.radians(float(fam_lat) - lat)
            dlambda = math.radians(float(fam_lon) - lon)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
            distancia = 2 * R * math.asin(math.sqrt(a))
        else:
            # Sin coords de familia: aceptar igual (no podemos verificar)
            distancia = 0

        print(f"[confirmar_llegada] servicio={sid}, prestador_lat={lat}, prestador_lon={lon}, "
              f"solicitante_lat={fam_lat}, solicitante_lon={fam_lon}, distancia={round(distancia)}m, radio={radio}m")

        if distancia > radio and fam_lat and fam_lon:
            print(f"[confirmar_llegada] RECHAZADO — demasiado lejos ({round(distancia)}m > {radio}m)")
            return jsonify({
                'ok': False,
                'demasiado_lejos': True,
                'distancia': round(distancia),
                'radio': int(radio),
            })

        db.execute(
            """UPDATE servicios
               SET estado='ACTIVO', prestador_confirmo_llegada=1,
                   prestador_lat_llegada=?, prestador_lon_llegada=?,
                   fecha_llegada=?, distancia_llegada_metros=?
               WHERE id=?""",
            (lat, lon, ahora_argentina(), round(distancia), sid)
        )
        # Notificar solicitante
        fam = db.execute("SELECT usuario_id FROM solicitantes WHERE id=?", (s['solicitante_id'],)).fetchone()
        pr_nombre = session.get('nombre', '') + ' ' + session.get('apellido', '')
        if fam:
            _notificar(db, fam['usuario_id'], 'prestador_llego',
                       'El prestador llegó',
                       f'{pr_nombre.strip()} confirmó su llegada. El servicio comenzó.')
        admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
        if admin:
            _notificar(db, admin['id'], 'servicio_iniciado',
                       'Servicio iniciado',
                       f'Prestador {pr_nombre.strip()} llegó para servicio #{sid}.')
        db.commit()
        print(f"[confirmar_llegada] OK — servicio {sid} -> estado=ACTIVO, distancia={round(distancia)}m")
        return jsonify({'ok': True, 'distancia': round(distancia)})

    except Exception as e:
        print(f"[confirmar_llegada] ERROR INESPERADO — servicio={sid}: {e}")
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@prestador_bp.route('/servicios/<int:sid>/confirmar-fin', methods=['POST'])
def servicio_confirmar_fin(sid):
    db  = get_db()
    pid = _get_prestador_id(db)

    s = db.execute(
        """SELECT s.*, pr.tarifa_hora AS tarifa_pr
           FROM servicios s
           JOIN prestadores pr ON pr.id = s.prestador_id
           WHERE s.id=? AND s.prestador_id=? AND s.estado='ACTIVO' AND s.prestador_confirmo_fin=0""",
        (sid, pid)
    ).fetchone()
    if not s:
        flash('No se puede confirmar la finalización en este momento.', 'error')
        return redirect(url_for('prestador.servicio_detalle', sid=sid))

    ahora = ahora_argentina()

    # ── Calcular monto ────────────────────────────────────────────────────────
    cfg = {r['clave']: r['valor'] for r in db.execute(
        "SELECT clave, valor FROM configuracion "
        "WHERE clave IN ('comision_solicitante_pct','comision_prestador_pct')"
    ).fetchall()}

    try:
        hi_h, hi_m = map(int, s['hora_inicio'].split(':'))
        hf_h, hf_m = map(int, s['hora_fin'].split(':'))
        mins  = (hf_h * 60 + hf_m) - (hi_h * 60 + hi_m)
        horas = max(mins / 60, 0)
    except Exception:
        horas = 0

    tarifa_hora = s['tarifa_pr'] or s['tarifa_hora'] or 0
    monto_bruto = round(tarifa_hora * horas, 2) if (tarifa_hora and horas) else (s['monto_estimado'] or 0)

    sol_pct  = float(cfg.get('comision_solicitante_pct', 15))
    pres_pct = float(cfg.get('comision_prestador_pct', 7))
    comision_solicitante = round(monto_bruto * sol_pct  / 100, 2)
    comision_prestador   = round(monto_bruto * pres_pct / 100, 2)
    comision_monto       = round(comision_solicitante + comision_prestador, 2)
    comision_pct         = 0
    monto_neto           = round(monto_bruto - comision_prestador, 2)

    # ── Procesar cobro automático ─────────────────────────────────────────────
    # En sandbox o sin credenciales: simular cobro exitoso directamente
    from auth import _cfg_db as _cfgdb
    mp_modo         = _cfgdb('mp_modo', 'sandbox')
    mp_access_token = _cfgdb('mp_access_token', '').strip()
    metodo_pago     = 'automatico_sandbox' if (mp_modo == 'sandbox' or not mp_access_token) else 'automatico_mp'

    # ── Actualizar servicio y crear pago ──────────────────────────────────────
    db.execute(
        """UPDATE servicios SET
               prestador_confirmo_fin=1, fecha_confirmacion_prestador=?,
               solicitante_confirmo_fin=1,   fecha_confirmacion_solicitante=?,
               fecha_finalizacion=?,     estado='FINALIZADO'
           WHERE id=?""",
        (ahora, ahora, ahora, sid)
    )
    cur = db.execute(
        """INSERT INTO pagos
           (servicio_id, solicitante_id, prestador_id, tipo_pago,
            monto_bruto, comision_pct, comision_monto,
            comision_solicitante, comision_prestador,
            monto_neto, estado, metodo_pago, fecha_pago, fecha_liquidacion)
           VALUES (?,?,?,'servicio',?,?,?,?,?,?,'LIQUIDADO',?,?,?)""",
        (sid, s['solicitante_id'], pid,
         monto_bruto, comision_pct, comision_monto,
         comision_solicitante, comision_prestador,
         monto_neto, metodo_pago, ahora, ahora)
    )
    pago_id = cur.lastrowid

    pr_nombre = session.get('nombre', '') + ' ' + session.get('apellido', '')

    # ── Notificar solicitante ─────────────────────────────────────────────────────
    fam = db.execute("SELECT usuario_id FROM solicitantes WHERE id=?", (s['solicitante_id'],)).fetchone()
    if fam:
        _notificar(db, fam['usuario_id'], 'pago_liquidado',
                   '✅ Cobro liquidado',
                   f'Se liquidó el pago de $ {monto_bruto:.2f} por el servicio de '
                   f'{pr_nombre.strip()} del {s["fecha_servicio"]}.')

    # ── Notificar prestador ───────────────────────────────────────────────────
    pr_user = db.execute("SELECT usuario_id FROM prestadores WHERE id=?", (pid,)).fetchone()
    if pr_user:
        _notificar(db, pr_user['usuario_id'], 'pago_liquidado',
                   f'💰 Tu pago de $ {monto_neto:.0f} fue acreditado',
                   f'El pago por el servicio del {s["fecha_servicio"]} fue liquidado.')

    # ── Notificar admin ───────────────────────────────────────────────────────
    admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
    if admin:
        _notificar(db, admin['id'], 'pago_liquidado',
                   f'✅ Cobro liquidado — servicio #{sid}',
                   f'$ {monto_bruto:.0f} (neto prestador: $ {monto_neto:.0f})')

    db.commit()
    print(f"[confirmar_fin] Servicio #{sid} finalizado. Cobro LIQUIDADO: $ {monto_bruto:.2f} ({metodo_pago})")

    # ── Enviar correos con desglose ───────────────────────────────────────────
    _enviar_correos_liquidacion(db, pago_id)

    flash(f'✅ Servicio finalizado. El cobro de $ {monto_bruto:.0f} fue liquidado automáticamente.', 'success')
    return redirect(url_for('prestador.servicio_detalle', sid=sid))


# ─── COBROS ───────────────────────────────────────────────────────────────────

@prestador_bp.route('/cobros')
def cobros():
    db   = get_db()
    pid  = _get_prestador_id(db)
    tab  = request.args.get('tab', 'pendientes')
    page = max(1, int(request.args.get('page', 1)))
    PER_PAGE = 10

    total_pendiente = db.execute(
        "SELECT COALESCE(SUM(monto_neto),0) as s FROM pagos WHERE prestador_id=? AND estado='PROCESADO'",
        (pid,)
    ).fetchone()['s']

    hoy = date.today()
    total_mes = db.execute(
        """SELECT COALESCE(SUM(monto_neto),0) as s FROM pagos
           WHERE prestador_id=? AND estado='LIQUIDADO'
             AND strftime('%Y-%m', fecha_liquidacion) = ?""",
        (pid, hoy.strftime('%Y-%m'))
    ).fetchone()['s']

    if tab == 'pendientes':
        rows = db.execute(
            """SELECT p.*, u.nombre || ' ' || u.apellido AS solicitante_nombre,
                      s.fecha_servicio
               FROM pagos p
               JOIN servicios s ON s.id = p.servicio_id
               JOIN solicitantes fam ON fam.id = p.solicitante_id
               JOIN usuarios u ON u.id = fam.usuario_id
               WHERE p.prestador_id=? AND p.estado='PROCESADO'
               ORDER BY p.fecha_pago DESC""",
            (pid,)
        ).fetchall()
        total_pages = 1
    else:  # historial
        total = db.execute(
            "SELECT COUNT(*) as c FROM pagos WHERE prestador_id=? AND estado='LIQUIDADO'", (pid,)
        ).fetchone()['c']
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        offset = (page - 1) * PER_PAGE
        rows = db.execute(
            """SELECT p.*, u.nombre || ' ' || u.apellido AS solicitante_nombre,
                      s.fecha_servicio
               FROM pagos p
               JOIN servicios s ON s.id = p.servicio_id
               JOIN solicitantes fam ON fam.id = p.solicitante_id
               JOIN usuarios u ON u.id = fam.usuario_id
               WHERE p.prestador_id=? AND p.estado='LIQUIDADO'
               ORDER BY p.fecha_liquidacion DESC LIMIT ? OFFSET ?""",
            (pid, PER_PAGE, offset)
        ).fetchall()

    return render_template('prestador/cobros.html',
                           tab=tab, rows=rows,
                           total_pendiente=round(total_pendiente, 2),
                           total_mes=round(total_mes, 2),
                           page=page, total_pages=total_pages,
                           **_ctx())


# ─── PERFIL ───────────────────────────────────────────────────────────────────

@prestador_bp.route('/perfil')
def perfil():
    db  = get_db()
    pid = _get_prestador_id(db)
    if not pid:
        flash('Tu perfil de prestador no fue encontrado.', 'error')
        return redirect(url_for('auth.logout'))

    prestador = db.execute(
        """SELECT pr.*, u.nombre, u.apellido, u.email, u.telefono,
                  c.nombre AS categoria_nombre,
                  z.nombre AS zona_nombre
           FROM prestadores pr
           JOIN usuarios u ON u.id = pr.usuario_id
           LEFT JOIN categorias c ON c.id = pr.categoria_id
           LEFT JOIN zonas z ON z.id = pr.zona_id
           WHERE pr.id=?""",
        (pid,)
    ).fetchone()

    disponibilidad = db.execute(
        'SELECT * FROM disponibilidad WHERE prestador_id=? ORDER BY id', (pid,)
    ).fetchall()

    puntaje_row = db.execute(
        "SELECT AVG(puntaje) as avg, COUNT(*) as cnt FROM calificaciones WHERE prestador_id=?", (pid,)
    ).fetchone()

    servicios_count = db.execute(
        "SELECT COUNT(*) as c FROM servicios WHERE prestador_id=? AND estado='FINALIZADO'", (pid,)
    ).fetchone()['c']

    resenas = db.execute(
        """SELECT cal.puntaje, cal.comentario, cal.fecha,
                  u.nombre || ' ' || u.apellido AS solicitante_nombre
           FROM calificaciones cal
           JOIN solicitantes fam ON fam.id = cal.solicitante_id
           JOIN usuarios u ON u.id = fam.usuario_id
           WHERE cal.prestador_id=?
           ORDER BY cal.fecha DESC LIMIT 5""",
        (pid,)
    ).fetchall()

    return render_template('prestador/perfil.html',
                           prestador=prestador,
                           disponibilidad=disponibilidad,
                           puntaje=round(puntaje_row['avg'] or 0, 1),
                           resenas_count=puntaje_row['cnt'],
                           servicios_count=servicios_count,
                           resenas=resenas,
                           **_ctx())


@prestador_bp.route('/perfil/editar', methods=['GET', 'POST'])
def perfil_editar():
    db  = get_db()
    pid = _get_prestador_id(db)
    if not pid:
        flash('Tu perfil de prestador no fue encontrado.', 'error')
        return redirect(url_for('auth.logout'))

    prestador = db.execute(
        """SELECT pr.*, u.nombre, u.apellido, u.email,
                  c.nombre AS categoria_nombre,
                  c.tarifa_minima, c.tarifa_maxima
           FROM prestadores pr
           JOIN usuarios u ON u.id = pr.usuario_id
           LEFT JOIN categorias c ON c.id = pr.categoria_id
           WHERE pr.id=?""",
        (pid,)
    ).fetchone()

    zonas = db.execute('SELECT id, nombre FROM zonas WHERE activa=1 ORDER BY nombre').fetchall()

    # Disponibilidad actual
    disp_actual = {}
    for d in db.execute('SELECT * FROM disponibilidad WHERE prestador_id=?', (pid,)).fetchall():
        key = f"{d['dia_semana']}_{d['hora_inicio']}"
        disp_actual[key] = True

    if request.method == 'POST':
        descripcion      = request.form.get('descripcion', '').strip()
        experiencia      = request.form.get('experiencia_anios', '0').strip()
        try:
            tarifa_hora  = float(request.form.get('tarifa_hora', '0').replace(',', '.'))
        except (ValueError, AttributeError):
            tarifa_hora  = 0.0
        # Cobro
        metodo_cobro     = request.form.get('metodo_cobro', 'mercadopago')
        cbu              = request.form.get('cbu', '').strip() or None
        alias_mp         = request.form.get('alias_mp', '').strip() or None
        email_mp         = request.form.get('email_mp', '').strip() or None
        # Fiscal
        cuit             = request.form.get('cuit', '').strip() or None
        condicion_fiscal = request.form.get('condicion_fiscal', 'no_informada')
        # GPS
        latitud          = request.form.get('latitud', '').strip() or None
        longitud         = request.form.get('longitud', '').strip() or None
        codigo_postal    = request.form.get('codigo_postal', '').strip() or None
        localidad        = request.form.get('localidad', '').strip() or None
        provincia        = request.form.get('provincia', '').strip() or None
        try:
            radio_cobertura_km = int(request.form.get('radio_cobertura_km', '10'))
        except (ValueError, TypeError):
            radio_cobertura_km = 10

        # Foto de perfil
        foto = request.files.get('foto')
        foto_url = prestador['foto_url']
        if foto and foto.filename and _allowed(foto.filename):
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(f'prestador_{pid}.jpg')
            ruta_foto = os.path.join(UPLOAD_FOLDER, filename)
            foto.save(ruta_foto)
            _comprimir_imagen(ruta_foto)
            foto_url = f'/static/uploads/prestadores/{filename}'

        # Fotos DNI
        import time as _time
        uid = session['usuario_id']

        def _guardar_dni(field, prefix, old_url):
            f = request.files.get(field)
            if not f or not f.filename:
                return old_url
            ext = f.filename.rsplit('.', 1)[-1].lower()
            if ext not in ALLOWED_EXTS:
                return old_url
            os.makedirs(UPLOAD_FOLDER_DNI, exist_ok=True)
            fname = secure_filename(f'{prefix}_{uid}_{int(_time.time())}.jpg')
            ruta = os.path.join(UPLOAD_FOLDER_DNI, fname)
            f.save(ruta)
            _comprimir_imagen(ruta)
            return f'/static/docs/dni/{fname}'

        dni_frente_url = _guardar_dni('dni_foto_frente', 'dni_frente', prestador['dni_foto_frente_url'])
        dni_selfie_url = _guardar_dni('dni_foto_selfie', 'dni_selfie', prestador['dni_foto_selfie_url'])

        try:
            experiencia = int(experiencia)
        except ValueError:
            experiencia = 0

        ub_dt = datetime.now().isoformat() if (latitud or codigo_postal) else prestador['ubicacion_actualizada']

        db.execute(
            """UPDATE prestadores SET descripcion=?, experiencia_anios=?,
               foto_url=?, tarifa_hora=?,
               metodo_cobro=?, cbu=?, alias_mp=?, email_mp=?,
               cuit=?, condicion_fiscal=?,
               dni_foto_frente_url=?, dni_foto_selfie_url=?,
               latitud=?, longitud=?, codigo_postal=?, localidad=?, provincia=?,
               radio_cobertura_km=?, ubicacion_actualizada=?
               WHERE id=?""",
            (descripcion, experiencia, foto_url, tarifa_hora,
             metodo_cobro, cbu, alias_mp, email_mp,
             cuit, condicion_fiscal,
             dni_frente_url, dni_selfie_url,
             latitud, longitud, codigo_postal, localidad, provincia,
             radio_cobertura_km, ub_dt, pid)
        )

        # Disponibilidad: borrar y re-insertar
        db.execute('DELETE FROM disponibilidad WHERE prestador_id=?', (pid,))
        for dia in DIAS_SEMANA:
            for franja_key, _, h_ini, h_fin in FRANJAS:
                key = f"disp_{dia}_{franja_key}"
                if request.form.get(key):
                    db.execute(
                        'INSERT INTO disponibilidad (prestador_id, dia_semana, hora_inicio, hora_fin) VALUES (?,?,?,?)',
                        (pid, dia, h_ini, h_fin)
                    )

        admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
        if admin:
            nombre_pr = f"{prestador['nombre']} {prestador['apellido']}"
            _notificar(db, admin['id'], 'MODIFICACION',
                       f'Prestador actualizó su perfil: {nombre_pr}',
                       f'{nombre_pr} modificó datos de su perfil.')
        db.commit()
        flash('Perfil actualizado correctamente.', 'success')
        return redirect(url_for('prestador.perfil'))

    # Reconstruir disponibilidad marcada como dict {dia_franja: True}
    disp_marcada = {}
    for d in db.execute('SELECT * FROM disponibilidad WHERE prestador_id=?', (pid,)).fetchall():
        for franja_key, _, h_ini, _ in FRANJAS:
            if d['hora_inicio'] == h_ini:
                disp_marcada[f"{d['dia_semana']}_{franja_key}"] = True

    return render_template('prestador/perfil_editar.html',
                           prestador=prestador, zonas=zonas,
                           dias=DIAS_SEMANA, franjas=FRANJAS,
                           disp_marcada=disp_marcada,
                           **_ctx())


# ─── CERTIFICADO UPLOAD ───────────────────────────────────────────────────────

@prestador_bp.route('/perfil/certificado/subir', methods=['POST'])
def certificado_subir():
    import time
    db  = get_db()
    pid = _get_prestador_id(db)
    f   = request.files.get('certificado')
    if not f or not f.filename:
        flash('No se seleccionó ningún archivo.', 'error')
        return redirect(url_for('prestador.perfil'))
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED_DOCS:
        flash('Formato no permitido. Usá PDF, JPG o PNG.', 'error')
        return redirect(url_for('prestador.perfil'))
    os.makedirs(UPLOAD_FOLDER_DOCS, exist_ok=True)
    filename = secure_filename(f'cert_{session["usuario_id"]}_{int(time.time())}.{ext}')
    ruta_archivo = os.path.join(UPLOAD_FOLDER_DOCS, filename)
    f.save(ruta_archivo)
    cert_url = f'/static/docs/prestadores/{filename}'
    print(f"[DOC] Guardando certificado en: {ruta_archivo}")
    print(f"[DOC] URL guardada: {cert_url}")
    db.execute('UPDATE prestadores SET certificado_url=? WHERE id=?', (cert_url, pid))
    db.commit()
    flash('Certificado subido correctamente.', 'success')
    return redirect(url_for('prestador.perfil'))


# ─── CV UPLOAD ────────────────────────────────────────────────────────────────

@prestador_bp.route('/perfil/cv/subir', methods=['POST'])
def cv_subir():
    import time
    db  = get_db()
    pid = _get_prestador_id(db)
    f   = request.files.get('cv_archivo')
    redirect_dest = request.form.get('redirect_to', 'perfil')
    dest = url_for('prestador.perfil_editar') + '#cv' if redirect_dest == 'editar' else url_for('prestador.perfil')

    if not f or not f.filename:
        flash('No se seleccionó ningún archivo.', 'error')
        return redirect(dest)
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext != 'pdf':
        flash('Solo se aceptan archivos PDF para el CV.', 'error')
        return redirect(dest)
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > 5 * 1024 * 1024:
        flash('El archivo no puede superar 5 MB.', 'error')
        return redirect(dest)
    cv_folder = os.path.join(UPLOAD_FOLDER_CV, 'prestadores')
    os.makedirs(cv_folder, exist_ok=True)
    filename = secure_filename(f'cv_{session["usuario_id"]}_{int(time.time())}.pdf')
    ruta_cv = os.path.join(cv_folder, filename)
    f.save(ruta_cv)
    cv_url = f'/static/docs/cv/prestadores/{filename}'
    print(f"[DOC] Guardando CV en: {ruta_cv}")
    print(f"[DOC] URL guardada: {cv_url}")
    db.execute('UPDATE prestadores SET cv_url=? WHERE id=?', (cv_url, pid))
    db.commit()
    flash('✅ CV subido correctamente.', 'success')
    return redirect(dest)


# ─── CONTACTO ─────────────────────────────────────────────────────────────────

@prestador_bp.route('/contacto', methods=['GET', 'POST'])
def contacto():
    db  = get_db()
    uid = session['usuario_id']

    if request.method == 'POST':
        tipo_contacto = request.form.get('tipo_contacto', '').strip()
        asunto        = request.form.get('asunto', '').strip()
        descripcion   = request.form.get('descripcion', '').strip()

        errores = []
        if tipo_contacto not in ('problema_tecnico', 'reclamo', 'sugerencia'):
            errores.append('Tipo de contacto inválido.')
        if not asunto or len(asunto) > 100:
            errores.append('El asunto es obligatorio (máximo 100 caracteres).')
        if not descripcion or len(descripcion) < 20:
            errores.append('La descripción debe tener al menos 20 caracteres.')

        if errores:
            for e in errores:
                flash(e, 'error')
            mis_contactos = db.execute(
                "SELECT * FROM contactos WHERE usuario_id=? ORDER BY fecha_envio DESC", (uid,)
            ).fetchall()
            return render_template('prestador/contacto.html',
                                   tipo_preseleccionado=tipo_contacto,
                                   mis_contactos=mis_contactos,
                                   **_ctx())

        db.execute(
            """INSERT INTO contactos (usuario_id, tipo_usuario, tipo_contacto, asunto, descripcion)
               VALUES (?, 'prestador', ?, ?, ?)""",
            (uid, tipo_contacto, asunto, descripcion)
        )
        # Notificar al admin
        admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
        if admin:
            tipos_label = {'problema_tecnico': 'Problema técnico', 'reclamo': 'Reclamo', 'sugerencia': 'Sugerencia'}
            nombre_completo = f"{session.get('nombre', '')} {session.get('apellido', '')}"
            _notificar(db, admin['id'], 'contacto',
                       f"Nuevo {tipos_label.get(tipo_contacto, tipo_contacto)}: {asunto} — de {nombre_completo}")
        db.commit()
        return redirect(url_for('prestador.contacto_enviado'))

    tipo_pre = request.args.get('tipo', '')
    mis_contactos = db.execute(
        "SELECT * FROM contactos WHERE usuario_id=? ORDER BY fecha_envio DESC",
        (uid,)
    ).fetchall()
    return render_template('prestador/contacto.html',
                           tipo_preseleccionado=tipo_pre,
                           mis_contactos=mis_contactos,
                           **_ctx())


@prestador_bp.route('/contacto/enviado')
def contacto_enviado():
    return render_template('prestador/contacto_enviado.html', **_ctx())


@prestador_bp.route('/contacto/<int:cid>')
def contacto_detalle(cid):
    db  = get_db()
    uid = session['usuario_id']
    c = db.execute(
        "SELECT * FROM contactos WHERE id=? AND usuario_id=?", (cid, uid)
    ).fetchone()
    if not c:
        flash('Mensaje no encontrado.', 'error')
        return redirect(url_for('prestador.contacto'))
    return render_template('prestador/contacto_detalle.html', c=c, **_ctx())


# ─── NOTIFICACIONES ───────────────────────────────────────────────────────────

@prestador_bp.route('/notificaciones')
def notificaciones():
    db = get_db()
    notifs = db.execute(
        'SELECT * FROM notificaciones WHERE usuario_id=? ORDER BY fecha DESC',
        (session['usuario_id'],)
    ).fetchall()
    # Marcar todas como leídas
    db.execute(
        'UPDATE notificaciones SET leida=1 WHERE usuario_id=?',
        (session['usuario_id'],)
    )
    db.commit()
    return render_template('prestador/notificaciones.html',
                           notifs=notifs,
                           nombre=session.get('nombre', ''),
                           apellido=session.get('apellido', ''),
                           notif_count=0)
