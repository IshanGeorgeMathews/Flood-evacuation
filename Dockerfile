# FloodEvac Ernakulam — web app image.
# The image serves the dashboard and API from the processed artefacts in data/processed and models/.
# Run the data pipeline on a workstation (needs Google Earth Engine credentials), or download the release
# artefacts with scripts/fetch_data.ps1, before building.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLOODEVAC_ROOT=/app \
    PORT=8000

WORKDIR /app

# geospatial wheels (shapely, pyproj, pyogrio, rasterio) bundle their native libraries
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[pipeline]"

COPY configs ./configs
COPY web ./web
COPY data/reference ./data/reference
COPY data/processed ./data/processed
COPY models ./models
COPY tests/fixtures ./tests/fixtures

RUN useradd --create-home --uid 1000 floodevac && chown -R floodevac /app
USER floodevac

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=8)"

CMD ["python", "-m", "floodevac.api.app"]
