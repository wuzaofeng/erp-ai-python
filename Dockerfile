FROM python:3.11-slim

WORKDIR /app

# 系统依赖（chromadb / pymupdf 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 layer 缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 数据目录（SQLite + ChromaDB）在此，挂载 volume 覆盖
RUN mkdir -p /app/data/chroma

EXPOSE 3001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3001"]
