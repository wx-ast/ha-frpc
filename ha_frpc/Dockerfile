ARG BUILD_FROM
FROM $BUILD_FROM

# FRP version argument
ARG FRP_VERSION=0.65.0

# Install dependencies
RUN apk add --no-cache curl tar python3 \
    && arch="$(apk --print-arch)" \
    && case "$arch" in \
        x86_64) machine="amd64" ;; \
        aarch64) machine="arm64" ;; \
        armhf) machine="arm" ;; \
        armv7) machine="arm" ;; \
        x86) machine="386" ;; \
       esac \
    && curl -sSL "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_${machine}.tar.gz" \
       | tar xz --strip-components=1 -C /usr/bin frp_${FRP_VERSION}_linux_${machine}/frpc

# Copy default configuration template
COPY defaults/ /defaults/

# Copy run script
COPY run.py /run.py
RUN chmod a+x /run.py

CMD ["/run.py"]
