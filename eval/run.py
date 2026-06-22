"""
RAGAS evaluation harness for the /ask query layer.

Black-box: sends each question in dataset.yaml to the running API (with
include_context so the retrieved context is returned), then scores the answers
with RAGAS — faithfulness (answer grounded in context), response relevancy
(answer addresses the question), and context precision (retrieved context is
relevant). An OpenAI model is the judge.

Environment:
  SENSE_URL          API base URL (default http://localhost:8000)
  OPENAI_API_KEY     used by RAGAS as the judge (chat + embeddings)
  EVAL_JUDGE_MODEL   judge chat model (default gpt-4o-mini)
"""

import os
import pathlib

import httpx
import yaml
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    Faithfulness,
    LLMContextPrecisionWithoutReference,
    ResponseRelevancy,
)

API_URL = os.environ.get("SENSE_URL", "http://localhost:8000").rstrip("/")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-4o-mini")


def ask(question, device_id):
    resp = httpx.post(
        f"{API_URL}/ask",
        json={"question": question, "device_id": device_id, "include_context": True},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    spec = yaml.safe_load((pathlib.Path(__file__).parent / "dataset.yaml").read_text())
    device_id = spec.get("device_id")

    samples = []
    print(f"Querying {API_URL}/ask for {len(spec['questions'])} questions...\n")
    for item in spec["questions"]:
        r = ask(item["question"], device_id)
        print(f"[{r['route']:>10}] {item['question']}\n             -> {r['answer'][:90]}")
        samples.append(SingleTurnSample(
            user_input=item["question"],
            response=r["answer"],
            retrieved_contexts=[r.get("context") or "(no context)"],
        ))

    llm = LangchainLLMWrapper(ChatOpenAI(model=JUDGE_MODEL, temperature=0))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small"))
    metrics = [Faithfulness(), ResponseRelevancy(), LLMContextPrecisionWithoutReference()]

    print("\nScoring with RAGAS...\n")
    result = evaluate(
        EvaluationDataset(samples=samples),
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
    )
    print("=== RAGAS scores ===")
    print(result)


if __name__ == "__main__":
    main()
