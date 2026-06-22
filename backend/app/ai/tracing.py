"""
Optional Langfuse tracing for the query graph.

When LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set, the graph nodes are
recorded as spans in Langfuse (routing decision, retrieved context, answer,
latency). When unconfigured this is a pass-through and Langfuse is never
imported, so it adds no overhead and emits no logs.
"""

from app import config


def observe(**kwargs):
    """Decorator: Langfuse ``@observe`` when tracing is configured, else identity."""
    if not config.TRACING_ENABLED:
        return lambda fn: fn
    from langfuse import observe as _observe
    return _observe(**kwargs)
