# Mock TP-Link JetStream switch: SSH server whose login shell is a fake JetStream
# CLI REPL backed by a persisted running/startup config (configuration plane),
# plus an SNMPv3 agent on UDP/161 (monitoring plane, never SSH). SSH target for
# the real JetStreamCliAdapter; SNMP target for the real
# JetStreamSnmpMonitoringProvider.
FROM alpine:3.19

RUN apk add --no-cache openssh-server python3 tini net-snmp net-snmp-tools \
    && ssh-keygen -A \
    && mkdir -p /var/lib/mockdev /var/lib/net-snmp

COPY bin/jetstream-cli /usr/bin/jetstream-cli
COPY bin/fdb-pass /usr/bin/fdb-pass
RUN chmod +x /usr/bin/jetstream-cli /usr/bin/fdb-pass

COPY seed/ /usr/share/mockdev-seed/

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV MOCK_SSH_USER=admin \
    MOCK_SSH_PASSWORD=admin \
    MOCK_STATE_DIR=/var/lib/mockdev \
    MOCK_SNMP_USER=hsncmon \
    MOCK_SNMP_AUTH_KEY=hsncauth123 \
    MOCK_SNMP_PRIV_KEY=hsncpriv123

# 22 = configuration plane (SSH); 161/udp = monitoring plane (SNMPv3).
EXPOSE 22 161/udp
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
