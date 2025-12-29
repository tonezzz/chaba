FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY main.py /app/main.py

ENV PORT=8067
EXPOSE 8067

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8067"]
