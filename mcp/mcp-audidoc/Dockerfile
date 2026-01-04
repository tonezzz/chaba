FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8075 \
    OCR_ENABLED=1 \
    OCR_LANG=tha+eng \
    AUDIDOC_ROOT=/data \
    AUDIDOC_PDF_DIR=audidoc-pdfs

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      curl \
      poppler-utils \
      tesseract-ocr \
      tesseract-ocr-tha \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY main.py /app/main.py

EXPOSE 8075

HEALTHCHECK --interval=10s --timeout=3s --retries=12 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8075"]
