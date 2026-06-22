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

    parts = ["=== KNOWLEDGE BASE ==="]
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
