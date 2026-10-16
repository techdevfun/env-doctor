#!/bin/sh
# Fail CI when .env drifts from .env.example.
set -e
python -m env_doctor check --env .env --example .env.example --format text
