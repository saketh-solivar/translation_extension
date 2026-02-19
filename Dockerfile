FROM python:3.11-slim

WORKDIR /code

ENV PYTHONUNBUFFERED=1

RUN pip install --upgrade pip

RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

COPY requirements.txt /code

RUN pip install --no-cache-dir -r requirements.txt

# 👇 THIS LINE WAS MISSING
COPY . /code

EXPOSE 8080

CMD exec uvicorn app:app --host 0.0.0.0 --port $PORT
