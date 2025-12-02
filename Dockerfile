FROM python:3.11

WORKDIR /app

ENV PYTHONUNBUFFERED=1

ENV KMP_DUPLICATE_LIB_OK=TRUE

COPY requirements.txt .

# Installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript \
    poppler-utils \
    gcc \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libxrender1 \
    libxext6 \
    libsm6 \
    libxrandr2 \
    libfontconfig1 \
    tesseract-ocr \
    tesseract-ocr-fra \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install -r requirements.txt

COPY . .

COPY ./protos ./protos

RUN python -m grpc_tools.protoc -I./protos --python_out=. --grpc_python_out=. ./protos/pdf_service.proto

EXPOSE 50051
CMD ["python", "server.py"]
