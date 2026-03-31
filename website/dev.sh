#!/bin/bash
set -euo pipefail

source ~/miniforge3/etc/profile.d/conda.sh
export AWS_PROFILE=sonde-notifier

trap 'kill 0' EXIT

(cd frontend && bundle exec jekyll serve --config _config.yml,_config_dev.yml -) &
conda run --live-stream -n sondesearch ./backend/src/v2.py &

wait -n
