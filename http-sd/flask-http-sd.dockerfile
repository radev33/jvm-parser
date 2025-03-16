FROM python:3.14-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sd_api.py .

EXPOSE 8000
CMD ["python", "sd_api.py"]