# Mock OpenWrt device: SSH server exposing fake `uci` + `ubus` over a persisted
# UCI-style state file (configuration plane), plus a Prometheus node-exporter on
# :9100 (monitoring plane, never SSH). SSH target for the real OpenWrtSshAdapter;
# scrape target for the real OpenWrtPrometheusMonitoringProvider.
FROM alpine:3.19

RUN apk add --no-cache openssh-server python3 tini \
    && ssh-keygen -A \
    && mkdir -p /var/lib/mockdev

# Fake OpenWrt tooling on PATH.
COPY bin/uci /usr/bin/uci
COPY bin/ubus /usr/bin/ubus
COPY bin/node-exporter /usr/bin/node-exporter
RUN chmod +x /usr/bin/uci /usr/bin/ubus /usr/bin/node-exporter

# Seed state baked into the image; copied to the state volume on first boot.
COPY seed/ /usr/share/mockdev-seed/

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Credentials are (re)applied at runtime from env in the entrypoint.
ENV MOCK_SSH_USER=root \
    MOCK_SSH_PASSWORD=openwrt \
    MOCK_STATE_DIR=/var/lib/mockdev

# 22 = configuration plane (SSH); 9100 = monitoring plane (Prometheus).
EXPOSE 22 9100
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
