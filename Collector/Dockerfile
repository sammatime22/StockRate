FROM python:3.6-slim
COPY collector.py /
COPY collector-config-private.yaml /
RUN apt update && apt install -y cron
RUN apt install -y gcc
RUN apt install -y build-essential
RUN apt install -y libmariadb-dev
RUN echo "0 23 * * * python3 /collector.py" | crontab -u root -
CMD ["cron", "-f", "/etc/crontabs/root"]
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt