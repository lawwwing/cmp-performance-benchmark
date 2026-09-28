FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN useradd --create-home --uid 1000 --user-group bench \
    && chown -R bench:bench /app

USER bench

ENV PYTHONUNBUFFERED=1 \
    CMP_BENCH_BIND=0.0.0.0

EXPOSE 4173

CMD ["python3", "scripts/serve.py"]
