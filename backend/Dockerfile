FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY requirements.lock.txt ./
ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --index-url "$PIP_INDEX_URL" -r requirements.lock.txt
COPY . .
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
