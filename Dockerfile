FROM python:3.10-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

ARG TORCH_INDEX=https://download.pytorch.org/whl/cu124
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' \
        /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-asr.txt ./
RUN pip install --index-url "${TORCH_INDEX}" \
        --extra-index-url "${PIP_INDEX_URL}" \
        torch==2.5.1 torchaudio==2.5.1 \
    && pip install -i "${PIP_INDEX_URL}" -r requirements.txt -r requirements-asr.txt

COPY app ./app
COPY config ./config
COPY deploy ./deploy

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", \
     "--env-file", ".env", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
