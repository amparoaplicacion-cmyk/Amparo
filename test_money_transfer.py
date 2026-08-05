"""
Script de prueba puntual — NO forma parte de la app.
Prueba el camino alternativo que sugirió Soporte MP para transferir saldo
account_money entre cuentas, ya que POST /v1/transfers da 404.

Uso: python3 test_money_transfer.py
Correr desde /home/amparoaplicacion/amparo/ (usa la misma amparo.db de producción).

OJO: si la llamada tiene éxito, mueve plata real (monto chico de prueba).
"""
import sqlite3
import requests

DB_PATH = 'amparo.db'
EMAIL_PRESTADOR = 'ellesuije@yahoo.com.ar'  # cambiar si querés probar con otro prestador
MONTO_PRUEBA = 1.0

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT valor FROM configuracion WHERE clave='mp_access_token'").fetchone()
access_token = (row['valor'] or '').strip() if row else ''

if not access_token:
    print('No hay mp_access_token cargado en la tabla configuracion.')
    raise SystemExit(1)

payload = {
    'transaction_amount': MONTO_PRUEBA,
    'payment_method_id': 'account_money',
    'operation_type': 'money_transfer',
    'description': 'Test money_transfer AMPARO',
    'payer': {'email': EMAIL_PRESTADOR},
}

resp = requests.post(
    'https://api.mercadopago.com/v1/payments',
    json=payload,
    headers={
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'X-Idempotency-Key': 'test-money-transfer-amparo-001',
    },
    timeout=20,
)

print(f'HTTP {resp.status_code}')
print(resp.text)
