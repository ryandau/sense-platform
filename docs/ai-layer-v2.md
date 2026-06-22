# AI Layer v2 — Design

Status: in progress. Tracks the redesign of the `/ask` query layer and the
supporting infrastructure around it.

## Motivation

The current `/ask` endpoint is a single linear pipeline: embed the question,
run a pgvector similarity search, and pass the results to Claude. This handles
"specific" questions ("when was PM2.5 highest?") well, but answers analytical
questions ("what was the average last week?") poorly, because similarity search
is the wrong retrieval strategy for aggregates. There is also no visibility into
why a given answer was produced, no automated measure of answer quality, and no
way for external assistants to query the data.

## Goals

1. Route questions to the appropriate retrieval strategy.
2. Make the query pipeline observable.
3. Measure answer quality automatically.
4. Expose the data to Model Context Protocol (MCP) clients.

## Architecture

```
/ask  ──►  query graph (LangGraph)
            ├─ classify            analytical vs specific
            ├─ retrieve_analytical parameterised SQL aggregation
            ├─ retrieve_specific   pgvector search (existing logic)
            └─ synthesise          Claude answer
           nodes traced by Langfuse when configured

MCP server  ──►  shared query layer  ──►  PostgreSQL
                 list_devices, latest_reading, reading_history, aqi_status, ask

eval/  ──►  RAGAS harness  →  faithfulness / answer-relevancy / context-precision
```

## Components

### Query graph (LangGraph)

A `StateGraph` over `{question, device_id, hours, route, plan, context, answer}`.

- **classify** — structured output `{route, field, aggregation, window_hours}`
  from a small model. No free-form SQL is generated.
- **retrieve_analytical** — a parameterised aggregation over `readings`, e.g.
  `AVG((data->>'pm2_5')::numeric)` within a time window. Injection-safe by
  construction (fields and aggregates validated against an allow-list).
- **retrieve_specific** — the existing vector + recent-readings + knowledge-base
  retrieval.
- **synthesise** — the existing Claude call.

LangGraph is used for orchestration only; nodes call the existing OpenAI and
Anthropic clients directly, avoiding the wider LangChain LLM stack.

### Observability (Langfuse)

Optional. When `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are set, the graph
is traced (per-node spans, tokens, cost, retrieved context). A no-op otherwise.
Uses Langfuse Cloud; self-hosting is possible but requires additional services
(ClickHouse, Redis, object storage) and is out of scope here.

### MCP server

A `FastMCP` server exposing `list_devices`, `latest_reading`, `reading_history`,
`aqi_status`, and `ask`. Reuses the shared query layer so logic is not
duplicated. Runs over stdio for local clients and optionally over HTTP/SSE.

### Evaluation (RAGAS)

A development/CI harness scoring `/ask` against a fixed question set on the
faithfulness, answer-relevancy, and context-precision metrics. RAGAS's
dependencies are isolated in `requirements-eval.txt` and never enter the API
image. Runs on demand or on a schedule, not on every pull request (it makes
many model calls).

## File layout

```
backend/app/
  queries.py        shared read queries (API + MCP)
  ai/
    graph.py        LangGraph StateGraph
    retrieval.py    vector search + SQL aggregation
    tracing.py      Langfuse setup (no-op when unconfigured)
  mcp_server.py     FastMCP tools
eval/
  dataset.yaml      questions (and optional ground truth)
  run.py            RAGAS runner
requirements-eval.txt
```

## Configuration additions

| Variable | Required | Purpose |
|----------|----------|---------|
| `LANGFUSE_PUBLIC_KEY` | No | Enables tracing |
| `LANGFUSE_SECRET_KEY` | No | Enables tracing |
| `LANGFUSE_HOST` | No | Defaults to Langfuse Cloud |

## Phases

Each phase is independently mergeable.

- [x] **Phase 0 — Refactor.** Extract `queries.py` and `ai/retrieval.py` from
  `main.py`. No behaviour change; foundation for the graph and the MCP server.
- [ ] **Phase 1 — Routed `/ask`.** Add the LangGraph graph with classification
  and the analytical retrieval branch.
- [ ] **Phase 2 — Tracing.** Optional Langfuse instrumentation of the graph.
- [ ] **Phase 3 — MCP server.** Tools over the shared query layer.
- [ ] **Phase 4 — Evaluation.** RAGAS harness and an on-demand eval task.

## Notes

This work depends on the portable-Docker stack and is developed on the
`feat/ai-layer-v2` branch (cut from `feat/portable-docker`). It adds runtime
dependencies (`langgraph`, `langfuse`, `mcp`) that the portable stack does not
have; each is justified by a feature above. Evaluation dependencies are
development-only.
