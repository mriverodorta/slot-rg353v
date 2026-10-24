FROM slot-rg353v-image-tools:latest
RUN apt-get update && apt-get install -y --no-install-recommends build-essential liblz4-dev openssh-client \
    && rm -rf /var/lib/apt/lists/*
