FROM python:3.12-slim

WORKDIR /app

# 依赖单独一层,代码改动不触发重装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# 非 root 运行
RUN useradd -r -u 10001 appuser && mkdir -p /app/qa_logs && chown -R appuser /app
USER appuser

EXPOSE 8741

# 注意:本服务**不挂 vault 卷**。生产数据面是 heng-pg 投影,
# vault backend 只用于本地开发。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8741"]
