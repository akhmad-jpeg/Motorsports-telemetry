"""Central configuration and database connection manager for F1 Telemetry Platform."""

import os
import mysql.connector

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', 'password'),
    'database': os.environ.get('DB_NAME', 'f1_strategy'),
    'port': int(os.environ.get('DB_PORT', 3306))
}

def get_db_connection():
    """Return a MySQL database connection using DB_CONFIG."""
    return mysql.connector.connect(**DB_CONFIG)
