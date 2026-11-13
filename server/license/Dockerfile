FROM python:3.12-slim
WORKDIR /app
COPY app.py admin.html /app/
ENV DB_PATH=/data/licenses.db PORT=8010 TRIAL_DAYS=3 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8010
CMD ["python3", "/app/app.py"]
