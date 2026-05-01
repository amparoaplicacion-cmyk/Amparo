import math
import os
from datetime import date, datetime

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, session, url_for)

from database import get_db, ahora_argentina
from auth import enviar_email, _cfg_db


def _calcular_horas(hora_inicio, hora_fin):
    """Calcula horas exactas entre dos horarios HH:MM (acepta también HH:MM:SS)."""
    hi = datetime.strptime(hora_inicio[:5], '%H:%M')
    hf = datetime.strptime(hora_fin[:5], '%H:%M')
    diferencia = hf - hi
    return diferencia.seconds / 3600


def _haversine(lat1, lon1, lat2, lon2):
    """Distancia en km entre dos puntos GPS (fórmula de Haversine)."""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

solicitante_bp = Blueprint('solicitante', __name__, url_prefix='/solicitante')


@solicitante_bp.route('/login')
def login_solicitante():
    if 'usuario_id' in session and session.get('tipo') == 'solicitante':
        return redirect(url_for('solicitante.dashboard'))
    return render_template('login_solicitante.html')

DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
FRANJAS = [
    ('manana', 'Mañana',  '08:00', '12:00'),
    ('tarde',  'Tarde',   '12:00', '18:00'),
    ('noche',  'Noche',   '18:00', '22:00'),
]


# ─── Guards ──────────────────────────────────────────────────────────────────

@solicitante_bp.before_request
def verificar_solicitante():
    if request.endpoint == 'solicitante.pago_mp_webhook':
        return  # Webhook de MP: sin autenticación
    if request.endpoint == 'solicitante.login_solicitante':
        return  # Login PWA: sin autenticacion requerida
    if 'usuario_id' not in session:
        return redirect(url_for('solicitante.login_solicitante'))
    if session.get('tipo') != 'solicitante':
        session.clear()
        return redirect(url_for('solicitante.login_solicitante'))
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
        'nombre':      session.get('nombre', ''),
        'apellido':    session.get('apellido', ''),
        'notif_count': notif_count,
    }


def _get_solicitante_id(db):
    row = db.execute(
        'SELECT id FROM solicitantes WHERE usuario_id=?', (session['usuario_id'],)
    ).fetchone()
    return row['id'] if row else None


def _notificar(db, usuario_id, tipo, titulo, mensaje=None):
    db.execute(
        'INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje) VALUES (?,?,?,?)',
        (usuario_id, tipo, titulo, mensaje)
    )


def _stars(n):
    """Devuelve string de estrellas llenas y vacías."""
    try:
        n = round(float(n or 0))
    except (ValueError, TypeError):
        n = 0
    return '★' * n + '☆' * (5 - n)


# ─── DASHBOARD / BUSCAR ───────────────────────────────────────────────────────

@solicitante_bp.route('/dashboard')
def dashboard():
    db  = get_db()
    fid = _get_solicitante_id(db)
    if not fid:
        flash('Tu perfil de solicitante no fue encontrado.', 'error')
        return redirect(url_for('auth.logout'))

    familia = db.execute('SELECT * FROM solicitantes WHERE id=?', (fid,)).fetchone()

    # Parámetros de búsqueda
    categoria_id = request.args.get('categoria_id', '')
    turno        = request.args.get('turno', '')
    min_cal      = request.args.get('min_cal', '')
    orden        = request.args.get('orden', 'distancia')
    buscar       = request.args.get('buscar', '0')
    try:
        radio_km = int(request.args.get('radio_km', '20'))
    except (ValueError, TypeError):
        radio_km = 20

    categorias = db.execute('SELECT id, nombre FROM categorias WHERE activa=1 ORDER BY nombre').fetchall()

    fam_lat = familia['latitud']
    fam_lon = familia['longitud']
    tiene_ubicacion = bool(fam_lat and fam_lon)

    prestadores = []
    if buscar == '1':
        params = []
        where  = ["pr.estado_perfil='APROBADO'"]

        if categoria_id:
            where.append('pr.categoria_id=?')
            params.append(categoria_id)
        if turno:
            franja_map = {'manana': '08:00', 'tarde': '12:00', 'noche': '18:00'}
            h = franja_map.get(turno)
            if h:
                where.append('EXISTS (SELECT 1 FROM disponibilidad d WHERE d.prestador_id=pr.id AND d.hora_inicio=?)')
                params.append(h)
        if min_cal:
            where.append(f'COALESCE(avg_cal.avg,0) >= {int(min_cal)}')

        sql = f'''
            SELECT pr.id, pr.foto_url, pr.descripcion, pr.experiencia_anios,
                   pr.latitud, pr.longitud, pr.radio_cobertura_km,
                   pr.localidad, pr.provincia, pr.tarifa_hora,
                   pr.dni_verificado, pr.antecedentes_ok, pr.certificados_ok,
                   u.nombre || " " || u.apellido AS nombre_completo,
                   c.nombre AS categoria_nombre,
                   ROUND(COALESCE(avg_cal.avg, 0), 1) AS puntaje,
                   COALESCE(avg_cal.cnt, 0) AS resenas_count
            FROM prestadores pr
            JOIN usuarios u ON u.id = pr.usuario_id
            LEFT JOIN categorias c ON c.id = pr.categoria_id
            LEFT JOIN (
                SELECT prestador_id, AVG(puntaje) AS avg, COUNT(*) AS cnt
                FROM calificaciones GROUP BY prestador_id
            ) avg_cal ON avg_cal.prestador_id = pr.id
            WHERE {" AND ".join(where)}
        '''
        raw = db.execute(sql, params).fetchall()

        prestadores_list = []
        for p in raw:
            p_dict = dict(p)

            # Calcular distancia si ambos tienen GPS
            if tiene_ubicacion and p['latitud'] and p['longitud']:
                dist = _haversine(fam_lat, fam_lon, p['latitud'], p['longitud'])
                p_dict['distancia_km'] = round(dist, 1)
                # Filtrar: distancia dentro del radio buscado Y dentro del radio del prestador
                if dist > radio_km:
                    continue
                if dist > (p['radio_cobertura_km'] or 10):
                    continue
            else:
                p_dict['distancia_km'] = None

            disp = db.execute(
                'SELECT dia_semana, hora_inicio FROM disponibilidad WHERE prestador_id=? ORDER BY id',
                (p['id'],)
            ).fetchall()
            dias_set = sorted({d['dia_semana'] for d in disp},
                              key=lambda x: DIAS_SEMANA.index(x) if x in DIAS_SEMANA else 99)
            p_dict['dias_disponibles'] = dias_set
            prestadores_list.append(p_dict)

        # Ordenar
        if orden == 'distancia' and tiene_ubicacion:
            prestadores_list.sort(key=lambda x: x['distancia_km'] if x['distancia_km'] is not None else 9999)
        elif orden == 'calificacion':
            prestadores_list.sort(key=lambda x: x['puntaje'], reverse=True)

        prestadores = prestadores_list

        # Guardar búsqueda en sesión para navegación desde perfil
        session['ultima_busqueda'] = {
            'categoria_id': categoria_id,
            'radio_km': radio_km,
            'turno': turno,
            'min_cal': min_cal,
            'orden': orden,
        }
        session['resultados_busqueda'] = [p['id'] for p in prestadores_list]

    # Indicadores KPI
    pendientes_resp = db.execute(
        "SELECT COUNT(*) as c FROM servicios WHERE solicitante_id=? AND estado='PENDIENTE'", (fid,)
    ).fetchone()['c']
    activos = db.execute(
        "SELECT COUNT(*) as c FROM servicios WHERE solicitante_id=? AND estado IN ('ACEPTADO','ACTIVO')", (fid,)
    ).fetchone()['c']
    proximo = db.execute(
        """SELECT fecha_servicio, hora_inicio FROM servicios
           WHERE solicitante_id=? AND estado IN ('ACEPTADO','ACTIVO') AND fecha_servicio >= ?
           ORDER BY fecha_servicio, hora_inicio LIMIT 1""",
        (fid, date.today().isoformat())
    ).fetchone()
    reclamos_abiertos = db.execute(
        """SELECT COUNT(*) as c FROM reclamos r
           JOIN servicios s ON s.id = r.servicio_id
           WHERE s.solicitante_id=? AND r.estado='ABIERTO'""", (fid,)
    ).fetchone()['c']

    sin_calificar = db.execute(
        '''SELECT s.id, s.fecha_servicio,
                  u.nombre || ' ' || u.apellido AS prestador_nombre
           FROM servicios s
           JOIN prestadores pr ON pr.id = s.prestador_id
           JOIN usuarios u     ON u.id  = pr.usuario_id
           WHERE s.solicitante_id=? AND s.estado='FINALIZADO'
             AND s.id NOT IN (SELECT servicio_id FROM calificaciones)
           ORDER BY s.fecha_servicio DESC''',
        (fid,)
    ).fetchall()

    return render_template('solicitante/dashboard.html',
                           familia=familia,
                           categorias=categorias,
                           prestadores=prestadores,
                           buscar=buscar,
                           categoria_id=categoria_id,
                           radio_km=radio_km,
                           turno=turno,
                           min_cal=min_cal,
                           orden=orden,
                           tiene_ubicacion=tiene_ubicacion,
                           pendientes_resp=pendientes_resp,
                           activos=activos,
                           proximo=proximo,
                           reclamos_abiertos=reclamos_abiertos,
                           sin_calificar=sin_calificar,
                           stars_fn=_stars,
                           **_ctx())


# ─── PERFIL PRESTADOR ─────────────────────────────────────────────────────────

