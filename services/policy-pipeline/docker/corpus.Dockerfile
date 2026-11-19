# 政策原文对外只读 API。独立小镜像，不动 policy-pipeline:latest 的依赖层。
# 只 COPY 两个 scripts 包；vault 从不挂载 —— 派生产物在部署形态上不可达。
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pyyaml "fastapi>=0.110" "uvicorn>=0.29"
COPY scripts/__init__.py ./scripts/__init__.py
COPY scripts/public_export ./scripts/public_export
COPY scripts/corpus_service ./scripts/corpus_service
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
EXPOSE 8731
CMD ["python", "-m", "uvicorn", "scripts.corpus_service.app:app", "--host", "0.0.0.0", "--port", "8731"]
