FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8069

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

RUN pip3 install --no-cache-dir --no-deps xformers==0.0.28.post2

COPY . .

EXPOSE 8069

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8069}"]