@solicitante_bp.route('/prestadores/<int:pid>')
def prestador_perfil(pid):
    db = get_db()

    prestador = db.execute(
        '''SELECT pr.id, pr.foto_url, pr.descripcion, pr.experiencia_anios,
                  pr.dni_verificado, pr.antecedentes_ok, pr.certificados_ok,
                  pr.tarifa_hora,
                  u.nombre || " " || u.apellido AS nombre_completo,
                  c.nombre AS categoria_nombre, c.id AS categoria_id,
                  c.tarifa_minima, c.tarifa_maxima,
                  z.nombre AS zona_nombre,
                  ROUND(COALESCE(avg_cal.avg, 0), 1) AS puntaje,
                  COALESCE(avg_cal.cnt, 0) AS resenas_count
           FROM prestadores pr
           JOIN usuarios u ON u.id = pr.usuario_id
           LEFT JOIN categorias c ON c.id = pr.categoria_id
           LEFT JOIN zonas z ON z.id = pr.zona_id
           LEFT JOIN (
               SELECT prestador_id, AVG(puntaje) AS avg, COUNT(*) AS cnt
               FROM calificaciones GROUP BY prestador_id
           ) avg_cal ON avg_cal.prestador_id = pr.id
           WHERE pr.id=? AND pr.estado_perfil='APROBADO' ''',
        (pid,)
    ).fetchone()
    if not prestador:
        abort(404)

    # Navegación desde resultados de búsqueda
    resultados = session.get('resultados_busqueda', [])
    ub          = session.get('ultima_busqueda', {})
    prev_id = next_id = None
    pos_actual = total = None
    if pid in resultados:
        idx        = resultados.index(pid)
        pos_actual = idx + 1
        total      = len(resultados)
        prev_id    = resultados[idx - 1] if idx > 0 else None
        next_id    = resultados[idx + 1] if idx < len(resultados) - 1 else None

    if ub:
        volver_url = url_for('solicitante.dashboard', buscar='1',
                             categoria_id=ub.get('categoria_id', ''),
                             radio_km=ub.get('radio_km', 20),
                             turno=ub.get('turno', ''),
                             min_cal=ub.get('min_cal', ''),
                             orden=ub.get('orden', 'distancia'))
        volver_label = '← Volver a los resultados'
    else:
        volver_url   = url_for('solicitante.dashboard')
        volver_label = '← Volver'

    disponibilidad = db.execute(
        'SELECT dia_semana, hora_inicio FROM disponibilidad WHERE prestador_id=? ORDER BY id',
        (pid,)
    ).fetchall()

    # Construir grilla de disponibilidad
    disp_set = set()
    for d in disponibilidad:
        disp_set.add((d['dia_semana'], d['hora_inicio']))

    resenas = db.execute(
        '''SELECT cal.puntaje, cal.comentario, cal.fecha
           FROM calificaciones cal
           WHERE cal.prestador_id=? AND cal.moderada != 1
           ORDER BY cal.fecha DESC LIMIT 5''',
        (pid,)
    ).fetchall()

    return render_template('solicitante/prestador_perfil.html',
                           p=prestador,
                           disp_set=disp_set,
                           dias=DIAS_SEMANA,
                           franjas=FRANJAS,
                           resenas=resenas,
                           stars_fn=_stars,
                           volver_url=volver_url,
                           volver_label=volver_label,
                           prev_id=prev_id,
                           next_id=next_id,
                           pos_actual=pos_actual,
                           total=total,
                           **_ctx())


# ─── CALCULAR PRESUPUESTO (API) ───────────────────────────────────────────────

@solicitante_bp.route('/calcular_presupuesto')
def calcular_presupuesto():
    from flask import jsonify
    db           = get_db()
    prestador_id = request.args.get('prestador_id', type=int)
    hora_inicio  = request.args.get('hora_inicio', '').strip()
    hora_fin     = request.args.get('hora_fin', '').strip()

    if not prestador_id or not hora_inicio or not hora_fin:
        return jsonify({'error': 'Faltan parametros'}), 400

    pr = db.execute('SELECT tarifa_hora FROM prestadores WHERE id=?', (prestador_id,)).fetchone()
    if not pr:
        return jsonify({'error': 'Prestador no encontrado'}), 404

    tarifa_hora = pr['tarifa_hora'] or 0

    try:
        horas = _calcular_horas(hora_inicio, hora_fin)
    except Exception:
        return jsonify({'error': 'Horarios invalidos'}), 400

    if horas <= 0:
        return jsonify({'error': 'La hora fin debe ser posterior al inicio'}), 400

    if tarifa_hora == 0:
        return jsonify({'sin_tarifa': True, 'horas': round(horas, 1)})

    monto_servicio = tarifa_hora * horas

    cfg = {}
    for row in db.execute(
        "SELECT clave, valor FROM configuracion "
        "WHERE clave IN ('comision_solicitante_pct','comision_prestador_pct')"
    ).fetchall():
        cfg[row['clave']] = row['valor']

    sol_pct  = float(cfg.get('comision_solicitante_pct', 15))
    comision_solicitante = round(monto_servicio * sol_pct / 100, 2)
    monto_total = round(monto_servicio + comision_solicitante, 2)

    return jsonify({
        'sin_tarifa':          False,
        'horas':               round(horas, 1),
        'tarifa_hora':         tarifa_hora,
        'monto_servicio':      round(monto_servicio, 2),
        'comision_monto':      round(comision_solicitante, 2),
        'comision_label':      f'{sol_pct:.0f}%',
        'monto_total':         monto_total,
    })


# ─── NUEVA SOLICITUD ──────────────────────────────────────────────────────────

@solicitante_bp.route('/solicitud/nueva/<int:prestador_id>', methods=['GET', 'POST'])
def solicitud_nueva(prestador_id):
    db  = get_db()
    fid = _get_solicitante_id(db)

    prestador = db.execute(
        '''SELECT pr.id, pr.foto_url, pr.categoria_id,
                  u.nombre || " " || u.apellido AS nombre_completo,
                  c.nombre AS categoria_nombre,
                  c.tarifa_minima, c.tarifa_maxima
           FROM prestadores pr
           JOIN usuarios u ON u.id = pr.usuario_id
           LEFT JOIN categorias c ON c.id = pr.categoria_id
           WHERE pr.id=? AND pr.estado_perfil='APROBADO' ''',
        (prestador_id,)
    ).fetchone()
    if not prestador:
        abort(404)

    categorias = db.execute('SELECT id, nombre FROM categorias WHERE activa=1 ORDER BY nombre').fetchall()

    if request.method == 'POST':
        fecha_servicio = request.form.get('fecha_servicio', '').strip()
        hora_inicio    = request.form.get('hora_inicio', '').strip()
        hora_fin       = request.form.get('hora_fin', '').strip()
        categoria_id   = request.form.get('categoria_id', prestador['categoria_id'])
        mensaje        = request.form.get('mensaje', '').strip() or None

        errores = []
        if not fecha_servicio:
            errores.append('La fecha del servicio es obligatoria.')
        elif fecha_servicio < date.today().isoformat():
            errores.append('La fecha no puede ser en el pasado.')
        if not hora_inicio:
            errores.append('La hora de inicio es obligatoria.')
        if not hora_fin:
            errores.append('La hora de fin es obligatoria.')
        if hora_inicio and hora_fin and hora_fin <= hora_inicio:
            errores.append('La hora de fin debe ser posterior a la de inicio.')

        if errores:
            for e in errores:
                flash(e, 'error')
        else:
            # Calcular presupuesto para guardar
            pr_row = db.execute('SELECT tarifa_hora FROM prestadores WHERE id=?', (prestador_id,)).fetchone()
            tarifa_hora = (pr_row['tarifa_hora'] or 0) if pr_row else 0
            try:
                horas_est = _calcular_horas(hora_inicio, hora_fin)
            except Exception:
                horas_est = 0
            if tarifa_hora and horas_est:
                monto_est = tarifa_hora * horas_est
                cfg = {r['clave']: r['valor'] for r in db.execute(
                    "SELECT clave,valor FROM configuracion WHERE clave IN ('comision_tipo','comision_pct_default','comision_fijo')"
                ).fetchall()}
                if cfg.get('comision_tipo', 'porcentaje') == 'porcentaje':
                    comision_est = monto_est * float(cfg.get('comision_pct_default', 15)) / 100
                else:
                    comision_est = float(cfg.get('comision_fijo', 0))
                total_est = round(monto_est + comision_est, 2)
                monto_est  = round(monto_est, 2)
                comision_est = round(comision_est, 2)
            else:
                tarifa_hora = None; horas_est = None; monto_est = None
                comision_est = None; total_est = None

            cur = db.execute(
                '''INSERT INTO servicios
                   (solicitante_id, prestador_id, categoria_id, fecha_servicio,
                    hora_inicio, hora_fin, mensaje_solicitante, estado, fecha_solicitud,
                    tarifa_hora, horas_estimadas, monto_estimado, comision_estimada, total_estimado)
                   VALUES (?,?,?,?,?,?,?,'PENDIENTE',?,?,?,?,?,?)''',
                (fid, prestador_id, categoria_id,
                 fecha_servicio, hora_inicio, hora_fin, mensaje,
                 ahora_argentina(),
                 tarifa_hora, horas_est, monto_est, comision_est, total_est)
            )
            servicio_id = cur.lastrowid

            # Notificar al prestador
            pr_usuario = db.execute(
                'SELECT usuario_id FROM prestadores WHERE id=?', (prestador_id,)
            ).fetchone()
            if pr_usuario:
                _notificar(db, pr_usuario['usuario_id'], 'nueva_solicitud',
                           'Nueva solicitud de servicio',
                           f'Recibiste una solicitud para el {fecha_servicio} de {hora_inicio} a {hora_fin}.')
            db.commit()
            flash('¡Solicitud enviada! El prestador tiene 24 horas para responder.', 'success')
            return redirect(url_for('solicitante.contrataciones', tab='pendientes'))

    return render_template('solicitante/solicitud_nueva.html',
                           prestador=prestador,
                           categorias=categorias,
                           hoy=date.today().isoformat(),
                           **_ctx())


# ─── CONTRATACIONES ───────────────────────────────────────────────────────────

@solicitante_bp.route('/contrataciones')
def contrataciones():
    db   = get_db()
    fid  = _get_solicitante_id(db)
    tab  = request.args.get('tab', 'pendientes')
    page = max(1, int(request.args.get('page', 1)))
    PER_PAGE = 10

    if tab == 'pendientes':
        rows = db.execute(
            '''SELECT s.*,
                      u.nombre || " " || u.apellido AS prestador_nombre,
                      pr.foto_url,
                      c.nombre AS categoria_nombre
               FROM servicios s
               JOIN prestadores pr ON pr.id = s.prestador_id
               JOIN usuarios u ON u.id = pr.usuario_id
               LEFT JOIN categorias c ON c.id = s.categoria_id
               WHERE s.solicitante_id=? AND s.estado='PENDIENTE'
               ORDER BY s.fecha_solicitud DESC''',
            (fid,)
        ).fetchall()
        total_pages = 1

    elif tab == 'activos':
        rows = db.execute(
            '''SELECT s.*,
                      u.nombre || " " || u.apellido AS prestador_nombre,
                      u.telefono AS prestador_telefono,
                      pr.foto_url,
                      c.nombre AS categoria_nombre
               FROM servicios s
               JOIN prestadores pr ON pr.id = s.prestador_id
               JOIN usuarios u ON u.id = pr.usuario_id
               LEFT JOIN categorias c ON c.id = s.categoria_id
               WHERE s.solicitante_id=? AND s.estado IN ('ACEPTADO','ACTIVO','PENDIENTE_CONFIRMACION')
               ORDER BY s.fecha_servicio, s.hora_inicio''',
            (fid,)
        ).fetchall()
        total_pages = 1

    else:  # historial
        total = db.execute(
            "SELECT COUNT(*) as c FROM servicios WHERE solicitante_id=? AND estado IN ('FINALIZADO','CANCELADO','RECHAZADO')",
            (fid,)
        ).fetchone()['c']
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        offset = (page - 1) * PER_PAGE
        rows = db.execute(
            '''SELECT s.*,
                      u.nombre || " " || u.apellido AS prestador_nombre,
                      pr.foto_url,
                      c.nombre AS categoria_nombre,
                      cal.puntaje AS mi_calificacion,
                      pg.monto_bruto,
                      pg.comision_monto,
                      (COALESCE(pg.monto_bruto, 0) + COALESCE(pg.comision_monto, 0)) AS total_pagado
               FROM servicios s
               JOIN prestadores pr ON pr.id = s.prestador_id
               JOIN usuarios u ON u.id = pr.usuario_id
               LEFT JOIN categorias c ON c.id = s.categoria_id
               LEFT JOIN calificaciones cal ON cal.servicio_id = s.id AND cal.solicitante_id = s.solicitante_id
               LEFT JOIN pagos pg ON pg.servicio_id = s.id
               WHERE s.solicitante_id=? AND s.estado IN ('FINALIZADO','CANCELADO','RECHAZADO')
               ORDER BY s.fecha_servicio DESC LIMIT ? OFFSET ?''',
            (fid, PER_PAGE, offset)
        ).fetchall()

    return render_template('solicitante/contrataciones.html',
                           tab=tab, rows=rows,
                           page=page, total_pages=total_pages,
                           **_ctx())


