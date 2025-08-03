FROM python:3.9-slim
COPY emailer.py /
COPY emailer-config-private.yaml /
COPY emailer-oauth2-private.txt /
RUN apt update && apt install -y cron
RUN apt install -y gcc
RUN apt install -y build-essential
RUN apt install -y libmariadb-dev
RUN echo "0 3 * * * python3 /emailer.py" | crontab -u root -
CMD ["cron", "-f", "/etc/crontabs/root"]
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt