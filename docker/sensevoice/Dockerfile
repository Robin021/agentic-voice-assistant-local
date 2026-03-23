FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ARG VENV_NAME="sensevoice"
ENV VENV=$VENV_NAME
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

ENV DEBIAN_FRONTEN=noninteractive
ENV PYTHONUNBUFFERED=1
SHELL ["/bin/bash", "--login", "-c"]

RUN apt-get update -y --fix-missing
RUN apt-get install -y git build-essential curl wget ffmpeg unzip git git-lfs sox libsox-dev && \
    apt-get clean && \
    git lfs install

# ==================================================================
# conda install and conda forge channel as default
# ------------------------------------------------------------------
# Install miniforge
RUN wget --quiet "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh" -O ~/miniforge.sh && \
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
ENV PYTHONPATH="${PYTHONPATH}:${HOME_DIR}/workspace/SenseVoice"
RUN conda init

RUN mkdir -p ${HOME_DIR}/workspace/

WORKDIR ${HOME_DIR}/workspace

RUN git clone https://github.com/FunAudioLLM/SenseVoice.git

RUN conda activate ${VENV} && cd SenseVoice && \
    pip install "setuptools==69.5.1" wheel && \
    pip install -r requirements.txt

COPY --chown=${VENV_NAME}:${VENV_NAME} ./fastapi SenseVoice
RUN conda activate ${VENV} && pip install -r SenseVoice/requirements-server.txt

WORKDIR ${HOME_DIR}/workspace/SenseVoice

HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=10 \
  CMD curl -f http://localhost:50000/v1/health || exit 1