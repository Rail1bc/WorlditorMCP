# worlditor-mcp 服务镜像：COPY 源码 → pip 安装 → 启动
FROM python:3.12-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

ENV WORLDITOR_DATA_DIR=/data \
    WORLDITOR_HOST=0.0.0.0 \
    WORLDITOR_PORT=6288

VOLUME ["/data"]
EXPOSE 6288

CMD ["worlditor", "serve"]
