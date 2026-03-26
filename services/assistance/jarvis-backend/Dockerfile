FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./

ENV JARVIS_HOST=0.0.0.0
ENV JARVIS_PORT=18018

EXPOSE 18018

CMD ["python", "main.py"]
