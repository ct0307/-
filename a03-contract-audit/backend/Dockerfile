FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-dev libxml2-dev libxslt-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 构建阶段联网预下载本地 embedding 模型，烤进镜像层。
# 之后运行时强制离线（HF_HUB_OFFLINE），合同数据与模型均不出企业内网。
# 若切换 LOCAL_EMBED_MODEL，需同步修改此处模型名。
ARG EMBED_MODEL=BAAI/bge-small-zh-v1.5
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBED_MODEL}')"

COPY . .
RUN mkdir -p storage

# 运行时禁止联网校验/下载：模型已在上面烤入镜像，直接读本地缓存。
# 避免生产环境因 huggingface.co 不可达而卡在超时重试。
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
