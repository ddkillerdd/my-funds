FROM python:3.12-slim

WORKDIR /app

# 构建上下文必须是 monorepo 根目录；Linux 哈希锁固定运行时传递依赖。
COPY fund-advisor/requirements-linux.lock /app/fund-advisor/requirements-linux.lock
# 允许隔离 staging 选择可达的包源，默认仍使用官方 PyPI。
ARG PIP_INDEX_URL=https://pypi.org/simple
# 服务器外网下载较慢时延长读取超时并重试，仍保持锁文件哈希校验。
RUN python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" \
    --timeout 180 --retries 10 --require-hashes \
    -r /app/fund-advisor/requirements-linux.lock

COPY fund-advisor/backend/ /app/fund-advisor/backend/
COPY fund-advisor/alembic/ /app/fund-advisor/alembic/
COPY fund-advisor/alembic.ini.example /app/fund-advisor/alembic.ini
COPY fund-analyzer/engine/ /app/fund-analyzer/engine/

WORKDIR /app/fund-advisor

RUN mkdir -p data/uploads

EXPOSE 8200

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8200"]
