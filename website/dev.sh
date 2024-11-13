#!/bin/bash

export AWS_PROFILE=sonde-notifier
(cd frontend && bundle exec jekyll serve --config _config.yml,_config_dev.yml -) & (conda run --live-stream -n sondesearch ./backend/src/v2.py)


