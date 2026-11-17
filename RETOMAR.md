# Para retomar el proyecto AMPARO (actualizado el 11/11/2026)

## Estado
- El código del modelo Marketplace (OAuth + application_fee) ya está hecho y en main.
- Bloqueo: al vincular la cuenta MP del prestador, MP muestra "La aplicación no está
  preparada para conectar con Mercado Pago" (App 281380903524855). Según MP (WCS-45763)
  falta que habiliten el flujo OAuth (allow_flow) del lado de ellos; no es autoservicio.
- Tickets anteriores: WCS-44983 y WCS-45763 (cerrados).
- 11/11/2026: se abrió un ticket nuevo por el asistente de MP Developers (producto
  Credentials). Número: WCS-58435 (producto: Online Payments - Checkout API).
- 12/11/2026 13:56 respondió MP (Sofía) en el ticket: allow_flow vacío y validación de
  permisos para vincular vendedores NO aprobada. No lo pueden activar desde ese canal;
  quedó ESCALADO. Pidieron NO repetir intentos con cuentas reales hasta que confirmen.
  No contestaron las 2 preguntas (cuenta personal vs negocio; fondos inmediatos).
- Seguir el ticket desde el botón "Revisar solicitud" del mail (las respuestas no
  siempre llegan por mail). Si para el 24/11 no hay novedades, mandar un seguimiento.

## Resultado de la prueba del 11/11/2026 (casa de Julia Balestre, prestadora)
- Solicitante de prueba: colosorodas5. Tarjeta: VISA de CRÉDITO terminada en 9667
  (no es débito).
- Flujo completo hasta el cobro: pedido → aceptado → confirmar llegada (GPS) → cobro OK.
  - Pago 24 ($34,50): rechazado por CVV mal cargado (cc_rejected_bad_filled_security_code).
  - Pago 25 ($14,38): aprobado. Entró entero a la cuenta MP de Amparo.
- Julia NO tiene MP vinculado → se usó el modelo viejo (disbursement), que falla con
  HTTP 404: MP no tiene API para transferir de una cuenta a otra. Sus $11,62 se le
  transfirieron a mano desde la app MP.
- Intento de vinculación OAuth: 11/11/2026 11:54 (hora Argentina). Se eligió Argentina y
  salió "La aplicación no está preparada para conectar con Mercado Pago". Hay captura.
- Verificado en producción: mp_client_id = 281380903524855 y
  app_url = https://amparoaplicacion.pythonanywhere.com (correctos).

## OJO: dejado así en producción (volver atrás después de la próxima prueba)
- geofence_radio_metros = 20000 (lo normal es 50). Se subió porque Julia estaba a ~5,9 km
  de la dirección de colosorodas5. Para volver a 50, en el Bash de PythonAnywhere:
  python3 -c "import sqlite3;c=sqlite3.connect('amparo/amparo.db');c.execute(\"UPDATE configuracion SET valor='50' WHERE clave='geofence_radio_metros'\");c.commit()"
- La base que usa la app en PythonAnywhere es ~/amparo/amparo.db (hay otra suelta en
  ~/amparo.db que no se usa).

## Próximo paso
- Esperar la respuesta de MP. Cuando habiliten allow_flow, volver a casa de Julia y
  repetir: perfil de Julia → Editar perfil → "Vincular con Mercado Pago" (con la cuenta
  MP de Julia, no la de Amparo). Si el recuadro queda verde, hacer un servicio de prueba
  y verificar que la plata le llegue directo a Julia.

## Pendientes de código
- El token de la tarjeta se genera con las credenciales de Amparo, pero el cobro con
  split usa el access_token del prestador (routes/solicitante.py, ~línea 1543).
  Probablemente MP lo rechace: hay que generar el token con la public_key del prestador
  (prestadores.mp_oauth_public_key).
- El 11/11 a las 14:22 (UTC) la app intentó el disbursement del pago 24 aunque el cobro
  fue RECHAZADO. Revisar qué camino lo disparó (no debería transferir si no se cobró).
- El mail de contraseña temporal llega vacío (revisar la plantilla
  mail_contrasena_temp_cuerpo en producción).
- Agregar la opción "olvidé mi contraseña" (envío de un link por mail).

## Condiciones del dueño
- El prestador tiene que recibir el dinero en el mismo momento, sin retención.
- Ningún trámite fiscal (monotributo / cuenta de negocio) hasta que funcione.
