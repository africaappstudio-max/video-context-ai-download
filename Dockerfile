FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
# Starts without a license; the license is checked only when the tool is called.
CMD ["understand-this-video-mcp"]
