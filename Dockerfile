FROM python:3.11-slim

WORKDIR /code

ENV PYTHONUNBUFFERED=1
ENV PORT=8000

RUN pip install --upgrade pip

RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

COPY requirements.txt /code

RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /code

EXPOSE 8000

CMD exec uvicorn app:app --host 0.0.0.0 --port 8000
