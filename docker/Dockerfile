FROM lscr.io/linuxserver/chromium:latest AS build

# ──────────────────────────────────────────────────────────────
# LinkCage - Hardened Chromium Sandbox Image
# Goals:
#   1. Patch every *fixable* CVE (full Debian security upgrade).
#   2. Strip every tool a streamed, sandboxed browser does not need
#      at runtime — purging packages (not just deleting files) so the
#      CVEs leave the dpkg database, not just the filesystem.
# ──────────────────────────────────────────────────────────────

# Remove the NodeSource repo (GPG key rejected by Debian sqv policy)
RUN rm -f /etc/apt/sources.list.d/nodesource.list /etc/apt/sources.list.d/nodesource.sources 2>/dev/null || true

# Purge packages a sandboxed browser never needs, then autoremove the orphans
# they leave behind. Removing them from the dpkg database (not just deleting
# files) is what actually clears their CVEs, and it shrinks the attack surface:
# exim4 is a mail transfer agent, openssh-client a network client, Xwayland and
# the Wayland stack it pulls in are unused under the image's Xvfb/openbox (X11)
# display server, and linux-libc-dev is compile-time only. autoremove also
# clears the now-orphaned libunbound8 (2 CRITICAL, no fix) brought in by
# libgnutls-dane.
#
# NOTE: do NOT purge libheif — openbox's render library depends on it
# transitively (openbox -> libobrender32v5 -> libimlib2 -> libheif1), so
# removing libheif drags the window manager out with it and breaks the desktop.
RUN apt-get update && \
    apt-get purge -y \
        exim4-base exim4-config exim4-daemon-light \
        openssh-client \
        xwayland \
        linux-libc-dev \
    && apt-get autoremove -y --purge \
    && rm -rf /var/lib/apt/lists/*

# Patch all remaining packages to the latest Debian security updates.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get dist-upgrade -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Patch Python package CVEs (Selkies virtualenv)
RUN if command -v /lsiopy/bin/pip > /dev/null 2>&1; then \
        /lsiopy/bin/pip install --no-cache-dir --upgrade \
            cryptography \
            pillow \
            pyopenssl \
            setuptools; \
    fi

# ── Strip unnecessary bloat / leftover tooling ───────────────
RUN \
    # Docker engine + CLI plugins. buildx/compose are static Go binaries that
    # carry their own CVEs and are never needed for sandboxed browsing.
    rm -rf /usr/libexec/docker \
    && rm -f /usr/bin/dockerd /usr/bin/containerd /usr/bin/docker \
          /usr/bin/ctr /usr/bin/runc /usr/bin/containerd-shim-runc-v2 \
          /usr/bin/docker-proxy \
    # CMake (63MB) - build tool, not needed at runtime
    && rm -f /usr/bin/cmake /usr/bin/cpack /usr/bin/ctest \
    && rm -rf /usr/share/cmake* \
    # GCC/binutils leftovers (34MB)
    && rm -f /usr/bin/x86_64-linux-gnu-lto-dump-14 \
    && rm -rf /usr/lib/x86_64-linux-gnu/ldscripts \
    # Chromium locales - keep only English (saves ~110MB)
    && find /usr/lib/chromium/locales -type f ! -name 'en-US.*' -delete 2>/dev/null || true \
    # System locales (114MB) - keep only English
    && find /usr/share/locale -mindepth 1 -maxdepth 1 -type d ! -name 'en' ! -name 'en_US' -exec rm -rf {} + \
    # i18n data (17MB)
    && rm -rf /usr/share/i18n \
    # Fonts - keep basic Latin fonts, remove CJK and others (saves ~130MB)
    && rm -rf /usr/share/fonts/opentype/noto \
              /usr/share/fonts/opentype/urw-base35 \
              /usr/share/fonts/type1 \
              /usr/share/fonts/cmap /usr/share/fonts/cMap \
              /usr/share/fonts/X11/encodings \
    # Documentation and man pages (13MB)
    && rm -rf /usr/share/doc/* /usr/share/man/* \
    # Misc share dirs not needed at runtime
    && rm -rf /usr/share/poppler /usr/share/terminfo \
              /usr/share/bash-completion /usr/share/perl \
    # Python test files
    && find /lsiopy -type d \( -name tests -o -name test \) -exec rm -rf {} + 2>/dev/null || true \
    && find /lsiopy -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true \
    # Apt and dpkg caches
    && rm -rf /var/cache/apt/* /var/lib/apt/lists/* \
    # Clear log contents but preserve directory structure (nginx needs /var/log/nginx/)
    && find /var/log -type f -delete

# Flatten into a single layer
FROM scratch
COPY --from=build / /

# Restore environment variables lost during flatten
ENV PATH=/lsiopy/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/config \
    LANGUAGE=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    TERM=xterm \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_VERBOSITY=1 \
    S6_STAGE2_HOOK=/docker-mods \
    VIRTUAL_ENV=/lsiopy \
    DISPLAY=:1 \
    PERL5LIB=/usr/local/bin \
    START_DOCKER=false \
    PULSE_RUNTIME_PATH=/defaults \
    SELKIES_INTERPOSER=/usr/lib/selkies_joystick_interposer.so \
    NVIDIA_DRIVER_CAPABILITIES=all \
    DISABLE_ZINK=false \
    DISABLE_DRI3=false \
    TITLE=Chromium \
    LSIO_FIRST_PARTY=true

LABEL org.opencontainers.image.title="LinkCage Sandbox" \
      org.opencontainers.image.description="Hardened Chromium browser for safely opening untrusted links" \
      org.opencontainers.image.authors="Luis Yax" \
      org.opencontainers.image.source="https://hub.docker.com/r/luisyax/linkcage-sandbox"

EXPOSE 3000 3001
VOLUME /config
ENTRYPOINT ["/init"]
