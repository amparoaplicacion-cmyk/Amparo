# Para retomar el proyecto AMPARO (actualizado el 10/11/2026)

## Estado
- El código del modelo Marketplace (OAuth + application_fee) ya está hecho y en main.
- Bloqueo: al vincular la cuenta MP del prestador, MP muestra "La aplicación no está
  preparada para conectar a MP" (App 281380903524855).
- El ticket WCS-45763 se cerró el 03/09/2026 porque no le mandamos a MP la fecha y hora
  de un intento reciente. El ticket anterior es WCS-44983.

## Prueba del 11/11 (en casa de un prestador de confianza)
1. En el admin de Amparo, Configuración → Pagos: revisar que estén el Client ID
   (281380903524855) y el Client Secret.
2. En el panel de MP (Tus integraciones → app): la Redirect URL tiene que ser exactamente
   https://amparoaplicacion.pythonanywhere.com/prestador/mercadopago/callback
3. Entrar a Amparo como prestador → editar perfil → "Vincular MercadoPago", e iniciar
   sesión con la cuenta MP real de ESA persona (no la de Amparo).
4. Anotar la fecha y hora exactas, sacar captura, y copiar el error log de PythonAnywhere
   (pestaña Web).
5. Con eso, redactar un ticket nuevo citando WCS-45763 y WCS-44983, con dos preguntas:
   - ¿Se puede habilitar allow_flow en una cuenta personal?
   - ¿El prestador recibe la plata disponible en el momento?

## Pendientes de código
- El token de la tarjeta se genera con las credenciales de Amparo, pero el cobro con
  split usa el access_token del prestador (routes/solicitante.py, ~línea 1543).
  Probablemente MP lo rechace: hay que generar el token con la public_key del prestador
  (prestadores.mp_oauth_public_key).
- Agregar la opción "olvidé mi contraseña" (envío de un link por mail).

## Condiciones del dueño
- El prestador tiene que recibir el dinero en el mismo momento, sin retención.
- Ningún trámite fiscal (monotributo / cuenta de negocio) hasta que funcione.
