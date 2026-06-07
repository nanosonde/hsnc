# Mock TP-Link JetStream switch: SSH server whose login shell is a fake JetStream
# CLI REPL backed by a persisted running/startup config. SSH target for the real
# JetStreamCliAdapter.
FROM alpine:3.19

RUN apk add --no-cache openssh-server python3 tini \
    && ssh-keygen -A \
    && mkdir -p /var/lib/mockdev

COPY bin/jetstream-cli /usr/bin/jetstream-cli
RUN chmod +x /usr/bin/jetstream-cli

COPY seed/ /usr/share/mockdev-seed/

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV MOCK_SSH_USER=admin \
    MOCK_SSH_PASSWORD=admin \
    MOCK_STATE_DIR=/var/lib/mockdev

EXPOSE 22
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
