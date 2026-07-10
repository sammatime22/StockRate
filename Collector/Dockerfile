FROM ghcr.io/sammatime22/stockrate/factory:latest
COPY collector.py /
RUN chmod +0011 /collector.py
RUN apt update
RUN apt install -y gcc
RUN apt install -y build-essential
RUN apt install -y libmariadb-dev
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python3", "/collector.py"]