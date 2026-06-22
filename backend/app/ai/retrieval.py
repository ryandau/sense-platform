"""
Retrieval for the /ask query layer.

Resolves the target device and assembles the RAG context (vector similarity
search, recent readings, and the knowledge base). The connection lifecycle is
the caller's responsibility.
"""

from app.config import generate_embedding


def resolve_device_id(conn, device_id=None):
    """Return device_id, defaulting to the most recently seen device, or None."""
    if device_id:
        return device_id
    with conn.cursor() as cur:
        cur.execute("SELECT device_id FROM devices ORDER BY last_seen_at DESC LIMIT 1")
        row = cur.fetchone()
    return row["device_id"] if row else None


def retrieve(conn, question, device_id, hours):
    """
    Assemble the RAG context for a question. Returns a dict with the context
    string and retrieval counts, or None when the device has no readings.
    """
    with conn.cursor() as cur:
        q_embedding = generate_embedding(question)

        # Most relevant readings to the question (vector similarity).
        cur.execute("""
            SELECT re.content, r.recorded_at
            FROM reading_embeddings re
            JOIN readings r ON r.id = re.reading_id
            WHERE r.device_id = %s AND re.embedding IS NOT NULL
            ORDER BY re.embedding <=> %s::vector
            LIMIT 30
        """, (device_id, str(q_embedding)))
        similar = cur.fetchall()

        # Most recent readings for current-state questions.
        cur.execute("""
            SELECT re.content, r.recorded_at
            FROM reading_embeddings re
            JOIN readings r ON r.id = re.reading_id
            WHERE r.device_id = %s
              AND r.recorded_at > NOW() - INTERVAL '%s hours'
            ORDER BY r.recorded_at DESC
            LIMIT 10
        """, (device_id, hours))
        recent = cur.fetchall()

        cur.execute("""
            SELECT title, content FROM knowledge_base
            WHERE type_slug IS NULL
               OR type_slug = (SELECT type_slug FROM devices WHERE device_id = %s)
            ORDER BY category, title
        """, (device_id,))
        knowledge = cur.fetchall()

    if not similar and not recent:
        return None

    # Overall distribution first, so a vector sample of typical readings cannot
    # make the answer overlook extremes (e.g. hazardous spikes).
    parts = []
    overview = overview_context(conn, device_id)
    if overview:
        parts.append(overview)

    parts.append("=== KNOWLEDGE BASE ===")
    for kb in knowledge:
        parts.append(f"## {kb['title']}\n{kb['content']}")

    seen = set()
    recent_unique, relevant_unique = [], []
    for r in recent:
        if r["content"] not in seen:
            seen.add(r["content"])
            recent_unique.append(r["content"])
    for r in similar:
        if r["content"] not in seen:
            seen.add(r["content"])
            relevant_unique.append(r["content"])

    parts.append("\n=== MOST RECENT READINGS ===")
    parts.extend(recent_unique)
    if relevant_unique:
        parts.append("\n=== MOST RELEVANT READINGS (by similarity to question) ===")
        parts.extend(relevant_unique)

    return {
        "context": "\n\n".join(parts),
        "similar_readings": len(similar),
        "recent_readings": len(recent),
    }


def field_statistics(conn, device_id):
    """
    Return min/max/avg for each numeric field over ALL of a device's readings,
    keyed by field. Computed generically from the device type's fields, so it is
    sensor-agnostic. Non-numeric values are filtered out before casting.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT type_slug FROM devices WHERE device_id = %s", (device_id,))
        row = cur.fetchone()
        if not row or not row.get("type_slug"):
            return {}
        cur.execute("SELECT fields FROM device_types WHERE slug = %s", (row["type_slug"],))
        frow = cur.fetchone()
        fields_meta = (frow or {}).get("fields") or {}
        fields = list(fields_meta.keys())
        if not fields:
            return {}

        numeric = r"^-?[0-9]+\.?[0-9]*$"   # only cast numeric-looking values
        selects, params = [], []
        for i, f in enumerate(fields):
            selects.append(
                f"MIN((data->>%s)::numeric) FILTER (WHERE data->>%s ~ %s) AS min_{i}, "
                f"MAX((data->>%s)::numeric) FILTER (WHERE data->>%s ~ %s) AS max_{i}, "
                f"ROUND(AVG((data->>%s)::numeric) FILTER (WHERE data->>%s ~ %s), 2) AS avg_{i}"
            )
            params += [f, f, numeric, f, f, numeric, f, f, numeric]
        params.append(device_id)
        cur.execute("SELECT " + ", ".join(selects) + " FROM readings WHERE device_id = %s", params)
        vals = cur.fetchone()

    stats = {}
    for i, f in enumerate(fields):
        avg = vals.get(f"avg_{i}")
        if avg is None:
            continue  # no numeric readings for this field
        meta = fields_meta.get(f, {})
        stats[f] = {
            "label": meta.get("label", f),
            "unit": meta.get("unit", ""),
            "min": float(vals[f"min_{i}"]),
            "max": float(vals[f"max_{i}"]),
            "avg": float(avg),
        }
    return stats


def recorded_categories(conn, device_id):
    """
    Distinct computed categorical values observed for a device, per metric
    (e.g. aqi_category -> [Good, Moderate, ..., Hazardous]). Grounds the
    interpretive health language an answer may use. Sensor-agnostic: derived
    from whatever non-numeric values appear in readings.computed.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kv.key AS key, array_agg(DISTINCT kv.value) AS values "
            "FROM readings r, jsonb_each_text(r.computed) AS kv "
            "WHERE r.device_id = %s AND r.computed IS NOT NULL "
            "AND kv.value !~ '^-?[0-9.]+$' "
            "GROUP BY kv.key",
            (device_id,),
        )
        rows = cur.fetchall()
    return {r["key"]: sorted(r["values"]) for r in rows}


def overview_context(conn, device_id):
    """
    Overall distribution stats + recorded categories as a context block, shared
    by both /ask routes so analytical and specific answers are grounded in the
    full distribution (including extremes), not just their own slice. Returns ''
    when there is nothing to report.
    """
    parts = []
    stats = field_statistics(conn, device_id)
    if stats:
        parts.append("=== OVERALL STATISTICS (all readings for this device) ===")
        for s in stats.values():
            unit = f" {s['unit']}" if s["unit"] else ""
            parts.append(f"{s['label']}: average {s['avg']}{unit}, range {s['min']} to {s['max']}{unit}")
    cats = recorded_categories(conn, device_id)
    if cats:
        parts.append("=== RECORDED CATEGORIES (computed across all readings) ===")
        for key, values in cats.items():
            parts.append(f"{key}: {', '.join(values)}")
    return "\n\n".join(parts)
