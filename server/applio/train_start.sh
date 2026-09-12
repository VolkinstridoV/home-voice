#!/bin/sh
# Start (or resume) RVC training for the jobbot model inside the applio container.
# Runs in the background inside the container; console goes to train_console.log.
set -e
cd /app
exec python core.py train \
  --model-name jobbot \
  --sample-rate 48000 \
  --total-epoch 2000 \
  --save-every-epoch 10 \
  --batch-size 8 \
  --gpu - \
  --pretrained \
  --vocoder HiFi-GAN \
  --index-algorithm Auto \
  > /app/logs/jobbot/train_console.log 2>&1
