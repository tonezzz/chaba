FROM python:3.11-slim

WORKDIR /repo

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

EXPOSE 8090

CMD ["python3", "frigate/control/app.py"]
