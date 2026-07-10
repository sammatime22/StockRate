FROM python:3.10-slim
COPY factory.py /
RUN apt update && apt install -y cron
RUN echo "0 4 * * * rm /*.log" > /cron.txt
RUN crontab -u root /cron.txt
CMD ["cron", "-f"]