@solicitante_bp.route('/contrataciones/<int:sid>')
def contratacion_detalle(sid):
    db  = get_db()
    fid = _get_solicitante_id(db)

    s = db.execute(
        '''SELECT s.*,
                  u.nombre || " " || u.apellido AS prestador_nombre,
                  u.telefono AS prestador_telefono,
                  u.email AS prestador_email,
                  pr.foto_url,
                  c.nombre AS categoria_nombre
           FROM servicios s
           JOIN prestadores pr ON pr.id = s.prestador_id
           JOIN usuarios u ON u.id = pr.usuario_id
           LEFT JOIN categorias c ON c.id = s.categoria_id
           WHERE s.id=? AND s.solicitante_id=?''',
        (sid, fid)
    ).fetchone()
    if not s:
        abort(404)

    pago = db.execute('SELECT * FROM pagos WHERE servicio_id=?', (sid,)).fetchone()
    cal  = db.execute(
        'SELECT * FROM calificaciones WHERE servicio_id=? AND solicitante_id=?',
        (sid, fid)
    ).fetchone()

    return render_template('solicitante/contratacion_detalle.html',
                           s=s, pago=pago, cal=cal,
                           **_ctx())


@solicitante_bp.route('/contrataciones/<int:sid>/cancelar', methods=['POST'])
def contratacion_cancelar(sid):
    db  = get_db()
    fid = _get_solicitante_id(db)

    s = db.execute(
        "SELECT * FROM servicios WHERE id=? AND solicitante_id=? AND estado IN ('PENDIENTE','ACEPTADO','ACTIVO')",
        (sid, fid)
    ).fetchone()
    if not s:
        flash('No se puede cancelar este servicio.', 'error')
        return redirect(url_for('solicitante.contrataciones'))

    # Si ya fue aceptado -> hay penalidad, redirigir a pagina de advertencia
    if s['estado'] in ('ACEPTADO', 'ACTIVO'):
        return redirect(url_for('solicitante.contratacion_cancelar_penalidad', sid=sid))

    # PENDIENTE: cancelar sin penalidad
    motivo = request.form.get('motivo', '').strip()
    if not motivo:
        flash('El motivo de cancelación es obligatorio.', 'error')
        return redirect(url_for('solicitante.contratacion_detalle', sid=sid))

    db.execute(
        "UPDATE servicios SET estado='CANCELADO', motivo_cancelacion=? WHERE id=?",
        (motivo, sid)
    )
    pr_usuario = db.execute(
        'SELECT usuario_id FROM prestadores WHERE id=?', (s['prestador_id'],)
    ).fetchone()
    if pr_usuario:
        _notificar(db, pr_usuario['usuario_id'], 'servicio_cancelado',
                   'Servicio cancelado por el solicitante',
                   f'El solicitante canceló la solicitud.')
    db.commit()
    # Email al solicitante
    sol_u = db.execute(
        'SELECT u.nombre, u.email FROM solicitantes sol JOIN usuarios u ON u.id=sol.usuario_id WHERE sol.id=?',
        (fid,)
    ).fetchone()
    if sol_u:
        pr_row = db.execute(
            'SELECT u.nombre, u.apellido FROM prestadores pr JOIN usuarios u ON u.id=pr.usuario_id WHERE pr.id=?',
            (s['prestador_id'],)
        ).fetchone()
        pr_nombre = f"{pr_row['nombre']} {pr_row['apellido']}" if pr_row else ''
        asunto = _cfg_db('mail_cancelacion_sin_penalidad_asunto', 'Servicio cancelado — AMPARO')
        cuerpo = _cfg_db('mail_cancelacion_sin_penalidad_cuerpo',
            'Hola {nombre},\n\nTu servicio fue cancelado sin penalidad.\n\n'
            'Prestador: {prestador_nombre}\n'
            'Fecha: {fecha_servicio}\n'
            'Horario: {hora_inicio} a {hora_fin}\n\n{link_app}')
        cuerpo = (cuerpo
            .replace('{nombre}', sol_u['nombre'])
            .replace('{prestador_nombre}', pr_nombre)
            .replace('{fecha_servicio}', str(s['fecha_servicio']))
            .replace('{hora_inicio}', str(s['hora_inicio']))
            .replace('{hora_fin}', str(s['hora_fin']))
            .replace('{link_app}', _cfg_db('app_url', 'http://127.0.0.1:5000') + '/solicitante/dashboard')
        )
        enviar_email(sol_u['email'], asunto, cuerpo)
    flash('Servicio cancelado.', 'success')
    return redirect(url_for('solicitante.contrataciones', tab='historial'))


@solicitante_bp.route('/contrataciones/<int:sid>/cancelar-penalidad')
def contratacion_cancelar_penalidad(sid):
    db  = get_db()
    fid = _get_solicitante_id(db)

    s = db.execute(
        """SELECT s.*, u.nombre || ' ' || u.apellido AS prestador_nombre
           FROM servicios s
           JOIN prestadores pr ON pr.id = s.prestador_id
           JOIN usuarios u ON u.id = pr.usuario_id
           WHERE s.id=? AND s.solicitante_id=? AND s.estado IN ('ACEPTADO','ACTIVO')""",
        (sid, fid)
    ).fetchone()
    if not s:
        flash('No se puede cancelar este servicio con penalidad.', 'error')
        return redirect(url_for('solicitante.contrataciones'))

    cfg = {r['clave']: r['valor'] for r in db.execute(
        "SELECT clave, valor FROM configuracion WHERE clave IN ('cancelacion_penalidad_pct')"
    ).fetchall()}

    penalidad_pct = float(cfg.get('cancelacion_penalidad_pct', 10))
    monto_ref     = s['monto_estimado'] or s['monto_acordado'] or 0
    penalidad     = round(monto_ref * penalidad_pct / 100, 2)

    return render_template('solicitante/cancelar_penalidad.html',
                           s=s, penalidad=penalidad,
                           penalidad_pct=penalidad_pct,
                           monto_ref=monto_ref, **_ctx())


@solicitante_bp.route('/contrataciones/<int:sid>/cancelar-confirmar', methods=['POST'])
def contratacion_cancelar_confirmar(sid):
    db  = get_db()
    fid = _get_solicitante_id(db)

    s = db.execute(
        "SELECT * FROM servicios WHERE id=? AND solicitante_id=? AND estado IN ('ACEPTADO','ACTIVO')",
        (sid, fid)
    ).fetchone()
    if not s:
        flash('No se puede cancelar este servicio.', 'error')
        return redirect(url_for('solicitante.contrataciones'))

    print(f"[PENALIDAD] Iniciando cancelación con penalidad — servicio={sid} solicitante={fid}")

    # ── Paso 1: calcular montos ───────────────────────────────────────────────
    cfg = {r['clave']: r['valor'] for r in db.execute(
        "SELECT clave, valor FROM configuracion WHERE clave IN ('cancelacion_penalidad_pct','cancelacion_prestador_pct','cancelacion_amparo_pct')"
    ).fetchall()}

    penalidad_pct    = float(cfg.get('cancelacion_penalidad_pct', 10))
    prestador_pct    = float(cfg.get('cancelacion_prestador_pct', 70))
    amparo_pct_cfg   = float(cfg.get('cancelacion_amparo_pct', 30))
    monto_ref        = float(s['monto_estimado'] or s['monto_acordado'] or 0)
    penalidad_total  = round(monto_ref * penalidad_pct / 100, 2)
    penalidad_prest  = round(penalidad_total * prestador_pct / 100, 2)
    penalidad_amparo = round(penalidad_total * amparo_pct_cfg / 100, 2)

    print(f"[PENALIDAD] monto_ref={monto_ref} pct={penalidad_pct}% total={penalidad_total} prest={penalidad_prest} amparo={penalidad_amparo}")

    # ── Paso 2: cancelar el servicio y crear el registro de pago — COMMIT inmediato ──
    try:
        db.execute(
            "UPDATE servicios SET estado='CANCELADO', motivo_cancelacion=? WHERE id=?",
            ('Cancelado por el solicitante — penalidad aplicada.', sid)
        )
        cur = db.execute(
            """INSERT INTO pagos
               (servicio_id, solicitante_id, prestador_id, tipo_pago,
                monto_bruto, comision_pct, comision_monto, monto_neto, estado)
               VALUES (?,?,?,'penalidad',?,?,?,?,'PENDIENTE')""",
            (sid, fid, s['prestador_id'],
             penalidad_total, amparo_pct_cfg, penalidad_amparo, penalidad_prest)
        )
        pago_id = cur.lastrowid
        db.commit()
        print(f"[PENALIDAD] Servicio {sid} cancelado en BD. Pago id={pago_id} insertado. Commit OK.")
    except Exception as e:
        import traceback
        print(f"[PENALIDAD] *** ERROR guardando cancelación servicio={sid}: {e}")
        traceback.print_exc()
        try:
            db.rollback()
        except Exception:
            pass
        flash('Ocurrió un error al cancelar el servicio. Intentá de nuevo o contactá a AMPARO.', 'error')
        return redirect(url_for('solicitante.contratacion_detalle', sid=sid))

    # ── Paso 3: procesar el cobro de penalidad (si falla, la cancelación ya está guardada) ──
    cobro_ok = False
    try:
        pago = db.execute("SELECT * FROM pagos WHERE id=?", (pago_id,)).fetchone()
        _procesar_pago(db, pago, s, metodo='automatico', referencia='AUTO-PENALIDAD')
        db.commit()
        cobro_ok = True
        print(f"[PENALIDAD] Cobro procesado OK — pago_id={pago_id}")
    except Exception as e:
        import traceback
        print(f"[PENALIDAD] *** ERROR procesando cobro pago_id={pago_id}: {e}")
        traceback.print_exc()
        # La cancelación ya está guardada. El pago queda en PENDIENTE para revisión del admin.
        try:
            db.rollback()
        except Exception:
            pass

    # ── Pasos 4 y 5: emails — SOLO si el cobro fue exitoso ────────────────────
    if cobro_ok:
        try:
            sol_u = db.execute(
                'SELECT u.nombre, u.email FROM solicitantes sol JOIN usuarios u ON u.id=sol.usuario_id WHERE sol.id=?',
                (fid,)
            ).fetchone()
            if sol_u:
                pr_row = db.execute(
                    'SELECT u.nombre, u.apellido FROM prestadores pr JOIN usuarios u ON u.id=pr.usuario_id WHERE pr.id=?',
                    (s['prestador_id'],)
                ).fetchone()
                pr_nombre = f"{pr_row['nombre']} {pr_row['apellido']}" if pr_row else ''
                asunto = _cfg_db('mail_cancelacion_con_penalidad_asunto', 'Servicio cancelado con penalidad — AMPARO')
                cuerpo = _cfg_db('mail_cancelacion_con_penalidad_cuerpo',
                    'Hola {nombre},\n\nTu servicio fue cancelado con penalidad.\n\n'
                    'Prestador: {prestador_nombre}\n'
                    'Fecha: {fecha_servicio}\n'
                    'Horario: {hora_inicio} a {hora_fin}\n'
                    'Penalidad aplicada: ${monto_penalidad}\n\n{link_app}')
                cuerpo = (cuerpo
                    .replace('{nombre}', sol_u['nombre'])
                    .replace('{prestador_nombre}', pr_nombre)
                    .replace('{fecha_servicio}', str(s['fecha_servicio']))
                    .replace('{hora_inicio}', str(s['hora_inicio']))
                    .replace('{hora_fin}', str(s['hora_fin']))
                    .replace('{monto_penalidad}', f'{penalidad_total:,.0f}')
                    .replace('{link_app}', _cfg_db('app_url', 'http://127.0.0.1:5000') + '/solicitante/dashboard')
                )
                enviar_email(sol_u['email'], asunto, cuerpo)
        except Exception as email_err:
            print(f"[CORREO] Error enviando email cancelación penalidad: {email_err}")

        try:
            prest_u = db.execute(
                '''SELECT u.email, u.nombre
                   FROM prestadores pr
                   JOIN usuarios u ON pr.usuario_id = u.id
                   WHERE pr.id = ?''',
                (s['prestador_id'],)
            ).fetchone()
            if prest_u:
                asunto_prest = 'Compensación por cancelación — AMPARO'
                cuerpo_prest = (
                    f"Hola {prest_u['nombre']},\n\n"
                    f"El solicitante canceló el servicio del {s['fecha_servicio']}.\n\n"
                    f"Como ya habías aceptado la solicitud, recibís una compensación por la cancelación.\n\n"
                    f"Compensación a recibir: ${penalidad_prest:,.0f}\n\n"
                    f"Este monto será acreditado en tu cuenta a la brevedad.\n\n"
                    f"Para ingresar a tu cuenta: {_cfg_db('app_url', 'http://127.0.0.1:5000')}/prestador/dashboard\n\n"
                    f"El equipo de AMPARO"
                )
                enviar_email(prest_u['email'], asunto_prest, cuerpo_prest)
        except Exception as email_err:
            print(f"[CORREO] Error enviando email compensación prestador: {email_err}")

    flash(
        f'Se canceló el servicio. Por haber cancelado después de la aceptación del prestador, '
        f'se cobró una penalidad de ${penalidad_total:,.0f}.',
        'warning'
    )
    return redirect(url_for('solicitante.contrataciones', tab='historial'))


@solicitante_bp.route('/contrataciones/<int:sid>/pagar')
def contratacion_pagar(sid):
    db  = get_db()
    fid = _get_solicitante_id(db)

    s = db.execute(
        """SELECT s.*, u.nombre || ' ' || u.apellido AS prestador_nombre
           FROM servicios s
           JOIN prestadores pr ON pr.id = s.prestador_id
           JOIN usuarios u ON u.id = pr.usuario_id
           WHERE s.id=? AND s.solicitante_id=?""",
        (sid, fid)
    ).fetchone()
    if not s:
        abort(404)

    pago = db.execute("SELECT * FROM pagos WHERE servicio_id=? AND estado='PENDIENTE'", (sid,)).fetchone()
    if not pago:
        flash('No hay pago pendiente para este servicio.', 'error')
        return redirect(url_for('solicitante.contratacion_detalle', sid=sid))

    tiene_mp    = bool(_cfg_db('mp_access_token', '').strip())
    modo_prueba = not tiene_mp or _cfg_db('mp_modo', 'sandbox') == 'sandbox'

    return render_template('solicitante/pago_servicio.html',
                           s=s, pago=pago,
                           tiene_mp=tiene_mp, modo_prueba=modo_prueba,
                           **_ctx())


@solicitante_bp.route('/contrataciones/<int:sid>/pagar/procesar', methods=['POST'])
def contratacion_pagar_procesar(sid):
    db  = get_db()
    fid = _get_solicitante_id(db)

    s = db.execute(
        """SELECT s.*, u.nombre || ' ' || u.apellido AS prestador_nombre
           FROM servicios s
           JOIN prestadores pr ON pr.id = s.prestador_id
           JOIN usuarios u ON u.id = pr.usuario_id
           WHERE s.id=? AND s.solicitante_id=?""",
        (sid, fid)
    ).fetchone()
    if not s:
        abort(404)

    pago = db.execute("SELECT * FROM pagos WHERE servicio_id=? AND estado='PENDIENTE'", (sid,)).fetchone()
    if not pago:
        flash('No hay pago pendiente.', 'error')
        return redirect(url_for('solicitante.contratacion_detalle', sid=sid))

    access_token = _cfg_db('mp_access_token', '').strip()

    solicitante = db.execute(
        '''SELECT s.metodo_pago, s.mp_card_token, u.email
           FROM solicitantes s
           JOIN usuarios u ON u.id = s.usuario_id
           WHERE s.id=?''',
        (fid,)
    ).fetchone()

    monto_total = float(round((pago['monto_bruto'] or 0) + (pago['comision_solicitante'] or 0), 2))

    # Pago directo con tarjeta guardada
    if (access_token and solicitante and
            solicitante['metodo_pago'] == 'tarjeta' and solicitante['mp_card_token']):
        try:
            import mercadopago
            sdk = mercadopago.SDK(access_token)
            payment_data = {
                "transaction_amount": monto_total,
                "token": solicitante['mp_card_token'],
                "description": f"Servicio AMPARO #{sid}",
                "installments": 1,
                "payment_method_id": "visa",
                "payer": {"email": solicitante['email']}
            }
            resp = sdk.payment().create(payment_data)
            result = resp.get("response", {})
            status = result.get("status")
            if status == "approved":
                ref = str(result.get("id", ""))
                _procesar_pago(db, pago, s, metodo='tarjeta_mp', referencia=ref)
                db.commit()
                flash('✅ Pago aprobado con tu tarjeta guardada.', 'success')
                return redirect(url_for('solicitante.contratacion_detalle', sid=sid, calificar=1))
            elif status in ("in_process", "pending"):
                flash('El pago está siendo procesado. Te avisaremos cuando se confirme.', 'info')
                return redirect(url_for('solicitante.contratacion_detalle', sid=sid))
            else:
                detail = result.get("status_detail", "")
                flash(f'El pago fue rechazado ({detail}). Verificá tu tarjeta o cambiá el método de pago.', 'error')
                return redirect(url_for('solicitante.contratacion_pagar', sid=sid))
        except Exception as e:
            flash(f'Error al procesar el pago con tarjeta: {str(e)[:120]}', 'error')
            return redirect(url_for('solicitante.contratacion_pagar', sid=sid))

    # Checkout Pro (Mercado Pago redirect) para método MP o cuando no hay token
    if access_token:
        try:
            import mercadopago
            sdk = mercadopago.SDK(access_token)
            tipo  = pago['tipo_pago'] or 'servicio'
            title = (f"Servicio AMPARO - {s['prestador_nombre']}"
                     if tipo == 'servicio'
                     else f"Penalidad AMPARO - {s['prestador_nombre']}")
            base_url = request.host_url.rstrip('/')
            preference_data = {
                "items": [{
                    "title": title,
                    "quantity": 1,
                    "unit_price": monto_total,
                    "currency_id": "ARS",
                }],
                "back_urls": {
                    "success": f"{base_url}/solicitante/pago/mp/ok?pago_id={pago['id']}&sid={sid}",
                    "failure": f"{base_url}/solicitante/pago/mp/fallo?pago_id={pago['id']}&sid={sid}",
                    "pending": f"{base_url}/solicitante/pago/mp/pendiente?pago_id={pago['id']}&sid={sid}",
                },
                "auto_return": "approved",
                "notification_url": f"{base_url}/solicitante/pago/mp/webhook",
                "external_reference": str(pago['id']),
            }
            resp = sdk.preference().create(preference_data)
            pref = resp.get("response", {})
            modo = _cfg_db('mp_modo', 'sandbox')
            init_point = pref.get("init_point") if modo == 'produccion' else pref.get("sandbox_init_point")
            if init_point:
                return redirect(init_point)
            flash('No se pudo obtener el link de pago de Mercado Pago.', 'error')
        except Exception as e:
            flash(f'Error con Mercado Pago: {str(e)[:120]}', 'error')
        return redirect(url_for('solicitante.contratacion_pagar', sid=sid))

    # Sin credenciales MP: modo simulado
    _procesar_pago(db, pago, s, metodo='simulado', referencia='SIMULADO-TEST')
    db.commit()
    flash('✅ Pago procesado (modo simulado). En producción se usará Mercado Pago.', 'success')
    return redirect(url_for('solicitante.contratacion_detalle', sid=sid, calificar=1))


def _get_config(db, *claves):
    rows = db.execute(
        f"SELECT clave, valor FROM configuracion WHERE clave IN ({','.join('?'*len(claves))})",
        claves
    ).fetchall()
    return {r['clave']: r['valor'] for r in rows}


def _enviar_aviso_pago_prestador(db, pago, s):
    """Envía email al prestador avisando que el cobro fue procesado."""
    pr_row = db.execute(
        'SELECT u.nombre, u.email, p.metodo_cobro '
        'FROM prestadores p JOIN usuarios u ON u.id = p.usuario_id '
        'WHERE p.id = ?', (s['prestador_id'],)
    ).fetchone()
    if not pr_row:
        print(f"[EMAIL] Prestador no encontrado para servicio {s.get('id')}")
        return
    print(f"[EMAIL] Enviando notificación de pago a prestador: {pr_row['email']}")
    asunto = _cfg_db('mail_pago_liquidado_asunto', 'Tu cobro fue procesado — AMPARO')
    cuerpo = _cfg_db('mail_pago_liquidado_cuerpo',
        'Hola {nombre},\n\nEl cobro del servicio del {fecha_liquidacion} fue procesado correctamente.\n\n'
        'Monto a acreditar: $ {monto_neto}\n'
        'Método de cobro: {metodo_cobro}\n\n'
        'Podés ver el detalle en la app:\n{link_app}')
    cuerpo = (cuerpo
        .replace('{nombre}',           pr_row['nombre'])
        .replace('{monto_neto}',       f"{pago['monto_neto']:,.0f}")
        .replace('{metodo_cobro}',     pr_row['metodo_cobro'] or '—')
        .replace('{fecha_liquidacion}', str(s['fecha_servicio']))
        .replace('{link_app}',         _cfg_db('app_url', 'http://127.0.0.1:5000') + '/prestador/dashboard')
    )
    return enviar_email(pr_row['email'], asunto, cuerpo)


def _enviar_recibo_solicitante(db, pago, s):
    """Envía email de recibo al solicitante tras el pago."""
    sol_row = db.execute(
        '''SELECT u.nombre, u.email
           FROM solicitantes sol
           JOIN usuarios u ON u.id = sol.usuario_id
           WHERE sol.id = ?''',
        (pago['solicitante_id'],)
    ).fetchone()
    if not sol_row:
        print(f"[EMAIL] Solicitante no encontrado para pago {pago.get('id')}")
        return
    print(f"[EMAIL] Enviando recibo a solicitante: {sol_row['email']}")

    total_pag = (pago['monto_bruto'] or 0) + (pago['comision_monto'] or 0)
    asunto = _cfg_db('mail_recibo_pago_asunto', 'Recibo de pago — AMPARO')
    cuerpo = _cfg_db('mail_recibo_pago_cuerpo',
        'Hola {nombre},\n\nTe confirmamos el pago del siguiente servicio:\n\n'
        'Prestador: {prestador_nombre}\n'
        'Fecha: {fecha_servicio}\n'
        'Horario: {hora_inicio} a {hora_fin}\n\n'
        'Subtotal servicio: ${monto_servicio}\n'
        'Servicio de AMPARO: ${comision}\n'
        'Total pagado: ${total_pagado}')
    cuerpo = (cuerpo
        .replace('{nombre}', sol_row['nombre'])
        .replace('{prestador_nombre}', s.get('prestador_nombre') or '')
        .replace('{fecha_servicio}', str(s['fecha_servicio']))
        .replace('{hora_inicio}', str(s['hora_inicio']))
        .replace('{hora_fin}', str(s['hora_fin']))
        .replace('{monto_servicio}', f"{pago['monto_bruto']:,.0f}")
        .replace('{comision}', f"{pago['comision_monto']:,.0f}")
        .replace('{total_pagado}', f"{total_pag:,.0f}")
    )
    return enviar_email(sol_row['email'], asunto, cuerpo)


def _procesar_pago(db, pago, s, metodo, referencia):
    tipo = pago['tipo_pago'] or 'servicio'
    print(f"[PAGO] Iniciando _procesar_pago — pago_id={pago['id']} tipo={tipo} monto={pago['monto_bruto']} metodo={metodo}")

    if tipo == 'penalidad':
        sol_dbg = db.execute(
            'SELECT sol.metodo_pago, sol.mp_card_token, u.email '
            'FROM solicitantes sol JOIN usuarios u ON u.id=sol.usuario_id WHERE sol.id=?',
            (pago['solicitante_id'],)
        ).fetchone()
        if sol_dbg:
            print(f"[PENALIDAD] Solicitante: {sol_dbg['email']} | metodo_pago={sol_dbg['metodo_pago']} | token={'SÍ' if sol_dbg['mp_card_token'] else 'VACÍO'}")
        else:
            print(f"[PENALIDAD] ADVERTENCIA: no se encontró el solicitante id={pago['solicitante_id']}")

        mp_token = _cfg_db('mp_access_token', '').strip()
        if not mp_token:
            print(f"[PENALIDAD] Sin access token — cobro simulado")
            db.execute(
                """UPDATE pagos SET
                       estado = 'PROCESADO',
                       metodo_pago = 'automatico_sandbox',
                       referencia_pago = 'SANDBOX_PENALIDAD',
                       fecha_pago = datetime('now', '-3 hours')
                   WHERE id = ?""",
                (pago['id'],)
            )
            db.commit()
            return
        print(f"[PENALIDAD] Monto bruto={pago['monto_bruto']} neto={pago['monto_neto']}")

    # Obtener método de cobro del prestador
    pr_row = db.execute(
        'SELECT usuario_id, metodo_cobro FROM prestadores WHERE id=?', (s['prestador_id'],)
    ).fetchone()
    metodo_cobro_prestador = pr_row['metodo_cobro'] if pr_row else None

    ahora = ahora_argentina()
    db.execute(
        """UPDATE pagos SET estado='LIQUIDADO', metodo_pago=?,
           referencia_pago=?, fecha_pago=?, fecha_liquidacion=?, metodo_cobro_prestador=? WHERE id=?""",
        (metodo, referencia, ahora, ahora, metodo_cobro_prestador, pago['id'])
    )
    print(f"[PAGO] Pago {pago['id']} marcado LIQUIDADO — metodo={metodo}")

    # Recargar pago con datos actualizados para el recibo
    pago_actualizado = db.execute('SELECT * FROM pagos WHERE id=?', (pago['id'],)).fetchone()

    if pr_row:
        tipo_label = 'compensación por cancelación' if pago['tipo_pago'] == 'penalidad' else 'servicio'
        _notificar(db, pr_row['usuario_id'], 'pago_liquidado',
                   f'Tu pago de $ {pago["monto_neto"]:,.0f} fue acreditado',
                   f'El pago de tu {tipo_label} fue liquidado. '
                   f'$ {pago["monto_neto"]:.2f} fueron acreditados en tu cuenta.')
    # Notificar al solicitante
    sol_usuario = db.execute(
        'SELECT uf.id FROM solicitantes sol JOIN usuarios uf ON uf.id=sol.usuario_id WHERE sol.id=?',
        (pago['solicitante_id'],)
    ).fetchone()
    if sol_usuario:
        _notificar(db, sol_usuario['id'], 'pago_liquidado',
                   'Pago procesado y liquidado',
                   f'Tu pago de $ {pago["monto_bruto"]:.2f} fue procesado correctamente.')
        if pago.get('tipo_pago') != 'penalidad':
            _notificar(db, sol_usuario['id'], 'calificacion_pendiente',
                       'Calificá el servicio',
                       f'¿Cómo fue tu experiencia? Calificá al prestador por el servicio del {s["fecha_servicio"]}.')
    admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
    if admin:
        _notificar(db, admin['id'], 'pago_liquidado',
                   'Pago liquidado automáticamente',
                   f'Pago $ {pago["monto_bruto"]:.2f} — servicio #{pago["servicio_id"]} liquidado.')

    # Registrar movimiento financiero
    try:
        from routes.financiero import registrar_movimiento
        total_cobrado = (pago['monto_bruto'] or 0) + (pago['comision_monto'] or 0)
        if pago['tipo_pago'] == 'penalidad':
            registrar_movimiento(
                db, 'PENALIDAD',
                f"Penalidad cancelación — servicio #{pago['servicio_id']}",
                monto_entrada=total_cobrado,
                referencia=referencia,
                pago_id=pago['id']
            )
        else:
            sol_row = db.execute(
                'SELECT u.nombre, u.apellido FROM solicitantes sol '
                'JOIN usuarios u ON u.id=sol.usuario_id WHERE sol.id=?',
                (pago['solicitante_id'],)
            ).fetchone()
            sol_nombre = (f"{sol_row['nombre']} {sol_row['apellido']}"
                          if sol_row else f'solicitante #{pago["solicitante_id"]}')
            registrar_movimiento(
                db, 'COBRO',
                f"Cobro servicio #{pago['servicio_id']} — {sol_nombre}",
                monto_entrada=total_cobrado,
                referencia=referencia,
                pago_id=pago['id']
            )
    except Exception as e:
        print(f'[AMPARO] Error registrando movimiento financiero: {e}')

    # Enviar correos con desglose
    try:
        from routes.prestador import _enviar_correos_liquidacion
        _enviar_correos_liquidacion(db, pago['id'])
    except Exception as e:
        print(f"[CORREO] Error al enviar correos de liquidación: {e}")

    # Disbursement automático: transferir monto_neto al prestador vía MP
    try:
        from routes.financiero import disbursement_prestador
        mp_token = _cfg_db('mp_access_token', '').strip()
        if mp_token:
            ok, detalle = disbursement_prestador(db, pago['id'], mp_token)
            if ok:
                print(f'[DISBURSEMENT] OK pago={pago["id"]} transfer_id={detalle}')
                if pr_row:
                    _notificar(db, pr_row['usuario_id'], 'pago_liquidado',
                               f'Tu pago de $ {pago["monto_neto"]:,.0f} fue transferido',
                               f'Transferimos $ {pago["monto_neto"]:.2f} a tu cuenta. '
                               f'Referencia de transferencia: {detalle}.')
            else:
                print(f'[DISBURSEMENT] FALLIDO pago={pago["id"]} error={detalle}')
                if admin:
                    _notificar(db, admin['id'], 'disbursement_fallido',
                               f'⚠️ Fallo al pagar prestador — pago #{pago["id"]}',
                               f'No se pudo transferir $ {pago["monto_neto"]:.2f} al prestador. '
                               f'Error: {detalle}. Revisar en Admin › Pagos › #{pago["id"]}.')
        else:
            db.execute(
                "UPDATE pagos SET disbursement_estado='SIN_CREDENCIALES' WHERE id=?",
                (pago['id'],)
            )
            print(f'[DISBURSEMENT] Sin access token — disbursement omitido para pago {pago["id"]}')
    except Exception as e:
        print(f'[DISBURSEMENT] Error inesperado en pago {pago["id"]}: {e}')


@solicitante_bp.route('/pago/mp/ok')
def pago_mp_ok():
    db      = get_db()
    fid     = _get_solicitante_id(db)
    pago_id = request.args.get('pago_id', type=int)
    sid     = request.args.get('sid', type=int)
    mp_pid  = request.args.get('payment_id', '')

    if pago_id:
        pago = db.execute("SELECT * FROM pagos WHERE id=?", (pago_id,)).fetchone()
        if pago and pago['solicitante_id'] == fid and pago['estado'] == 'PENDIENTE':
            s = db.execute(
                """SELECT s.*, u.nombre || ' ' || u.apellido AS prestador_nombre
                   FROM servicios s
                   JOIN prestadores pr ON pr.id = s.prestador_id
                   JOIN usuarios u ON u.id = pr.usuario_id
                   WHERE s.id=?""", (pago['servicio_id'],)
            ).fetchone()
            if s:
                _procesar_pago(db, pago, s, 'mercadopago', mp_pid)
                db.commit()
    flash('✅ ¡Pago realizado correctamente! Gracias.', 'success')
    dest = url_for('solicitante.contratacion_detalle', sid=sid, calificar=1) if sid else url_for('solicitante.pagos')
    return redirect(dest)


@solicitante_bp.route('/pago/mp/pendiente')
def pago_mp_pendiente():
    sid = request.args.get('sid', type=int)
    flash('Tu pago está pendiente de acreditación. Te avisaremos cuando se confirme.', 'info')
    dest = url_for('solicitante.contratacion_detalle', sid=sid) if sid else url_for('solicitante.pagos')
    return redirect(dest)


@solicitante_bp.route('/pago/mp/fallo')
def pago_mp_fallo():
    sid = request.args.get('sid', type=int)
    flash('Hubo un problema con el pago. Podés intentarlo nuevamente.', 'error')
    dest = url_for('solicitante.contratacion_pagar', sid=sid) if sid else url_for('solicitante.pagos')
    return redirect(dest)


@solicitante_bp.route('/pago/mp/webhook', methods=['POST'])
def pago_mp_webhook():
    data = request.get_json(silent=True) or {}
    if data.get('type') == 'payment':
        mp_pid = str(data.get('data', {}).get('id', ''))
        if mp_pid:
            db   = get_db()
            pago = db.execute(
                "SELECT * FROM pagos WHERE referencia_pago=? OR token_externo=?",
                (mp_pid, mp_pid)
            ).fetchone()
            if pago and pago['estado'] == 'PENDIENTE':
                s = db.execute(
                    """SELECT s.*, u.nombre || ' ' || u.apellido AS prestador_nombre
                       FROM servicios s
                       JOIN prestadores pr ON pr.id = s.prestador_id
                       JOIN usuarios u ON u.id = pr.usuario_id
                       WHERE s.id=?""", (pago['servicio_id'],)
                ).fetchone()
                if s:
                    _procesar_pago(db, pago, s, 'mercadopago', mp_pid)
                    db.commit()
    return '', 200


@solicitante_bp.route('/servicios/<int:sid>/calificar', methods=['GET', 'POST'])
def calificar_servicio(sid):
    db  = get_db()
    fid = _get_solicitante_id(db)

    s = db.execute(
        '''SELECT s.*,
                  u.nombre || ' ' || u.apellido AS prestador_nombre,
                  pr.foto_url,
                  c.nombre AS categoria_nombre
           FROM servicios s
           JOIN prestadores pr ON pr.id = s.prestador_id
           JOIN usuarios u     ON u.id  = pr.usuario_id
           LEFT JOIN categorias c ON c.id = s.categoria_id
           WHERE s.id=? AND s.solicitante_id=? AND s.estado='FINALIZADO' ''',
        (sid, fid)
    ).fetchone()
    if not s:
        flash('Servicio no encontrado o no disponible para calificar.', 'error')
        return redirect(url_for('solicitante.dashboard'))

    ya = db.execute(
        'SELECT id FROM calificaciones WHERE servicio_id=?', (sid,)
    ).fetchone()
    if ya:
        flash('Ya calificaste este servicio.', 'info')
        return redirect(url_for('solicitante.contratacion_detalle', sid=sid))

    if request.method == 'POST':
        puntaje    = request.form.get('puntaje', type=int)
        comentario = request.form.get('comentario', '').strip() or None
        if not puntaje or not 1 <= puntaje <= 5:
            flash('Por favor seleccioná un puntaje entre 1 y 5.', 'error')
            return render_template('solicitante/calificar.html', s=s, **_ctx())

        db.execute(
            '''INSERT INTO calificaciones
               (servicio_id, solicitante_id, prestador_id, puntaje, comentario, fecha)
               VALUES (?,?,?,?,?,?)''',
            (sid, fid, s['prestador_id'], puntaje, comentario, ahora_argentina())
        )
        # Notificar al prestador
        pr_u = db.execute('SELECT usuario_id FROM prestadores WHERE id=?', (s['prestador_id'],)).fetchone()
        sol_u = db.execute('SELECT nombre, apellido FROM usuarios WHERE id=?', (session['usuario_id'],)).fetchone()
        sol_nombre = f"{sol_u['nombre']} {sol_u['apellido']}" if sol_u else 'Un solicitante'
        if pr_u:
            _notificar(db, pr_u['usuario_id'], 'nueva_calificacion',
                       'Recibiste una nueva calificación',
                       f'{sol_nombre} te calificó con {puntaje}★ por el servicio del {s["fecha_servicio"]}.')
        # Notificar al admin
        admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
        if admin:
            pr_nombre_row = db.execute(
                'SELECT u.nombre, u.apellido FROM prestadores p JOIN usuarios u ON u.id=p.usuario_id WHERE p.id=?',
                (s['prestador_id'],)
            ).fetchone()
            pr_nombre = f"{pr_nombre_row['nombre']} {pr_nombre_row['apellido']}" if pr_nombre_row else 'un prestador'
            _notificar(db, admin['id'], 'nueva_calificacion',
                       'Nueva calificación recibida',
                       f'{sol_nombre} calificó a {pr_nombre} con {puntaje}★.')
        db.commit()
        flash('¡Gracias por tu calificación!', 'success')
        return redirect(url_for('solicitante.dashboard'))

    return render_template('solicitante/calificar.html', s=s, **_ctx())


@solicitante_bp.route('/contrataciones/<int:sid>/calificar', methods=['POST'])
def contratacion_calificar(sid):
    db      = get_db()
    fid     = _get_solicitante_id(db)
    puntaje = request.form.get('puntaje', '').strip()
    comentario = request.form.get('comentario', '').strip() or None

    s = db.execute(
        "SELECT * FROM servicios WHERE id=? AND solicitante_id=? AND estado='FINALIZADO'",
        (sid, fid)
    ).fetchone()
    if not s:
        flash('Solo podés calificar servicios finalizados.', 'error')
        return redirect(url_for('solicitante.contrataciones', tab='historial'))

    ya_calificado = db.execute(
        'SELECT id FROM calificaciones WHERE servicio_id=? AND solicitante_id=?',
        (sid, fid)
    ).fetchone()
    if ya_calificado:
        flash('Ya calificaste este servicio.', 'error')
        return redirect(url_for('solicitante.contratacion_detalle', sid=sid))

    try:
        puntaje_int = int(puntaje)
        if not 1 <= puntaje_int <= 5:
            raise ValueError
    except (ValueError, TypeError):
        flash('El puntaje debe ser un número entre 1 y 5.', 'error')
        return redirect(url_for('solicitante.contratacion_detalle', sid=sid))

    db.execute(
        '''INSERT INTO calificaciones
           (servicio_id, solicitante_id, prestador_id, puntaje, comentario, fecha)
           VALUES (?,?,?,?,?,?)''',
        (sid, fid, s['prestador_id'], puntaje_int, comentario, ahora_argentina())
    )

    # Notificar al prestador
    pr_usuario = db.execute(
        'SELECT usuario_id FROM prestadores WHERE id=?', (s['prestador_id'],)
    ).fetchone()
    sol_usuario = db.execute(
        'SELECT nombre, apellido FROM usuarios WHERE id=?', (session['usuario_id'],)
    ).fetchone()
    sol_nombre = f"{sol_usuario['nombre']} {sol_usuario['apellido']}" if sol_usuario else 'Un solicitante'
    if pr_usuario:
        _notificar(db, pr_usuario['usuario_id'], 'nueva_calificacion',
                   'Recibiste una nueva calificación',
                   f'{sol_nombre} te calificó con {puntaje_int}★ por el servicio del {s["fecha_servicio"]}.')
    # Notificar al admin
    pr_nombre_row = db.execute(
        'SELECT u.nombre, u.apellido FROM prestadores p JOIN usuarios u ON u.id=p.usuario_id WHERE p.id=?',
        (s['prestador_id'],)
    ).fetchone()
    pr_nombre = f"{pr_nombre_row['nombre']} {pr_nombre_row['apellido']}" if pr_nombre_row else 'un prestador'
    admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
    if admin:
        _notificar(db, admin['id'], 'nueva_calificacion',
                   'Nueva calificación recibida',
                   f'{sol_nombre} calificó a {pr_nombre} con {puntaje_int}★.')
    db.commit()
    flash('¡Calificación enviada! Gracias por tu opinión.', 'success')
    return redirect(url_for('solicitante.contratacion_detalle', sid=sid))


# ─── CONFIRMACIÓN DE SERVICIO ─────────────────────────────────────────────────

def _cobrar_tarjeta_automatico(db, pago_id, s, fid):
    """
    Cobra automáticamente la tarjeta registrada del solicitante vía MP.
    Si el cobro es exitoso llama a _procesar_pago() que marca LIQUIDADO y
    ejecuta el disbursement al prestador.
    Si falla, deja el pago en PENDIENTE y notifica al admin.
    """
    pago = db.execute('SELECT * FROM pagos WHERE id=?', (pago_id,)).fetchone()
    if not pago:
        print(f'[COBRO_AUTO] Pago {pago_id} no encontrado')
        return

    sol = db.execute(
        'SELECT sol.mp_card_token, sol.mp_card_payment_method, sol.mp_customer_id, sol.mp_card_id, u.email '
        'FROM solicitantes sol JOIN usuarios u ON u.id=sol.usuario_id WHERE sol.id=?',
        (fid,)
    ).fetchone()

    access_token = _cfg_db('mp_access_token', '').strip()

    tiene_tarjeta = sol and (sol['mp_card_id'] or sol['mp_card_token'])
    if not access_token or not tiene_tarjeta:
        motivo = 'Sin credenciales MP' if not access_token else 'El solicitante no tiene tarjeta registrada'
        print(f'[COBRO_AUTO] No se puede cobrar automáticamente — {motivo}')
        admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
        if admin:
            _notificar(db, admin['id'], 'cobro_fallido',
                       f'⚠️ No se pudo cobrar automáticamente — pago #{pago_id}',
                       f'Servicio #{s["id"]} finalizado pero el cobro automático no pudo ejecutarse: {motivo}. '
                       f'Revisar en Admin › Pagos › #{pago_id}.')
        db.commit()
        return

    monto_total = round((pago['monto_bruto'] or 0) + (pago['comision_solicitante'] or 0), 2)
    pm_raw = sol['mp_card_payment_method'] or ''
    payment_method = pm_raw if pm_raw and pm_raw != 'undefined' else 'visa'

    try:
        import mercadopago, requests as _req
        sdk = mercadopago.SDK(access_token)

        # Obtener token de cobro: desde card guardada (Customers API) o token directo
        charge_token = None
        customer_id  = sol['mp_customer_id']
        card_id      = sol['mp_card_id']
        if customer_id and card_id:
            tk_resp = _req.post(
                'https://api.mercadopago.com/v1/card_tokens',
                json={'customer_id': customer_id, 'card_id': card_id},
                headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
                timeout=15
            )
            if tk_resp.status_code == 200:
                charge_token = tk_resp.json().get('id')
                print(f'[COBRO_AUTO] Token desde Customers API OK: {charge_token[:10]}...')
            else:
                print(f'[COBRO_AUTO] Error generando token desde Customers API: {tk_resp.status_code} {tk_resp.text[:200]}')
        if not charge_token:
            charge_token = sol['mp_card_token']
            print(f'[COBRO_AUTO] Usando token directo (fallback)')

        payment_data = {
            'transaction_amount': monto_total,
            'token': charge_token,
            'description': f'Servicio AMPARO #{s["id"]}',
            'installments': 1,
            'payment_method_id': payment_method,
            'payer': {'email': sol['email']},
        }
        print(f'[COBRO_AUTO] Intentando cobrar ${monto_total} con {payment_method} al solicitante {sol["email"]}')
        resp   = sdk.payment().create(payment_data)
        result = resp.get('response', {})
        status = result.get('status')
        mp_pid = str(result.get('id', ''))
        print(f'[COBRO_AUTO] Respuesta MP completa: {resp}')
        print(f'[COBRO_AUTO] Respuesta MP: status={status} id={mp_pid} detail={result.get("status_detail")}')

        if status == 'approved':
            _procesar_pago(db, pago, s, metodo='tarjeta_mp', referencia=mp_pid)
            db.commit()
        else:
            detalle = result.get('status_detail', status or 'error desconocido')
            db.execute(
                "UPDATE pagos SET referencia_pago=? WHERE id=?",
                (mp_pid or 'RECHAZADO', pago_id)
            )
            admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
            if admin:
                _notificar(db, admin['id'], 'cobro_fallido',
                           f'⚠️ Cobro rechazado — pago #{pago_id}',
                           f'El cobro automático del servicio #{s["id"]} fue rechazado por MP: {detalle}. '
                           f'Revisar en Admin › Pagos › #{pago_id}.')
            sol_uid = db.execute(
                'SELECT id FROM usuarios WHERE id=(SELECT usuario_id FROM solicitantes WHERE id=?)', (fid,)
            ).fetchone()
            if sol_uid:
                _notificar(db, sol_uid['id'], 'cobro_fallido',
                           'El cobro de tu tarjeta fue rechazado',
                           f'No pudimos cobrar el servicio del {s["fecha_servicio"]}. '
                           f'Por favor, actualizá tu tarjeta en Mi Cuenta.')
            db.commit()
    except Exception as e:
        print(f'[COBRO_AUTO] Error inesperado: {e}')
        admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
        if admin:
            _notificar(db, admin['id'], 'cobro_fallido',
                       f'⚠️ Error en cobro automático — pago #{pago_id}',
                       f'Error técnico al intentar cobrar servicio #{s["id"]}: {str(e)[:200]}.')
        db.commit()


def _crear_pago_por_servicio(db, s, fid):
    """Crea el registro de pago al finalizar un servicio."""
    cfg = {r['clave']: r['valor'] for r in db.execute(
        "SELECT clave, valor FROM configuracion "
        "WHERE clave IN ('comision_solicitante_pct','comision_prestador_pct')"
    ).fetchall()}
    try:
        horas = _calcular_horas(s['hora_inicio'], s['hora_fin'])
    except Exception:
        horas = 0
    tarifa_hora = s['tarifa_hora'] or 0
    monto_bruto = round(tarifa_hora * horas, 2) if (tarifa_hora and horas) else (s['monto_estimado'] or 0)
    sol_pct  = float(cfg.get('comision_solicitante_pct', 15))
    pres_pct = float(cfg.get('comision_prestador_pct', 7))
    comision_solicitante = round(monto_bruto * sol_pct  / 100, 2)
    comision_prestador   = round(monto_bruto * pres_pct / 100, 2)
    comision_monto       = round(comision_solicitante + comision_prestador, 2)
    comision_pct         = 0
    monto_neto           = round(monto_bruto - comision_prestador, 2)
    cur = db.execute(
        """INSERT INTO pagos
           (servicio_id, solicitante_id, prestador_id, tipo_pago,
            monto_bruto, comision_pct, comision_monto,
            comision_solicitante, comision_prestador,
            monto_neto, estado)
           VALUES (?,?,?,'servicio',?,?,?,?,?,?,'PENDIENTE')""",
        (s['id'], fid, s['prestador_id'],
         monto_bruto, comision_pct, comision_monto,
         comision_solicitante, comision_prestador, monto_neto)
    )
    return monto_bruto, cur.lastrowid


@solicitante_bp.route('/contrataciones/<int:sid>/confirmar-fin', methods=['POST'])
def contratacion_confirmar_fin(sid):
    db  = get_db()
    fid = _get_solicitante_id(db)

    s = db.execute(
        """SELECT s.* FROM servicios s
           WHERE s.id=? AND s.solicitante_id=? AND s.estado IN ('ACEPTADO','ACTIVO')
             AND s.prestador_confirmo_fin=1 AND s.solicitante_confirmo_fin=0""",
        (sid, fid)
    ).fetchone()
    if not s:
        flash('No se puede confirmar este servicio ahora.', 'error')
        return redirect(url_for('solicitante.contratacion_detalle', sid=sid))

    ahora = ahora_argentina()
    db.execute(
        """UPDATE servicios SET estado='FINALIZADO',
           solicitante_confirmo_fin=1, fecha_confirmacion_solicitante=?,
           fecha_finalizacion=? WHERE id=?""",
        (ahora, ahora, sid)
    )
    monto, pago_id = _crear_pago_por_servicio(db, s, fid)
    db.commit()

    # Cobro automático a la tarjeta registrada del solicitante
    _cobrar_tarjeta_automatico(db, pago_id, s, fid)

    flash('✅ Servicio confirmado. El cobro fue procesado automáticamente.', 'success')
    return redirect(url_for('solicitante.contrataciones', tab='historial'))


@solicitante_bp.route('/contrataciones/<int:sid>/reportar-conflicto', methods=['POST'])
def contratacion_reportar_conflicto(sid):
    db     = get_db()
    fid    = _get_solicitante_id(db)
    motivo = request.form.get('motivo_conflicto', '').strip()

    if not motivo:
        flash('El motivo del problema es obligatorio.', 'error')
        return redirect(url_for('solicitante.contratacion_detalle', sid=sid))

    s = db.execute(
        "SELECT * FROM servicios WHERE id=? AND solicitante_id=? AND estado='ACTIVO'",
        (sid, fid)
    ).fetchone()
    if not s:
        flash('No se puede reportar un problema en este servicio.', 'error')
        return redirect(url_for('solicitante.contrataciones'))

    db.execute(
        "UPDATE servicios SET conflicto=1, motivo_conflicto=? WHERE id=?",
        (motivo, sid)
    )
    admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
    if admin:
        _notificar(db, admin['id'], 'conflicto',
                   f'⚠️ CONFLICTO en servicio #{sid}',
                   f'El solicitante reportó un problema. Motivo: {motivo}')
    db.commit()
    flash('Recibimos tu reporte. El equipo de AMPARO lo revisará y te contactará a la brevedad.', 'success')
    return redirect(url_for('solicitante.contratacion_detalle', sid=sid))


# ─── PAGOS ────────────────────────────────────────────────────────────────────

@solicitante_bp.route('/pagos')
def pagos():
    db   = get_db()
    tab  = request.args.get('tab', 'historial')
    page = max(1, int(request.args.get('page', 1)))
    PER_PAGE = 10

    # Obtener el id de la tabla solicitantes a partir del usuario en sesión
    sol_row = db.execute(
        'SELECT id FROM solicitantes WHERE usuario_id=?', (session['usuario_id'],)
    ).fetchone()

    if not sol_row:
        return render_template('solicitante/pagos.html',
                               tab=tab, rows=[], reclamos=[],
                               total_mes=0, page=1, total_pages=1,
                               servicios_finalizados=[],
                               **_ctx())

    fid = sol_row['id']
    hoy = date.today()

    total_mes = db.execute(
        '''SELECT COALESCE(SUM(monto_bruto), 0) as s FROM pagos
           WHERE solicitante_id=? AND estado IN ('PROCESADO','LIQUIDADO')
             AND strftime('%Y-%m', fecha_pago) = ?''',
        (fid, hoy.strftime('%Y-%m'))
    ).fetchone()['s']

    if tab == 'historial':
        total = db.execute(
            "SELECT COUNT(*) as c FROM pagos WHERE solicitante_id=?", (fid,)
        ).fetchone()['c']
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        offset = (page - 1) * PER_PAGE
        rows = db.execute(
            '''SELECT p.*,
                      u.nombre || ' ' || u.apellido AS prestador_nombre
               FROM pagos p
               JOIN prestadores pr ON pr.id = p.prestador_id
               JOIN usuarios u ON u.id = pr.usuario_id
               WHERE p.solicitante_id=?
               ORDER BY p.fecha_pago DESC LIMIT ? OFFSET ?''',
            (fid, PER_PAGE, offset)
        ).fetchall()
        reclamos = []

    else:  # reclamos
        rows = []
        total_pages = 1
        reclamos = db.execute(
            '''SELECT r.*,
                      s.fecha_servicio,
                      u.nombre || ' ' || u.apellido AS prestador_nombre
               FROM reclamos r
               JOIN servicios s ON s.id = r.servicio_id
               JOIN prestadores pr ON pr.id = s.prestador_id
               JOIN usuarios u ON u.id = pr.usuario_id
               WHERE s.solicitante_id=?
               ORDER BY r.fecha_apertura DESC''',
            (fid,)
        ).fetchall()

    # Servicios FINALIZADOS para el formulario de reclamo
    servicios_finalizados = db.execute(
        '''SELECT s.id, s.fecha_servicio,
                  u.nombre || ' ' || u.apellido AS prestador_nombre
           FROM servicios s
           JOIN prestadores pr ON pr.id = s.prestador_id
           JOIN usuarios u ON u.id = pr.usuario_id
           WHERE s.solicitante_id=? AND s.estado='FINALIZADO'
           ORDER BY s.fecha_servicio DESC''',
        (fid,)
    ).fetchall()

    return render_template('solicitante/pagos.html',
                           tab=tab, rows=rows,
                           reclamos=reclamos,
                           total_mes=round(total_mes, 2),
                           page=page, total_pages=total_pages,
                           servicios_finalizados=servicios_finalizados,
                           **_ctx())


