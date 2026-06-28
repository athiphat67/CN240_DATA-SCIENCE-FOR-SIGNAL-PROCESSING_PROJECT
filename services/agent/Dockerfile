# Use Python 3.12-slim as it's stable and modern
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    curl \
    sed \
    && rm -rf /var/lib/apt/lists/*

# แก้จุดที่ 1: ตรวจสอบการ Copy
# หากไฟล์ยังหาไม่เจอ ให้ลองเปลี่ยนเป็น COPY ./requirements.txt . 
# แต่ปกติ COPY requirements.txt . คือมาตรฐานถ้าไฟล์อยู่ข้างๆ Dockerfile
COPY requirements.txt .

# audioop-lts==0.2.2 requires Python 3.13. 
RUN sed -i '/audioop-lts/d' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# แก้จุดที่ 2: Copy ทั้งหมดไปที่ /app (ซึ่งเป็นจุดที่เราอยู่ปัจจุบัน)
COPY . .

# Set PYTHONPATH
ENV PYTHONPATH=/app

# Railway จะส่ง Port มาให้ผ่าน Environment Variable
# โค้ดคุณดึงค่า PORT อยู่แล้ว ไม่ต้องเปลี่ยนอะไรใน main.py
EXPOSE 8000

# Default command
CMD ["python", "main.py"]