FROM python:3-alpine

COPY Slim_requirements.in /requirements.in

RUN apk update && \
    apk add --no-cache --virtual .build-deps \
    python3-dev py3-setuptools py3-wheel gcc build-base musl-dev libffi-dev openssl-dev autoconf automake linux-headers && \
    apk add --no-cache python3 py3-pip bash bind-tools curl git make openssh-client rsync sshpass sudo yq && \
    pip3 install --no-cache-dir --no-compile pip-tools && pip-compile /requirements.in && \
    pip3 install --no-cache-dir --no-compile -r requirements.txt && \
    apk del .build-deps && \
    mkdir -p ~/.ansible/plugins/modules && \
    curl -o ~/.ansible/plugins/modules/aur.py https://raw.githubusercontent.com/kewlfft/ansible-aur/master/plugins/modules/aur.py && \
    mkdir -p ~/.ansible/plugins/filter && \
    curl -o ~/.ansible/plugins/filter/get_hetznercloud_networks.py https://raw.githubusercontent.com/ansible-community/molecule-hetznercloud/main/molecule_hetznercloud/playbooks/filter_plugins/get_hetznercloud_networks.py
