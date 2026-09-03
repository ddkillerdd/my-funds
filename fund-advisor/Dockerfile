FROM python:3.12-slim

WORKDIR /app

# 构建上下文必须是 monorepo 根目录，以便同时安装应用层和分析引擎依赖。
COPY fund-advisor/requirements.txt /app/fund-advisor/requirements.txt
COPY fund-analyzer/requirements.txt /app/fund-analyzer/requirements.txt
RUN pip install --no-cache-dir \
    -r /app/fund-advisor/requirements.txt \
    -r /app/fund-analyzer/requirements.txt

COPY fund-advisor/backend/ /app/fund-advisor/backend/
COPY fund-advisor/alembic/ /app/fund-advisor/alembic/
COPY fund-advisor/alembic.ini.example /app/fund-advisor/alembic.ini
COPY fund-analyzer/engine/ /app/fund-analyzer/engine/

WORKDIR /app/fund-advisor

RUN mkdir -p data/uploads

EXPOSE 8200

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8200"]
