#!/bin/sh
# Run this in the owner's Terminal. Elevate only Apple's telemetry executable.
set -eu
umask 077
if [ "$#" -ne 1 ]; then
  printf 'Usage: %s /absolute/measurement-root\n' "$0" >&2
  exit 2
fi
measurement_root=$1
case "$measurement_root" in
  /*) ;;
  *) printf 'Measurement root must be absolute.\n' >&2; exit 2 ;;
esac
mkdir -p "$measurement_root"
measurement_dir=$(mktemp -d "$measurement_root/power-XXXXXXXX")
printf 'Power log: %s/power.plist\n' "$measurement_dir"
printf 'Keep this Terminal open. Capture stops after 30 minutes; Ctrl-C stops it sooner.\n'
printf 'CPU/GPU/ANE telemetry estimates chip energy, not whole-machine wall energy.\n'
# The unprivileged shell opens the file, so it stays readable by the owner.
exec /usr/bin/sudo /usr/bin/powermetrics \
    --samplers cpu_power,gpu_power,ane_power \
    --sample-rate 1000 --sample-count 1800 --format plist --buffer-size 0 \
    > "$measurement_dir/power.plist"
