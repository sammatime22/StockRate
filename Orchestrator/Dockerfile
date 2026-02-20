FROM python:3.9-slim
COPY orchestrator.py /
RUN chmod +0011 /orchestrator.py
COPY orchestrator-config-private.yaml /
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt