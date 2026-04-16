FROM ghcr.io/sammatime22/stockrate/factory:latest
COPY orchestrator.py /
RUN chmod +0011 /orchestrator.py
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python3", "/orchestrator.py"]