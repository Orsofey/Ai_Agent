# Сервер аккаунтов и подписки «Андрей».
# Собирается из содержимого папки server/ — ровно так, как её загружают в Amvera.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1 PORT=80 DATA_DIR=/data
EXPOSE 80
CMD ["python", "run.py"]
