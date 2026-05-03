"""
Migración: agrega columnas de pago/disbursement faltantes.
Ejecutar una sola vez en PythonAnywhere:
    python migrate_payment_columns.py
Es seguro correrlo múltiples veces (usa ALTER TABLE solo si la columna no existe).
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'amparo.db')


def add_column_if_missing(conn, table, column, definition):
    existing = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if column not in existing:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        print(f'  [+] {table}.{column}')
    else:
        print(f'  [=] {table}.{column} (ya existe)')


def main():
    conn = sqlite3.connect(DB_PATH)
    print(f'Base de datos: {DB_PATH}')

    print('\n--- solicitantes ---')
    add_column_if_missing(conn, 'solicitantes', 'mp_card_payment_method', 'TEXT')
    add_column_if_missing(conn, 'solicitantes', 'mp_customer_id',         'TEXT')
    add_column_if_missing(conn, 'solicitantes', 'mp_card_id',             'TEXT')

    print('\n--- pagos ---')
    add_column_if_missing(conn, 'pagos', 'disbursement_id',     'TEXT')
    add_column_if_missing(conn, 'pagos', 'disbursement_estado', 'TEXT')
    add_column_if_missing(conn, 'pagos', 'disbursement_fecha',  'DATETIME')
    add_column_if_missing(conn, 'pagos', 'disbursement_error',  'TEXT')

    conn.commit()
    conn.close()
    print('\nMigracion completada.')


if __name__ == '__main__':
    main()
