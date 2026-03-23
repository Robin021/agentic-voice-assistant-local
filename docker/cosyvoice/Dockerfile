FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ARG VENV_NAME="cosyvoice"
ENV VENV=$VENV_NAME
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

ENV DEBIAN_FRONTEN=noninteractive
ENV PYTHONUNBUFFERED=1
SHELL ["/bin/bash", "--login", "-c"]

RUN apt-get update -y --fix-missing
RUN apt-get install -y git build-essential curl wget ffmpeg unzip git git-lfs sox libsox-dev libaio-dev && \
    apt-get clean && \
    git lfs install

# ==================================================================
# conda install and conda forge channel as default
# ------------------------------------------------------------------
# Install miniforge
RUN wget --quiet https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O ~/miniforge.sh && \
    /bin/bash ~/miniforge.sh -b -p /opt/conda && \
    rm ~/miniforge.sh && \
    ln -s /opt/conda/etc/profile.d/conda.sh /etc/profile.d/conda.sh && \
    echo "source /opt/conda/etc/profile.d/conda.sh" >> /opt/nvidia/entrypoint.d/100.conda.sh && \
    echo "source /opt/conda/etc/profile.d/conda.sh" >> ~/.bashrc && \
    echo "conda activate ${VENV}" >> /opt/nvidia/entrypoint.d/110.conda_default_env.sh && \
    echo "conda activate ${VENV}" >> $HOME/.bashrc

ENV PATH=/opt/conda/bin:$PATH

RUN conda config --add channels conda-forge && \
    conda config --set channel_priority strict
# ------------------------------------------------------------------
# ~conda
# ==================================================================

ENV HOME_DIR="/var/lib/${VENV_NAME}"

RUN groupadd --gid 1001 ${VENV_NAME}
RUN useradd --uid 1001 --gid 1001 --home-dir ${HOME_DIR} --create-home --shell /bin/bash ${VENV_NAME}
USER ${VENV_NAME}

RUN echo "source /opt/conda/etc/profile.d/conda.sh" >> ~/.bashrc && \
    echo "conda activate ${VENV}" >> $HOME/.bashrc

ENV PATH=/opt/conda/bin:$PATH

RUN conda create -y -n ${VENV} python=3.10
ENV CONDA_DEFAULT_ENV=${VENV}
ENV PYTHONPATH="${PYTHONPATH}:${HOME_DIR}/workspace/CosyVoice:${HOME_DIR}/workspace/CosyVoice/third_party/Matcha-TTS"
RUN conda init

RUN mkdir -p ${HOME_DIR}/workspace/

WORKDIR ${HOME_DIR}/workspace

RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git

RUN conda activate ${VENV} && conda install -y -c conda-forge pynini==2.1.5
RUN conda activate ${VENV} && cd CosyVoice && \
    pip install setuptools wheel && \
    pip install -r requirements.txt
RUN cd CosyVoice && git checkout dev/Comet
RUN conda activate ${VENV} && \ 
    pip uninstall -y deepspeed

WORKDIR ${HOME_DIR}/workspace/CosyVoice

RUN mkdir pretrained_models
RUN cd pretrained_models && \
    git clone https://www.modelscope.cn/iic/CosyVoice-300M.git

RUN conda activate ${VENV} && \
    modelscope download --model iic/CosyVoice-ttsfrd --local_dir pretrained_models/CosyVoice-ttsfrd
COPY --chown=${VENV_NAME}:${VENV_NAME} ./fastapi async_cosyvoice/runtime/fastapi/

RUN mkdir -p voice .cache/hub
COPY --chown=${VENV_NAME}:${VENV_NAME} ./voice voice
COPY --chown=${VENV_NAME}:${VENV_NAME} frontend.py async_cosyvoice/
COPY --chown=${VENV_NAME}:${VENV_NAME} config.py async_cosyvoice/

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=10 \
  CMD curl -f http://localhost:50001/v1/health || exit 1