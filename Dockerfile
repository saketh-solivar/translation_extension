FROM python:3.11-slim

WORKDIR /code

ENV PYTHONUNBUFFERED=1

RUN pip install --upgrade pip

RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

COPY requirements.txt /code

RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /code

# Explicitly copy credentials file
COPY credentials.json /code/credentials.json

EXPOSE 8080

CMD exec uvicorn app:app --host 0.0.0.0 --port $PORT
