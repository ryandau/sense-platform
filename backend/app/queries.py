"""
Shared read queries for devices and readings.

Each function takes an open database connection and returns plain dicts, so the
same logic backs both the HTTP API and the MCP server. Connection lifecycle is
the caller's responsibility.
"""


def list_devices(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.*, COUNT(r.id) as reading_count,
                   MAX(r.recorded_at) as last_reading_at
            FROM devices d
            LEFT JOIN readings r ON r.device_id = d.device_id
            GROUP BY d.id ORDER BY d.last_seen_at DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def latest_reading(conn, device_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM readings WHERE device_id = %s
            ORDER BY recorded_at DESC LIMIT 1
        """, (device_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def reading_history(conn, device_id, limit=100):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM readings WHERE device_id = %s
            ORDER BY recorded_at DESC LIMIT %s
        """, (device_id, min(limit, 1000)))
        return [dict(r) for r in cur.fetchall()]


def list_device_types(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM device_types ORDER BY name")
        return [dict(r) for r in cur.fetchall()]
