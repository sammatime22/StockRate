FROM python:3.6-slim
COPY collector.py /
RUN chmod +0011 /collector.py
COPY collector-config-private.yaml /
RUN apt update && apt install -y cron
RUN apt install -y gcc
RUN apt install -y build-essential
RUN apt install -y libmariadb-dev
RUN echo "40 1 * * * /usr/local/bin/python3 /collector.py" > /cron.txt
RUN crontab -u root /cron.txt
CMD ["cron", "-f"]
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt