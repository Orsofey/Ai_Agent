# Сервер аккаунтов и подписки «Андрей». Собирается из корня репозитория (amvera.yml).
FROM python:3.12-slim
WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ .
ENV PYTHONUNBUFFERED=1 PORT=80 DATA_DIR=/data
EXPOSE 80
CMD ["python", "run.py"]
