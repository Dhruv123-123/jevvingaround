# anygame: one paragraph, any game. Frames in, Jev decides, taps out.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble
RUN apt-get update && apt-get install -y --no-install-recommends adb libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY anygame ./anygame
COPY packs ./packs
COPY games ./games
RUN pip install --no-cache-dir . && python -c "import rapidocr_onnxruntime"   # warms the OCR model download
ENV HUD_PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
ENTRYPOINT ["anygame"]
CMD ["play", "2048", "--device", "web://games/2048.html", "--hold"]
