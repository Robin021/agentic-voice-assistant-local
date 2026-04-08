FROM ubuntu:24.04

ARG VENV_NAME="voicebot"
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
    echo "source /opt/conda/etc/profile.d/conda.sh" >> ~/.bashrc && \
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

RUN conda create -y -n ${VENV} python=3.13
ENV CONDA_DEFAULT_ENV=${VENV}
ENV PYTHONPATH="${HOME_DIR}/workspace/backend"
RUN conda init

RUN mkdir -p ${HOME_DIR}/workspace/backend

WORKDIR ${HOME_DIR}/workspace

COPY --chown=${VENV_NAME}:${VENV_NAME} source/backend backend
RUN conda activate ${VENV} && cd backend && \
    pip install -r requirements.txt && \
    python -c "import litellm.main; f=open(litellm.main.__file__,'a'); f.write('\nvertex_text_to_speech=None\n'); f.close()"

WORKDIR ${HOME_DIR}/workspace

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=10 \
  CMD curl -f http://localhost:8080/ || exit 1
