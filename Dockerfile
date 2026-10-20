FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 SDL_VIDEODRIVER=dummy CUDA_VISIBLE_DEVICES="" HOME=/tmp MPLCONFIGDIR=/tmp/matplotlib
RUN pip install --no-cache-dir torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir stable-baselines3==2.9.0 gymnasium==1.4.0 numpy==2.2.6 pygame==2.6.1 pillow==11.3.0 imageio==2.37.0 imageio-ffmpeg==0.6.0
COPY arena/worker.py /app/worker.py
WORKDIR /app
USER 1000:1000
ENTRYPOINT ["python", "/app/worker.py"]
