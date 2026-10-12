# homelab-mcp: lean MCP server for Home Assistant + Open WebUI.
#
# Dependencies are installed at build time from a fully pinned lockfile -
# never at pod start. The old mcpo chart resolved its servers from PyPI/npm on
# boot and ended up running while silently serving zero tools.
#
# Regenerate the lockfile after editing requirements.in:
#   uv pip compile --python-version 3.12 --python-platform x86_64-manylinux_2_28 requirements.in -o requirements.txt
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-deps -r requirements.txt

COPY server.py .

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin mcp
USER 10001

EXPOSE 8000
CMD ["python", "server.py"]
