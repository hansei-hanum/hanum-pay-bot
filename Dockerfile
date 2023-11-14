FROM python:3.11-slim-bullseye

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python3", "main.py"]