"""Allow `python -m env_doctor check ...`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
