FROM docker.io/library/python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY drive_client.py doc_archive.py ./
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn doc_archive:app --host ${DOC_ARCHIVE_BIND:-0.0.0.0} --port ${DOC_ARCHIVE_PORT:-8000}"]
