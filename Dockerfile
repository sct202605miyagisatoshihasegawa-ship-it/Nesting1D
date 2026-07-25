FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        bubblewrap \
        ca-certificates \
        curl \
        git \
        openssh-client \
        procps \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN useradd \
    --create-home \
    --uid 1000 \
    --shell /bin/bash \
    developer \
    && mkdir -p \
        /workspace/nesting1d \
        /home/developer/.codex \
    && chown -R developer:developer \
        /workspace/nesting1d \
        /home/developer

USER developer

ENV HOME="/home/developer"
ENV PATH="/home/developer/.local/bin:${PATH}"

WORKDIR /workspace/nesting1d

RUN curl -fsSL https://chatgpt.com/codex/install.sh | sh

CMD ["sleep", "infinity"]
