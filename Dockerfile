FROM python:3.12-slim

WORKDIR /app

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY app.py .
COPY coc/ coc/
COPY data/ data/
COPY static/ static/

# banco e dados persistentes fora da imagem
ENV COC_DB=/data/coc_control.db \
    COC_PRODUCTION=1 \
    COC_BEHIND_PROXY=1 \
    PYTHONUNBUFFERED=1
VOLUME /data

EXPOSE 8420
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8420/api/health',timeout=4)" || exit 1

CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "8420", "--no-browser", "--no-watcher", "--production"]
