# FROM python:3.11
# WORKDIR /code
# COPY . /code
# RUN pip install pip --upgrade
# RUN pip install -r /code/requirements.txt
# RUN apt-get update && apt-get install -y ffmpeg
# RUN apt-get clean && rm -rf /var/lib/apt/lists/*
# CMD ["uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim
WORKDIR /code
RUN pip install pip --upgrade
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean
COPY requirements.txt /code
# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code to the container
COPY . /code
CMD ["uvicorn", "app:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]