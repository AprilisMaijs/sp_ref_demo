
FROM python:3.12-slim

WORKDIR /app
COPY service_b/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY service_b /app
EXPOSE 8001
CMD ["python", "main.py"]
