FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY static ./static

ENV MCP_ASSISTANT_PORT=8099
EXPOSE 8099

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8099"]
