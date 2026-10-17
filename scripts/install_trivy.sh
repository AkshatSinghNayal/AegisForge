#!/usr/bin/env bash
set -euo pipefail
# Official v0.69.3 Linux x86_64 release, pinned by archive digest.
install_dir="${1:?Pass an output directory}"
mkdir -p "$install_dir"
curl --fail --location --retry 3 --output "$install_dir/trivy.tar.gz" \
  https://github.com/aquasecurity/trivy/releases/download/v0.69.3/trivy_0.69.3_Linux-64bit.tar.gz
printf '%s  %s\n' 1816b632dfe529869c740c0913e36bd1629cb7688bd5634f4a858c1d57c88b75 "$install_dir/trivy.tar.gz" | sha256sum --check -
tar -xzf "$install_dir/trivy.tar.gz" -C "$install_dir" trivy
