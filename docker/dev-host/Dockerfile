FROM node:20-bullseye

LABEL maintainer="surf-thailand" \
      description="Local replica of dev-host for combined a1-idc1/idc1 development"

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server sudo netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Prepare SSH server
RUN mkdir -p /var/run/sshd

# Create deployer user for SSH access
RUN useradd -ms /bin/bash deployer \
    && echo "deployer:changeme" | chpasswd \
    && usermod -aG sudo deployer \
    && mkdir -p /home/deployer/.ssh

COPY sshd_config /etc/ssh/sshd_config
COPY authorized_keys.sample /home/deployer/.ssh/authorized_keys

RUN chown -R deployer:deployer /home/deployer/.ssh \
    && chmod 700 /home/deployer/.ssh \
    && chmod 600 /home/deployer/.ssh/authorized_keys

WORKDIR /workspace

EXPOSE 22 3000

HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD nc -z localhost 22 || exit 1

CMD ["/usr/sbin/sshd", "-D"]
