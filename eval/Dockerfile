# Evaluation harness image (development only). Build context is the repo root.
FROM python:3.12-slim
WORKDIR /eval
COPY requirements-eval.txt /tmp/requirements-eval.txt
RUN pip install --no-cache-dir -r /tmp/requirements-eval.txt
COPY eval/ /eval/
CMD ["python", "run.py"]
