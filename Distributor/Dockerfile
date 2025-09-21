FROM python:3.9-slim
COPY distributor.py /
RUN chmod +0011 /distributor.py
COPY distributor-config-private.yaml /
COPY tkn-private.json /
RUN apt update && apt install -y cron
RUN apt install -y gcc
RUN apt install -y build-essential
RUN apt install -y libmariadb-dev
RUN echo "0 3 * * * /usr/local/bin/python3 /distributor.py" > /cron.txt
RUN crontab -u root /cron.txt
CMD ["cron", "-f"]
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt