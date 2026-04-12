"""
Restaura las redacciones de correos en la tabla configuracion.
Ejecutar UNA VEZ después de recrear la base de datos:
    .venv\Scripts\python.exe restaurar_correos.py
"""
import sqlite3

CORREOS = [
    ('mail_bienvenida_asunto', '¡Bienvenido/a a AMPARO! Tu cuenta está lista'),
    ('mail_bienvenida_cuerpo', """Hola {nombre},

Es un placer tenerte con nosotros. Tu registro en AMPARO fue completado exitosamente y tu cuenta ya está activa.

Encontrar el cuidado profesional que tu familiar necesita ahora es simple, seguro y confiable.

Para comenzar seguí estos pasos:

1. Ingresá a AMPARO con tu email y contraseña.
2. Completá los datos de tu familiar a cuidar en Mi Cuenta.
3. Buscá un prestador por categoría y zona.
4. Revisá los perfiles, calificaciones y tarifas.
5. Enviá tu solicitud y coordiná el servicio.

Todos los prestadores de AMPARO tienen identidad, antecedentes penales y formación verificados. Los que tienen el distintivo ✅ AMPARO Verificado cuentan con los tres documentos aprobados.

Para ingresar hacé click aquí: {link_app}

AMPARO te da la bienvenida y te desea los mejores éxitos en esta nueva etapa.

El equipo de AMPARO"""),

    ('mail_desbloqueo_asunto', 'Tu cuenta de AMPARO fue desbloqueada'),
    ('mail_desbloqueo_cuerpo', """Hola {nombre},

Tu cuenta fue desbloqueada exitosamente. Ya podés ingresar a AMPARO con tu email y contraseña habitual.

Recordá que tu cuenta se bloquea automáticamente después de 3 intentos fallidos de ingreso. Si no recordás tu contraseña podés solicitar una nueva desde la pantalla de login.

Para ingresar hacé click aquí: {link_app}

El equipo de AMPARO"""),

    ('mail_vencimiento_asunto', 'Tu contraseña de AMPARO vence en {dias_restantes} días'),
    ('mail_vencimiento_cuerpo', """Hola {nombre},

Te avisamos que tu contraseña de AMPARO vence el {fecha_vencimiento}.

Para evitar que tu cuenta quede bloqueada te recomendamos cambiarla antes de esa fecha. Podés hacerlo ingresando a la app y yendo a Mi Cuenta.

Recordá que tu nueva contraseña debe tener al menos 8 caracteres, una mayúscula y un carácter especial.

Para ingresar y cambiar tu contraseña hacé click aquí: {link_app}

El equipo de AMPARO"""),

    ('mail_perfil_aprobado_asunto', '¡Bienvenido/a a AMPARO Red! Tu perfil fue aprobado'),
    ('mail_perfil_aprobado_cuerpo', """Hola {nombre},

¡Excelentes noticias! Tu perfil fue verificado y aprobado por el equipo de AMPARO. A partir de ahora aparecés en las búsquedas y podés empezar a recibir solicitudes de servicio.

¿Qué sigue?

1. Ingresá a AMPARO Red y revisá tu perfil público.
2. Asegurate de tener tu disponibilidad horaria actualizada.
3. Cuando recibas una solicitud tenés 24 horas para aceptarla o rechazarla.

Para ingresar hacé click aquí: {link_app}

AMPARO te da la bienvenida y te desea los mejores éxitos en esta nueva etapa.

El equipo de AMPARO"""),

    ('mail_perfil_rechazado_asunto', 'Revisión de tu documentación en AMPARO Red'),
    ('mail_perfil_rechazado_cuerpo', """Hola {nombre},

Revisamos tu documentación y encontramos un inconveniente que necesita tu atención.

Motivo: {motivo_rechazo}

Por favor ingresá a la app, corregí o volvé a subir la documentación indicada y aguardá una nueva revisión.

Para ingresar hacé click aquí: {link_app}

El equipo de AMPARO"""),

    ('mail_registro_prestador_asunto', 'Recibimos tu registro en AMPARO Red'),
    ('mail_registro_prestador_cuerpo', """Hola {nombre},

Recibimos tu registro en AMPARO Red. Estamos revisando tu documentación y te notificaremos cuando tu perfil esté aprobado.

El tiempo de verificación depende del plazo que hayas elegido para obtener tu certificado de antecedentes penales. Una vez que nos llegue toda tu documentación, procesamos tu aprobación a la brevedad.

Mientras tanto podés ingresar a la app para completar o corregir cualquier dato de tu perfil.

Para ingresar hacé click aquí: {link_app}

El equipo de AMPARO"""),

    ('mail_recibo_pago_asunto', 'Recibo de pago — Servicio AMPARO del {fecha_servicio}'),
    ('mail_recibo_pago_cuerpo', """Hola {nombre},

Te confirmamos el pago del siguiente servicio:

Prestador: {prestador_nombre}
Fecha: {fecha_servicio}
Horario: {hora_inicio} a {hora_fin}

Detalle del cobro:
Subtotal del servicio: $ {monto_servicio}
Comisión AMPARO: $ {comision}
Total cobrado: $ {total_pagado}

Gracias por confiar en AMPARO.

El equipo de AMPARO"""),

    ('mail_pago_liquidado_asunto', 'Tu pago fue acreditado — AMPARO'),
    ('mail_pago_liquidado_cuerpo', """Hola {nombre},

Te informamos que tu pago fue procesado y acreditado en tu cuenta.

Detalle de la liquidación:
Monto acreditado: $ {monto_neto}
Método de acreditación: {metodo_cobro}
Fecha de acreditación: {fecha_liquidacion}

Si tenés alguna consulta sobre este pago no dudes en contactarnos.

Para ingresar a tu cuenta hacé click aquí: {link_app}

El equipo de AMPARO"""),

    ('mail_cancelacion_sin_penalidad_asunto', 'Servicio cancelado — AMPARO'),
    ('mail_cancelacion_sin_penalidad_cuerpo', """Hola {nombre},

Te informamos que el siguiente servicio fue cancelado:

Prestador: {prestador_nombre}
Fecha: {fecha_servicio}
Horario: {hora_inicio} a {hora_fin}

La cancelación se realizó antes de que el prestador aceptara la solicitud, por lo que no se aplicó ningún cargo.

Podés buscar otro prestador disponible ingresando a la app.

Para ingresar hacé click aquí: {link_app}

El equipo de AMPARO"""),

    ('mail_cancelacion_con_penalidad_asunto', 'Servicio cancelado con penalidad — AMPARO'),
    ('mail_cancelacion_con_penalidad_cuerpo', """Hola {nombre},

Te informamos que el siguiente servicio fue cancelado:

Prestador: {prestador_nombre}
Fecha: {fecha_servicio}
Horario: {hora_inicio} a {hora_fin}

Debido a que el prestador ya había aceptado tu solicitud, se aplicó una penalidad del 10% sobre el monto del servicio de acuerdo a los términos y condiciones de AMPARO.

Monto de la penalidad cobrada: $ {monto_penalidad}

Si tenés alguna consulta sobre este cobro no dudes en contactarnos.

Para ingresar a tu cuenta hacé click aquí: {link_app}

El equipo de AMPARO"""),

    ('mail_respuesta_contacto_asunto', 'Respuesta a tu mensaje — AMPARO'),
    ('mail_respuesta_contacto_cuerpo', """Hola {nombre},

Recibimos tu {tipo_contacto} con el asunto "{asunto_mensaje}" y queremos darte una respuesta.

{respuesta_admin}

Si necesitás más información o tenés alguna otra consulta no dudes en escribirnos nuevamente desde la app en la sección Contacto.

Para ingresar hacé click aquí: {link_app}

El equipo de AMPARO"""),

    ('mail_contrasena_temp_asunto', 'Tu nueva contraseña temporal de AMPARO'),
    ('mail_contrasena_temp_cuerpo', """Hola {nombre},

El administrador de AMPARO generó una contraseña temporal para tu cuenta.

Tu contraseña temporal es: {contrasena_temporal}

Al ingresar con esta contraseña el sistema te pedirá que la cambies por una nueva. Recordá que tu nueva contraseña debe tener al menos 8 caracteres, una mayúscula y un carácter especial.

Para ingresar hacé click aquí: {link_app}

Si no solicitaste este cambio contactate con nosotros a: {empresa_email}

El equipo de AMPARO"""),
]


def restaurar():
    conn = sqlite3.connect('amparo.db')
    actualizados = 0
    for clave, valor in CORREOS:
        resultado = conn.execute(
            'UPDATE configuracion SET valor=? WHERE clave=?', (valor, clave)
        )
        if resultado.rowcount > 0:
            actualizados += 1
            print(f'  OK  {clave}')
        else:
            print(f'  --  {clave} (no encontrada, saltando)')
    conn.commit()
    conn.close()
    print(f'\n{actualizados} plantillas de correo restauradas.')


if __name__ == '__main__':
    restaurar()
