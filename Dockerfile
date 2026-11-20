FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium
# 不设 PW_CHANNEL -> 测试默认用上面安装的 bundled chromium，无需镜像内预装 Edge
COPY . .
ENV PYTHONPATH=/app
EXPOSE 8000
