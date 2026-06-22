# Evaluation

Offline quality evaluation of the `/ask` query layer using
[RAGAS](https://docs.ragas.io). It sends the questions in `dataset.yaml` to the
running API and scores the answers on:

- **faithfulness** — is the answer grounded in the retrieved context?
- **response relevancy** — does the answer address the question?
- **context precision** — is the retrieved context relevant?

RAGAS uses an OpenAI model as the judge, so `OPENAI_API_KEY` (from `.env`) must
have chat access. This makes many model calls; run it on demand, not per commit.

## Run

With the stack already up (`docker compose up -d`):

```bash
docker compose --profile eval run --rm eval
```

The harness is isolated in its own image (`eval/Dockerfile`) with a pinned
LangChain stack, kept separate from the API image via `requirements-eval.txt`.

To evaluate a different device or question set, edit `dataset.yaml`.
