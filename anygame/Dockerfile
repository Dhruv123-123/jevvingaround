# syntax=docker/dockerfile:1.7
# anygame: one paragraph, any game. Frames in, Jev decides, taps out.
ARG PW=1.56.0
FROM mcr.microsoft.com/playwright/python:v${PW}-noble
ARG PW
RUN apt-get update && apt-get install -y --no-install-recommends adb libgl1 xvfb && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY anygame ./anygame
COPY packs ./packs
COPY games ./games
COPY roms ./roms
# render: videos · emulator: Game Boy · stream: WebSocket state feeds · desktop: screen:// (needs a display: xvfb-run inside a container)
# a corporate proxy with its own CA: docker build --secret id=ca,src=/path/ca.crt . (ignored when absent)
RUN --mount=type=secret,id=ca,required=false sh -c 'if [ -s /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca REQUESTS_CA_BUNDLE=/run/secrets/ca SSL_CERT_FILE=/run/secrets/ca; fi; \
    pip install --no-cache-dir ".[render,emulator,stream]" "playwright==${PW}" pytest mss && pip install --no-cache-dir --no-deps pynput python-xlib six \
    && python -c "import rapidocr_onnxruntime"'   # pynput without evdev (the X backend is the one a display has); warms the OCR model download
COPY test ./test
ENV HUD_PORT=8080 PYTHONUNBUFFERED=1 ANYGAME_HOME=/packs
VOLUME /packs                                        # authored packs persist here: docker run -v anygame-packs:/packs …
EXPOSE 8080
ENTRYPOINT ["anygame"]
CMD ["play", "2048", "--device", "web://games/2048.html", "--hold"]
