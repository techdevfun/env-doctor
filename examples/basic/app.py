"""Minimal app that reads the vars from examples/basic/.env."""
import os

db = os.getenv("DATABASE_URL", "postgres://localhost:5432/myapp")
name = os.getenv("APP_NAME", "env-doctor-demo")
print(f"{name} -> {db}")
