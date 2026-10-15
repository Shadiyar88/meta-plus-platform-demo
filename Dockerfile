FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 META_DB=/app/data/meta.sqlite3
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home meta && mkdir -p /app/data && chown -R meta:meta /app
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=meta:meta . /app
USER meta
EXPOSE 8766
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8766"]
