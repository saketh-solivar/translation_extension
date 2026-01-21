FROM python:3.11-slim
WORKDIR /code
ENV PYTHONUNBUFFERED=1
RUN pip install pip --upgrade
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean
COPY requirements.txt /code
# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code to the container
COPY . /code
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]