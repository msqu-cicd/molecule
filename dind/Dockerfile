FROM debian:buster-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN set -ex; \
    apt-get update; \
    apt-get install -y --fix-missing --no-install-recommends \
        apt-transport-https \
        bash \
        ca-certificates \
        cron \
        curl \
        gnupg \
        iproute2 \
        logrotate \
        lsb-release \
        openssh-server \
        python \
        sudo \
        software-properties-common \
        systemd \
        systemd-sysv; \
    curl -fsSL https://download.docker.com/linux/debian/gpg | apt-key add -; \
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/debian $(lsb_release -cs) stable"; \
    apt-get update; \
    apt-get install -y --fix-missing --no-install-recommends \
        docker-ce \
        docker-ce-cli \
        containerd.io; \
    apt-get clean -y && apt-get clean -y && apt-get autoclean -y && rm -rf /var/lib/apt/lists/*; \
    rm -Rf /usr/share/doc && rm -Rf /usr/share/man; \
    rm -f /lib/systemd/system/multi-user.target.wants/getty.target; \
    update-alternatives --set iptables /usr/sbin/iptables-legacy; \
    update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy; \
    mkdir -p /run/sshd;

COPY docker         /etc/init.d/docker
COPY docker.service /etc/systemd/system/multi-user.target.wants/docker.service

VOLUME [ "/sys/fs/cgroup", "/var/lib/docker" ]
CMD [ "/lib/systemd/systemd" ]
