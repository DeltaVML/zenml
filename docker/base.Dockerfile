FROM ubuntu:18.04

# python
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \

RUN apt-get update && \
  apt-get install --no-install-recommends -q software-properties-common && \
  add-apt-repository ppa:deadsnakes/ppa && \
  add-apt-repository ppa:maarten-fonville/protobuf && \
  apt-get update && \
  apt-get install --no-install-recommends -q \
  build-essential \
  ca-certificates \
  libsnappy-dev \
  protobuf-compiler \
  libprotobuf-dev \
  python3.7-dev \
  wget \
  unzip \
  git && \
  add-apt-repository -r ppa:deadsnakes/ppa && \
  add-apt-repository -r ppa:maarten-fonville/protobuf && \
  apt-get autoremove --purge python2.7-dev python2.7 libpython2.7 python2.7-minimal \
  python3.5-dev python3.5 libpython3.5 python3.5-minimal && \
  update-alternatives --install /usr/bin/python python /usr/bin/python3.7 1 && \
  update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.7 1 && \
  update-alternatives --install /usr/bin/python-config python-config /usr/bin/python3.7-config 1 && \
  apt-get autoclean && \
  apt-get autoremove --purge && \
  wget https://bootstrap.pypa.io/get-pip.py && python3 get-pip.py && \
  pip install --no-cache-dir --upgrade --pre pip

ARG ZENML_VERSION
RUN pip install --no-cache zenml${ZENML_VERSION:+==$ZENML_VERSION}
