FROM python:3.12-slim
RUN pip install --no-cache-dir "wyoming>=1.5" "faster-whisper>=1.1" numpy
COPY langproxy.py /app/langproxy.py
VOLUME ["/data"]
ENTRYPOINT ["python", "/app/langproxy.py"]
