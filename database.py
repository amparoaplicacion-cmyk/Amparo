import os
import sqlite3
from datetime import datetime, timezone, timedelta

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'amparo.db')

ARGENTINA_TZ = timezone(timedelta(hours=-3))


def ahora_argentina():
    """Devuelve la fecha y hora actual en zona horaria de Argentina (UTC-3)."""
    return datetime.now(timezone.utc).astimezone(ARGENTINA_TZ).strftime('%Y-%m-%d %H:%M:%S')


def get_db():
    conn = sqlite3.connect(DATABASE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
