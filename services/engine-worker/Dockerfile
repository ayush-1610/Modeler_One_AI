# syntax=docker/dockerfile:1.7
# Engine image: R 4.6.1 + ospsuite 12.4.4 (PK-Sim 12.3.173) + parameter identification 2.2.0 + .NET 8 runtime
# + the Python activity worker. One image per engine version, referenced by digest only.
#
# Build from the repository root (x86-64 target, the compute servers' architecture):
#   docker build --platform linux/amd64 -f services/engine-worker/Dockerfile -t modeler-engine:ospsuite-12.4.4 .
#
# R packages come as prebuilt Ubuntu 24.04 (noble) binaries: CRAN packages from Posit Package Manager (rocker's
# default repo) and OSP packages from the OSP r-universe Linux binary repository, except ospsuite itself, which is
# installed from its release commit (below). Production builds pin the base image by digest (docs/ENGINEERING_PLAN.md §9).

ARG R_VERSION=4.6.1
FROM rocker/r-ver:${R_VERSION}

ARG DOTNET_CHANNEL=8.0
ARG OSP_LINUX_BINARIES=https://open-systems-pharmacology.r-universe.dev/bin/linux/noble-x86_64/4.6

ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    DOTNET_ROOT=/opt/dotnet \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 \
    PATH=/opt/dotnet:/opt/venv/bin:$PATH \
    LD_LIBRARY_PATH=/usr/local/lib/R/site-library/ospsuite/lib

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl locales python3 python3-venv \
      libicu74 libxml2 libssl3 libcurl4 libfontconfig1 libfreetype6 libharfbuzz0b libfribidi0 \
      libpng16-16 libjpeg-turbo8 libtiff6 libgomp1 \
 && sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen \
 && curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
 && bash /tmp/dotnet-install.sh --runtime dotnet --channel "${DOTNET_CHANNEL}" --install-dir /opt/dotnet \
 && rm -rf /var/lib/apt/lists/* /tmp/dotnet-install.sh

# The qualified engine (T-01, golden/catalog.json "engine"): ospsuite 12.4.4, PI 2.2.0, rSharp 1.2.2 on .NET 8. The
# repositories serve their newest builds, so rSharp is replaced by its tagged 1.2.2 release (2.x needs .NET 10), and
# the build fails if any version differs: an image that is not the qualified engine must never be produced.
# The r-universe serves only the newest ospsuite (12.4.5 since October 2026, which the version check refused), so
# ospsuite 12.4.4 is installed from its release commit ("Release 12.4.4", OSPSuite-R #1995): the release ships its
# .NET and native libraries in inst/lib, so its source installs as is. The source tree's .Rprofile starts renv, which
# the package's configure step would run; it is removed first. The archive must match the sha256 of the first
# qualified build (CI run 37609508306, 2026-10-07): a changed archive fails the build instead of installing.
ARG OSPSUITE_VERSION=12.4.4
ARG OSPSUITE_COMMIT=4f37d444ef1a299ba72ffc418ee82f049db89dd8
ARG OSPSUITE_SHA256=87f9fb388b242906d59d2e4a5e6d8d5ae6c2e5932b194f39684553376c9efb05
ARG PI_VERSION=2.2.0
ARG RSHARP_VERSION=1.2.2
RUN Rscript -e "options(repos = c(osp = '${OSP_LINUX_BINARIES}', getOption('repos'))); \
                install.packages(c('jsonlite', 'digest', 'ospsuite', 'ospsuite.parameteridentification'))" \
 && curl -fsSL "https://github.com/Open-Systems-Pharmacology/OSPSuite-R/archive/${OSPSUITE_COMMIT}.tar.gz" \
      -o /tmp/ospsuite.tar.gz \
 && echo "${OSPSUITE_SHA256}  /tmp/ospsuite.tar.gz" | sha256sum -c - \
 && mkdir /tmp/ospsuite && tar -xzf /tmp/ospsuite.tar.gz -C /tmp/ospsuite --strip-components=1 \
 && rm -rf /tmp/ospsuite/.Rprofile /tmp/ospsuite/renv /tmp/ospsuite/renv.lock \
 && R CMD INSTALL /tmp/ospsuite && rm -rf /tmp/ospsuite /tmp/ospsuite.tar.gz \
 && curl -fsSL "https://github.com/Open-Systems-Pharmacology/rSharp/archive/refs/tags/v${RSHARP_VERSION}.tar.gz" \
      -o /tmp/rSharp.tar.gz \
 && R CMD INSTALL /tmp/rSharp.tar.gz && rm -f /tmp/rSharp.tar.gz \
 && Rscript -e "want <- c(ospsuite = '${OSPSUITE_VERSION}', ospsuite.parameteridentification = '${PI_VERSION}', \
                          rSharp = '${RSHARP_VERSION}'); \
                got <- vapply(names(want), function(p) as.character(packageVersion(p)), ''); \
                print(got); if (!identical(unname(got), unname(want))) stop('engine versions differ from the qualified set')"

RUN python3 -m venv /opt/venv
COPY packages/run-contracts /src/packages/run-contracts
COPY services/engine-worker /src/services/engine-worker
RUN pip install --no-cache-dir /src/packages/run-contracts /src/services/engine-worker

COPY services/engine-worker/r/ /engine/
COPY services/engine-worker/golden/ /engine/golden/

RUN useradd --uid 10001 --create-home engine
USER 10001
# PK-Sim writes into the current directory on initialization; the worker runs every job in its own scratch dir,
# and ad-hoc `docker run` commands need a writable default.
WORKDIR /home/engine
ENV MODELER_ENGINE_COMMAND="Rscript /engine/run_job.R"
CMD ["python", "-m", "modeler_engine.worker"]