@solicitante_bp.route('/pagos/reclamo/nuevo', methods=['POST'])
def reclamo_nuevo():
    db          = get_db()
    fid         = _get_solicitante_id(db)
    servicio_id = request.form.get('servicio_id', '').strip()
    descripcion = request.form.get('descripcion', '').strip()

    if not servicio_id or not descripcion:
        flash('Completá todos los campos del reclamo.', 'error')
        return redirect(url_for('solicitante.pagos', tab='reclamos'))

    # Verificar que el servicio pertenece a esta familia y está FINALIZADO
    s = db.execute(
        "SELECT id FROM servicios WHERE id=? AND solicitante_id=? AND estado='FINALIZADO'",
        (servicio_id, fid)
    ).fetchone()
    if not s:
        flash('Solo podés reclamar sobre servicios finalizados.', 'error')
        return redirect(url_for('solicitante.pagos', tab='reclamos'))

    # Verificar que no exista ya un reclamo abierto para este servicio
    existente = db.execute(
        "SELECT id FROM reclamos WHERE servicio_id=? AND estado != 'CERRADO'",
        (servicio_id,)
    ).fetchone()
    if existente:
        flash('Ya existe un reclamo abierto para este servicio.', 'error')
        return redirect(url_for('solicitante.pagos', tab='reclamos'))

    db.execute(
        '''INSERT INTO reclamos (servicio_id, iniciado_por, descripcion, estado, fecha_apertura)
           VALUES (?,?,?,'ABIERTO',?)''',
        (servicio_id, session['usuario_id'], descripcion, ahora_argentina())
    )

    # Notificar al admin (usuario_id con tipo='admin')
    admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
    if admin:
        _notificar(db, admin['id'], 'nuevo_reclamo',
                   'Nuevo reclamo recibido',
                   f'Una familia presentó un reclamo sobre el servicio #{servicio_id}.')
    db.commit()
    flash('Reclamo enviado. Te notificaremos cuando sea revisado.', 'success')
    return redirect(url_for('solicitante.pagos', tab='reclamos'))


# ─── MI CUENTA ────────────────────────────────────────────────────────────────

@solicitante_bp.route('/mi_cuenta')
def mi_cuenta():
    db  = get_db()
    fid = _get_solicitante_id(db)

    datos = db.execute(
        '''SELECT f.*, u.nombre, u.apellido, u.email, u.telefono,
                  z.nombre AS zona_nombre
           FROM solicitantes f
           JOIN usuarios u ON u.id = f.usuario_id
           LEFT JOIN zonas z ON z.id = f.zona_id
           WHERE f.id=?''',
        (fid,)
    ).fetchone()

    mp_public_key = _cfg_db('mp_public_key', '')

    return render_template('solicitante/mi_cuenta.html',
                           datos=datos, mp_public_key=mp_public_key, **_ctx())


@solicitante_bp.route('/mi_cuenta/metodo_pago', methods=['POST'])
def mi_cuenta_metodo_pago():
    db  = get_db()
    fid = _get_solicitante_id(db)

    metodo_pago    = request.form.get('metodo_pago', '').strip()
    email_mp       = request.form.get('email_mp', '').strip() or None
    card_token     = request.form.get('card_token', '').strip() or None
    card_last_four = request.form.get('card_last_four', '').strip() or None
    card_type      = request.form.get('card_type', '').strip() or None

    if metodo_pago not in ('mercadopago', 'tarjeta'):
        flash('Método de pago no válido.', 'error')
        return redirect(url_for('solicitante.mi_cuenta'))

    if metodo_pago == 'mercadopago':
        if not email_mp:
            flash('Ingresá el email de tu cuenta de Mercado Pago.', 'error')
            return redirect(url_for('solicitante.mi_cuenta'))
        desc = f'Mercado Pago — {email_mp}'
        db.execute(
            '''UPDATE solicitantes
               SET metodo_pago=?, metodo_pago_descripcion=?, mp_card_token=NULL
               WHERE id=?''',
            (metodo_pago, desc, fid)
        )
    else:
        if not card_token:
            flash('Los datos de tarjeta no pudieron verificarse. Intentá de nuevo.', 'error')
            return redirect(url_for('solicitante.mi_cuenta'))
        if card_last_four and card_type:
            desc = f'{card_type.upper()} terminada en {card_last_four}'
        else:
            desc = 'Tarjeta registrada'

        # Crear cliente y card permanente en MP (Customers API)
        mp_customer_id = None
        mp_card_id = None
        access_token = _cfg_db('mp_access_token', '').strip()
        if access_token:
            try:
                import mercadopago, requests as _req
                sdk = mercadopago.SDK(access_token)
                sol_user = db.execute(
                    'SELECT u.email FROM usuarios u JOIN solicitantes s ON s.usuario_id=u.id WHERE s.id=?',
                    (fid,)
                ).fetchone()
                email_sol = sol_user['email'] if sol_user else None
                if email_sol:
                    search = sdk.customer().search({'filters': {'email': email_sol}})
                    results = search.get('response', {}).get('results', [])
                    if results:
                        mp_customer_id = results[0]['id']
                    else:
                        new_cust = sdk.customer().create({'email': email_sol})
                        mp_customer_id = new_cust.get('response', {}).get('id')
                    if mp_customer_id:
                        card_resp = sdk.card().create(mp_customer_id, {'token': card_token})
                        mp_card_id = card_resp.get('response', {}).get('id')
                        print(f'[MP_CUSTOMER] customer={mp_customer_id} card={mp_card_id}')
            except Exception as e:
                print(f'[MP_CUSTOMER] Error: {e}')

        db.execute(
            '''UPDATE solicitantes
               SET metodo_pago=?, metodo_pago_descripcion=?, mp_card_token=?,
                   mp_card_payment_method=?, mp_customer_id=?, mp_card_id=?
               WHERE id=?''',
            (metodo_pago, desc, card_token, card_type, mp_customer_id, mp_card_id, fid)
        )

    db.commit()
    flash('Método de pago actualizado correctamente.', 'success')
    return redirect(url_for('solicitante.mi_cuenta'))


@solicitante_bp.route('/mi_cuenta/editar', methods=['GET', 'POST'])
def mi_cuenta_editar():
    db  = get_db()
    fid = _get_solicitante_id(db)

    datos = db.execute(
        '''SELECT f.*, u.nombre, u.apellido, u.email, u.telefono
           FROM solicitantes f
           JOIN usuarios u ON u.id = f.usuario_id
           WHERE f.id=?''',
        (fid,)
    ).fetchone()

    if request.method == 'POST':
        nombre        = request.form.get('nombre', '').strip()
        apellido      = request.form.get('apellido', '').strip()
        telefono      = request.form.get('telefono', '').strip() or None
        direccion     = request.form.get('direccion', '').strip() or None
        fam_nombre    = request.form.get('familiar_nombre', '').strip() or None
        fam_edad      = request.form.get('familiar_edad', '').strip() or None
        fam_cond      = request.form.get('familiar_condicion', '').strip() or None
        fam_nec       = request.form.get('familiar_necesidades', '').strip() or None
        # GPS
        latitud       = request.form.get('latitud', '').strip() or None
        longitud      = request.form.get('longitud', '').strip() or None
        codigo_postal = request.form.get('codigo_postal', '').strip() or None
        localidad     = request.form.get('localidad', '').strip() or None
        provincia     = request.form.get('provincia', '').strip() or None

        if not nombre or not apellido:
            flash('El nombre y apellido son obligatorios.', 'error')
        else:
            ub_dt = datetime.now().isoformat() if (latitud or codigo_postal) else datos['ubicacion_actualizada']
            db.execute(
                'UPDATE usuarios SET nombre=?, apellido=?, telefono=? WHERE id=?',
                (nombre, apellido, telefono, session['usuario_id'])
            )
            db.execute(
                '''UPDATE solicitantes SET direccion=?,
                   familiar_nombre=?, familiar_edad=?,
                   familiar_condicion=?, familiar_necesidades=?,
                   latitud=?, longitud=?, codigo_postal=?, localidad=?, provincia=?,
                   ubicacion_actualizada=?
                   WHERE id=?''',
                (direccion, fam_nombre, fam_edad, fam_cond, fam_nec,
                 latitud, longitud, codigo_postal, localidad, provincia,
                 ub_dt, fid)
            )
            admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
            if admin:
                _notificar(db, admin['id'], 'MODIFICACION',
                           f'Solicitante actualizó su perfil: {nombre} {apellido}',
                           f'{nombre} {apellido} modificó datos de su perfil.')
            db.commit()
            session['nombre']   = nombre
            session['apellido'] = apellido
            flash('Datos actualizados correctamente.', 'success')
            return redirect(url_for('solicitante.mi_cuenta'))

    return render_template('solicitante/mi_cuenta_editar.html',
                           datos=datos, **_ctx())


# ─── NOTIFICACIONES ───────────────────────────────────────────────────────────

@solicitante_bp.route('/contacto', methods=['GET', 'POST'])
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
            return render_template('solicitante/contacto.html',
                                   tipo_preseleccionado=tipo_contacto,
                                   mis_contactos=mis_contactos,
                                   **_ctx())

        db.execute(
            """INSERT INTO contactos (usuario_id, tipo_usuario, tipo_contacto, asunto, descripcion)
               VALUES (?, 'solicitante', ?, ?, ?)""",
            (uid, tipo_contacto, asunto, descripcion)
        )
        admin = db.execute("SELECT id FROM usuarios WHERE tipo_usuario='admin' LIMIT 1").fetchone()
        if admin:
            tipos_label = {'problema_tecnico': 'Problema técnico', 'reclamo': 'Reclamo', 'sugerencia': 'Sugerencia'}
            nombre_completo = f"{session.get('nombre', '')} {session.get('apellido', '')}"
            _notificar(db, admin['id'], 'contacto',
                       f"Nuevo {tipos_label.get(tipo_contacto, tipo_contacto)}: {asunto} — de {nombre_completo}")
        db.commit()
        return redirect(url_for('solicitante.contacto_enviado'))

    tipo_pre = request.args.get('tipo', '')
    mis_contactos = db.execute(
        "SELECT * FROM contactos WHERE usuario_id=? ORDER BY fecha_envio DESC",
        (uid,)
    ).fetchall()
    return render_template('solicitante/contacto.html',
                           tipo_preseleccionado=tipo_pre,
                           mis_contactos=mis_contactos,
                           **_ctx())


@solicitante_bp.route('/contacto/enviado')
def contacto_enviado():
    return render_template('solicitante/contacto_enviado.html', **_ctx())


@solicitante_bp.route('/contacto/<int:cid>')
def contacto_detalle(cid):
    db  = get_db()
    uid = session['usuario_id']
    c = db.execute(
        "SELECT * FROM contactos WHERE id=? AND usuario_id=?", (cid, uid)
    ).fetchone()
    if not c:
        flash('Mensaje no encontrado.', 'error')
        return redirect(url_for('solicitante.contacto'))
    return render_template('solicitante/contacto_detalle.html', c=c, **_ctx())


@solicitante_bp.route('/notificaciones')
def notificaciones():
    db = get_db()
    notifs = db.execute(
        'SELECT * FROM notificaciones WHERE usuario_id=? ORDER BY fecha DESC',
        (session['usuario_id'],)
    ).fetchall()
    db.execute(
        'UPDATE notificaciones SET leida=1 WHERE usuario_id=?',
        (session['usuario_id'],)
    )
    db.commit()
    return render_template('solicitante/notificaciones.html',
                           notifs=notifs,
                           nombre=session.get('nombre', ''),
                           apellido=session.get('apellido', ''),
                           notif_count=0)
