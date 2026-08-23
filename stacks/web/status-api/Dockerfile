FROM registry.access.redhat.com/ubi9/python-311:latest

# Install git (for repo inspection) and upgrade packages for security patches.
USER root
RUN dnf update -y && dnf install -y git && (dnf remove -y kernel-headers vim-minimal vim-filesystem libcurl-devel libpng-devel mariadb-connector-c mariadb-connector-c-config mariadb-connector-c-devel || true) && dnf clean all \
    && git config --global --add safe.directory /repo

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools -r requirements.txt

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
