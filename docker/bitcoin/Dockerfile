FROM archlinux:base

RUN pacman -Sy --noconfirm --needed \
      bash \
      ca-certificates \
      capnproto \
      iproute2 \
      libevent \
      procps-ng \
      sqlite \
    && pacman -Scc --noconfirm

ENV BITCOIN_DATA=/root/.bitcoin

COPY bin/bitcoind /usr/local/bin/bitcoind
COPY bin/bitcoin-cli /usr/local/bin/bitcoin-cli
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /usr/local/bin/bitcoind /usr/local/bin/bitcoin-cli /entrypoint.sh \
    && ln -sf /usr/local/bin/bitcoind /usr/bin/bitcoind \
    && ln -sf /usr/local/bin/bitcoin-cli /usr/bin/bitcoin-cli

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bitcoind"]
