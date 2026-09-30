FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Bundle the model at build time; rendering never uploads narration or waits
# for a model download. The child process releases inference RAM before editing.
ENV WHISPER_MODEL=/opt/whisper-tiny.en
RUN python -c "from faster_whisper.utils import download_model; download_model('tiny.en', output_dir='/opt/whisper-tiny.en')"
COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 10000

CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
