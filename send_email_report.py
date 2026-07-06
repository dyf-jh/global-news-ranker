import os
import sys
import smtplib
from pathlib import Path
from datetime import datetime
from email.message import EmailMessage


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "outputs"

LATEST_ZH = OUTPUT_DIR / "latest_zh.md"
LATEST_EN = OUTPUT_DIR / "latest.md"
LATEST_CSV = OUTPUT_DIR / "latest.csv"


def load_env():
    env_path = PROJECT_DIR / ".env"

    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value


def split_recipients(value: str):
    return [
        x.strip()
        for x in value.replace(";", ",").split(",")
        if x.strip()
    ]


def read_text_file(path: Path, max_chars: int = 6000) -> str:
    if not path.exists():
        return ""

    text = path.read_text(encoding="utf-8-sig", errors="replace").strip()

    if len(text) > max_chars:
        return text[:max_chars] + "\n\n……正文过长，完整内容请查看附件。"

    return text


def build_plain_body() -> str:
    zh_text = read_text_file(LATEST_ZH, max_chars=7000)

    if not zh_text:
        zh_text = "中文简报文件 outputs/latest_zh.md 不存在或为空。"

    return f"""今日全球热点新闻简报已生成。

生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

以下为中文简报预览：

{zh_text}

---
附件包含：
- latest_zh.md：中文简报
- latest.md：英文报告
- latest.csv：表格数据
"""


def attach_file(message: EmailMessage, path: Path):
    if not path.exists():
        return

    data = path.read_bytes()

    if path.suffix.lower() == ".csv":
        maintype = "text"
        subtype = "csv"
    elif path.suffix.lower() == ".md":
        maintype = "text"
        subtype = "markdown"
    else:
        maintype = "application"
        subtype = "octet-stream"

    message.add_attachment(
        data,
        maintype=maintype,
        subtype=subtype,
        filename=path.name,
    )


def send_email():
    load_env()

    smtp_host = get_required_env("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "465").strip())
    smtp_user = get_required_env("SMTP_USER")
    smtp_password = get_required_env("SMTP_PASSWORD")
    mail_to_raw = get_required_env("MAIL_TO")
    subject_prefix = os.environ.get("MAIL_SUBJECT_PREFIX", "Global News Ranker").strip()

    recipients = split_recipients(mail_to_raw)
    if not recipients:
        raise RuntimeError("MAIL_TO has no valid recipient.")

    today = datetime.now().strftime("%Y-%m-%d")
    subject = f"[{subject_prefix}] 全球热点新闻简报 {today}"

    message = EmailMessage()
    message["From"] = smtp_user
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject

    message.set_content(build_plain_body(), subtype="plain", charset="utf-8")

    attach_file(message, LATEST_ZH)
    attach_file(message, LATEST_EN)
    attach_file(message, LATEST_CSV)

    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=60) as server:
        server.login(smtp_user, smtp_password)
        server.send_message(message)

    print(f"Email sent -> {', '.join(recipients)}")


if __name__ == "__main__":
    try:
        send_email()
    except Exception as e:
        print(f"Email push failed: {e}", file=sys.stderr)
        sys.exit(1)
