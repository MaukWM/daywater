FROM --platform=linux/amd64 debian:12

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      dolphin-emu \
      xvfb \
      xauth \
      mesa-utils \
      libgl1-mesa-dri \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 dolphin
USER dolphin
WORKDIR /home/dolphin

RUN mkdir -p /home/dolphin/.config/dolphin-emu \
             /home/dolphin/.local/share/dolphin-emu/StateSaves \
             /home/dolphin/.local/share/dolphin-emu/Dump/Frames \
             /home/dolphin/.local/share/dolphin-emu/GameSettings \
             /home/dolphin/iso

COPY --chown=dolphin:dolphin Dolphin.ini /home/dolphin/.config/dolphin-emu/Dolphin.ini
COPY --chown=dolphin:dolphin GFX.ini     /home/dolphin/.config/dolphin-emu/GFX.ini
COPY --chown=dolphin:dolphin entrypoint.sh /home/dolphin/entrypoint.sh

ENTRYPOINT ["/home/dolphin/entrypoint.sh"]
