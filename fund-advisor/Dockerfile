FROM python:3.12-slim

WORKDIR /app

# 构建上下文必须是 monorepo 根目录；Linux 哈希锁固定运行时传递依赖。
COPY fund-advisor/requirements-linux.lock /app/fund-advisor/requirements-linux.lock
RUN python -m pip install --no-cache-dir --require-hashes \
    -r /app/fund-advisor/requirements-linux.lock

COPY fund-advisor/backend/ /app/fund-advisor/backend/
COPY fund-advisor/alembic/ /app/fund-advisor/alembic/
COPY fund-advisor/alembic.ini.example /app/fund-advisor/alembic.ini
COPY fund-analyzer/engine/ /app/fund-analyzer/engine/

WORKDIR /app/fund-advisor

RUN mkdir -p data/uploads

EXPOSE 8200

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8200"]
