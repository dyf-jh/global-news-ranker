import os

def load_dotenv(dotenv_path=".env", override=False, encoding="utf-8"):
    if not os.path.exists(dotenv_path):
        return False

    with open(dotenv_path, "r", encoding=encoding) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and (override or key not in os.environ):
                os.environ[key] = value

    return True
