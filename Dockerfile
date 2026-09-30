FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Europe/Istanbul MPLCONFIGDIR=/tmp/mpl
RUN apt-get update && apt-get install -y --no-install-recommends fonts-inter tzdata \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
CMD ["python", "main.py"]
