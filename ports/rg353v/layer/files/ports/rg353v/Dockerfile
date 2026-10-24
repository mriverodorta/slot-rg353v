# Match upstream's conservative glibc baseline (Debian bullseye, glibc 2.31).
FROM rust:1.96.1-bullseye@sha256:21d112adb6ab370d39eef8f861f10b42342419b9569e7a05dac15e19eb65a3b4
RUN printf '%s\n' \
       'deb https://snapshot.debian.org/archive/debian/20260623T000000Z bullseye main' \
       'deb https://snapshot.debian.org/archive/debian/20260623T000000Z bullseye-updates main' \
       'deb https://snapshot.debian.org/archive/debian-security/20260623T000000Z bullseye-security main' \
       > /etc/apt/sources.list \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install -y --no-install-recommends \
       cmake pkg-config libsdl2-2.0-0 libegl1-mesa libgles2-mesa \
       libgl1-mesa-dri libasound2 libasound2-dev libudev-dev xvfb xauth file \
    && rm -rf /var/lib/apt/lists/*
RUN rustup component add clippy rustfmt
WORKDIR /src
