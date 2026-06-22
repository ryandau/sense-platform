"""
Tests for the routed /ask query graph (app.ai.graph).
LLM and database calls are mocked.
"""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.ai import graph


def _anthropic_returning(text):
    """A mock Anthropic client whose messages.create returns the given text."""
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text=text)]
    return client


def _conn_with_row(row):
    cur = MagicMock()
    cur.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


# ── classify ─────────────────────────────────────────────

@patch("app.config.get_anthropic")
def test_classify_analytical(mock_get):
    mock_get.return_value = _anthropic_returning(
        '{"route":"analytical","field":"co2_ppm","aggregation":"avg","window_hours":168}')
    out = graph.classify({"question": "average co2 last week"})
    assert out["route"] == "analytical"
    assert out["plan"] == {"field": "co2_ppm", "aggregation": "avg", "window_hours": 168}


@patch("app.config.get_anthropic")
def test_classify_specific(mock_get):
    mock_get.return_value = _anthropic_returning(
        '{"route":"specific","field":null,"aggregation":null,"window_hours":null}')
    out = graph.classify({"question": "when was pm2.5 worst"})
    assert out["route"] == "specific"
    assert out["plan"] is None


@patch("app.config.get_anthropic")
def test_classify_malformed_falls_back_to_specific(mock_get):
    mock_get.return_value = _anthropic_returning("sorry, not json")
    assert graph.classify({"question": "hi"})["route"] == "specific"


@patch("app.config.get_anthropic")
def test_classify_analytical_without_field_falls_back(mock_get):
    # avg with no field cannot be aggregated -> specific
    mock_get.return_value = _anthropic_returning(
        '{"route":"analytical","field":null,"aggregation":"avg","window_hours":24}')
    assert graph.classify({"question": "average?"})["route"] == "specific"


@patch("app.config.get_anthropic")
def test_classify_defaults_window_when_missing(mock_get):
    mock_get.return_value = _anthropic_returning(
        '{"route":"analytical","field":"pm2_5","aggregation":"max","window_hours":null}')
    out = graph.classify({"question": "highest pm2.5"})
    assert out["plan"]["window_hours"] == graph._DEFAULT_WINDOW_HOURS


# ── analytical retrieval ─────────────────────────────────

def test_retrieve_analytical_aggregate():
    conn, cur = _conn_with_row({"value": 9.3333, "n": 1200})
    graph._conn.set(conn)
    out = graph.retrieve_analytical(
        {"plan": {"field": "pm2_5", "aggregation": "avg", "window_hours": 168}, "device_id": "d"})
    assert out["meta"]["value"] == 9.33
    assert out["meta"]["readings"] == 1200
    assert "avg of pm2_5" in out["context"]
    # aggregate is a fixed allow-list identifier; field is a bound parameter
    sql, params = cur.execute.call_args[0]
    assert "AVG((data->>%s)::numeric)" in sql
    assert "pm2_5" in params


def test_retrieve_analytical_no_data():
    conn, _ = _conn_with_row({"value": None, "n": 0})
    graph._conn.set(conn)
    out = graph.retrieve_analytical(
        {"plan": {"field": "pm2_5", "aggregation": "max", "window_hours": 24}, "device_id": "d"})
    assert out["meta"]["value"] is None
    assert "No pm2_5 readings" in out["context"]


def test_retrieve_analytical_count_uses_count_query():
    conn, cur = _conn_with_row({"value": 42, "n": 42})
    graph._conn.set(conn)
    out = graph.retrieve_analytical(
        {"plan": {"field": None, "aggregation": "count", "window_hours": 24}, "device_id": "d"})
    assert out["meta"]["readings"] == 42
    assert "COUNT(*)" in cur.execute.call_args[0][0]


# ── specific retrieval ───────────────────────────────────

@patch("app.ai.graph.retrieval.retrieve")
def test_retrieve_specific_delegates(mock_retrieve):
    mock_retrieve.return_value = {"context": "ctx", "similar_readings": 5, "recent_readings": 3}
    graph._conn.set(MagicMock())
    out = graph.retrieve_specific({"question": "q", "device_id": "d", "hours": 24})
    assert out["context"] == "ctx"
    assert out["meta"] == {"similar_readings": 5, "recent_readings": 3}


@patch("app.ai.graph.retrieval.retrieve", return_value=None)
def test_retrieve_specific_no_readings(mock_retrieve):
    graph._conn.set(MagicMock())
    out = graph.retrieve_specific({"question": "q", "device_id": "d", "hours": 24})
    assert out["meta"] == {"similar_readings": 0, "recent_readings": 0}


# ── tracing ──────────────────────────────────────────────

def test_tracing_passthrough_without_keys():
    # No Langfuse keys in the test env, so @observe must be an identity wrapper.
    from app.ai import tracing

    @tracing.observe(name="x")
    def f(a):
        return a + 1

    assert f(1) == 2
