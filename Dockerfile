FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NODE_VERSION=20.x

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
        git \
        unzip \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION} | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY deps/repo_glm/pyproject.toml deps/repo_glm/requirements.txt ./deps/repo_glm/
COPY deps/repo_vdag/pyproject.toml deps/repo_vdag/requirements.txt ./deps/repo_vdag/

RUN pip install --upgrade pip setuptools wheel

COPY deps/repo_glm ./deps/repo_glm
COPY deps/repo_vdag ./deps/repo_vdag

RUN pip install -e ./deps/repo_glm \
 && pip install -e ./deps/repo_vdag \
 && pip install -r requirements.txt

COPY bridge_layer ./bridge_layer
COPY config.toml run.py ./

# Build number is passed in by build_and_save.ps1 so the app can display it.
# It must be an ENV (not just ARG) so it is visible when `reflex export` runs
# and top_menu.py is imported during the frontend compilation step.
ARG BUILD_NUMBER=0
ENV PYTHONPATH=/app:/app/deps/repo_vdag \
    GRAPHVISION_PIPELINE_HOOKS=bridge_layer.hooks_registration \
    REFLEX_ENV=prod \
    APP_BUILD_NUMBER=$BUILD_NUMBER

RUN cd /app/deps/repo_vdag && python -m reflex init --template blank || true \
 && cd /app/deps/repo_vdag && python -m reflex export --frontend-only --no-zip || true

EXPOSE 3322 8000

WORKDIR /app/deps/repo_vdag

CMD ["python", "-m", "reflex", "run", "--env", "prod", "--frontend-port", "3322", "--backend-port", "8000"]
