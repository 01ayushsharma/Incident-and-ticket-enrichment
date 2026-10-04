# One image, five roles. Every service in this stack shares the same Python
# dependencies, so building once and selecting the entrypoint per service in
# docker-compose keeps the build to a single layer cache rather than five.
#
# Multi-stage: the builder installs into a virtualenv that the runtime copies,
# so compilers and build headers never reach the final image.

# ---------------------------------------------------------------- builder ---
FROM python:3.11-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependency layer first: it changes far less often than the source, so a code
# edit does not reinstall chromadb and onnxruntime.
COPY pyproject.toml README.md ./
RUN python - <<'PY' > /tmp/requirements.txt
import tomllib, pathlib
data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
print("\n".join(data["project"]["dependencies"]))
PY
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# --------------------------------------------------------------- runtime ---
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # The repository mirrors the layout the submission guidelines ask for,
    # which is several package roots rather than one.
    PYTHONPATH="/app:/app/services:/app/mcp-servers/alarm-management:/app/apps/backend:/app/apps/frontend"

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Run as a non-root user: nothing here needs privileges.
RUN useradd --create-home --uid 10001 copilot
WORKDIR /app

COPY --chown=copilot:copilot services/     ./services/
COPY --chown=copilot:copilot connectors/   ./connectors/
COPY --chown=copilot:copilot mcp-servers/  ./mcp-servers/
COPY --chown=copilot:copilot apps/         ./apps/
COPY --chown=copilot:copilot rag/          ./rag/
COPY --chown=copilot:copilot scripts/      ./scripts/
COPY --chown=copilot:copilot test-data/    ./test-data/
COPY --chown=copilot:copilot pyproject.toml README.md ./

# The GUI's palette, fonts and radii live here, not in the Python source:
# without it the containerised GUI falls back to Streamlit's default theme.
# `streamlit run` reads it relative to the working directory, which is /app.
COPY --chown=copilot:copilot .streamlit/   ./.streamlit/

# Writable location for the retrieval index and the cached embedding model.
RUN mkdir -p /app/.index && chown -R copilot:copilot /app/.index
ENV VECTOR_STORE_PATH=/app/.index/chroma \
    HF_HOME=/app/.index/models \
    CHROMA_CACHE_DIR=/app/.index/models

USER copilot

# Overridden per service in docker-compose.yml.
CMD ["python", "-m", "uvicorn", "alarm_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
