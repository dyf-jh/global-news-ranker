import json
import subprocess
from pathlib import Path
from datetime import datetime

import streamlit as st


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "outputs"
HISTORY_DIR = OUTPUT_DIR / "history"
LOG_DIR = PROJECT_DIR / "logs"

LATEST_JSON = OUTPUT_DIR / "latest.json"
LATEST_CSV = OUTPUT_DIR / "latest.csv"
LATEST_MD = OUTPUT_DIR / "latest.md"
LATEST_ZH_MD = OUTPUT_DIR / "latest_zh.md"
SCHEDULED_LOG = LOG_DIR / "scheduled_run.log"


st.set_page_config(
    page_title="Global News Ranker",
    layout="wide",
)


def decode_bytes(data):
    """Decode bytes from UTF-8, UTF-16, or Windows local code page."""
    if not data:
        return ""

    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace")

    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")

    # PowerShell 5.x logs are often UTF-16LE.
    sample = data[:2000]
    if sample.count(b"\x00") > len(sample) * 0.1:
        return data.decode("utf-16", errors="replace")

    encodings = ["utf-8-sig", "mbcs", "gbk", "cp936"]

    for enc in encodings:
        try:
            return data.decode(enc)
        except Exception:
            pass

    return data.decode("utf-8", errors="replace")


def read_text(path, max_chars=None):
    if not path.exists():
        return ""

    data = path.read_bytes()
    text = decode_bytes(data)

    if max_chars is not None and len(text) > max_chars:
        return text[-max_chars:]

    return text


def read_bytes(path):
    if not path.exists():
        return b""
    return path.read_bytes()


def read_json(path):
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("articles", "items", "data", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    return []


def run_command(command, timeout=900):
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_DIR),
            shell=True,
            capture_output=True,
            timeout=timeout,
        )

        output = ""
        if result.stdout:
            output += decode_bytes(result.stdout)
        if result.stderr:
            output += "\n[stderr]\n" + decode_bytes(result.stderr)

        return result.returncode, output.strip()

    except subprocess.TimeoutExpired:
        return 124, "Command timed out."
    except Exception as e:
        return 1, str(e)


def run_powershell_script(script_path):
    command = (
        'powershell.exe -NoProfile -ExecutionPolicy Bypass '
        f'-File "{script_path}"'
    )
    return run_command(command, timeout=1200)


def get_file_mtime(path):
    if not path.exists():
        return "N/A"

    ts = datetime.fromtimestamp(path.stat().st_mtime)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def build_metrics(articles):
    coverages = []
    sources = {}
    providers = {}

    for item in articles:
        try:
            coverage = int(item.get("cluster_count", 1) or 1)
        except Exception:
            coverage = 1

        coverages.append(coverage)

        source = item.get("source") or "unknown"
        provider = item.get("raw_provider") or item.get("provider") or "unknown"

        sources[source] = sources.get(source, 0) + 1
        providers[provider] = providers.get(provider, 0) + 1

    max_coverage = max(coverages) if coverages else 0
    multi_source = sum(1 for c in coverages if c >= 2)
    single_source = sum(1 for c in coverages if c <= 1)

    top_source = "N/A"
    if sources:
        item = sorted(sources.items(), key=lambda x: x[1], reverse=True)[0]
        top_source = f"{item[0]}: {item[1]}"

    return {
        "total": len(articles),
        "max_coverage": max_coverage,
        "multi_source": multi_source,
        "single_source": single_source,
        "source_count": len(sources),
        "top_source": top_source,
        "sources": sources,
        "providers": providers,
    }


def articles_table(articles):
    rows = []

    for item in articles:
        rows.append(
            {
                "rank": item.get("rank"),
                "title": item.get("title"),
                "source": item.get("source"),
                "hot_score": item.get("hot_score"),
                "coverage": item.get("cluster_count"),
                "provider": item.get("raw_provider") or item.get("provider"),
                "url": item.get("url"),
            }
        )

    return rows


def list_history_dates():
    if not HISTORY_DIR.exists():
        return []

    dates = [p.name for p in HISTORY_DIR.iterdir() if p.is_dir()]
    return sorted(dates, reverse=True)


def display_downloads():
    st.subheader("下载最新文件")

    files = [
        ("中文简报 latest_zh.md", LATEST_ZH_MD, "text/markdown"),
        ("英文报告 latest.md", LATEST_MD, "text/markdown"),
        ("表格 latest.csv", LATEST_CSV, "text/csv"),
        ("结构化数据 latest.json", LATEST_JSON, "application/json"),
    ]

    cols = st.columns(4)

    for idx, item in enumerate(files):
        label, path, mime = item
        with cols[idx]:
            if path.exists():
                st.download_button(
                    label=label,
                    data=read_bytes(path),
                    file_name=path.name,
                    mime=mime,
                    use_container_width=True,
                )
            else:
                st.button(label + " 不存在", disabled=True, use_container_width=True)


def display_task_status():
    code, output = run_command(
        'schtasks /Query /TN "GlobalNewsRankerDaily" /V /FO LIST',
        timeout=30,
    )

    if code == 0:
        st.code(output, language="text")
    else:
        st.warning("无法读取 Windows 计划任务状态。")
        st.code(output, language="text")


st.title("Global News Ranker 本地控制台")

articles = read_json(LATEST_JSON)
metrics = build_metrics(articles)

with st.sidebar:
    st.header("操作")

    if st.button("刷新页面", use_container_width=True):
        st.experimental_rerun()

    st.markdown("---")
    st.caption("手动运行")

    if st.button("运行完整流程", use_container_width=True):
        with st.spinner("正在运行 run_daily.ps1，可能需要 1-3 分钟..."):
            code, output = run_powershell_script(PROJECT_DIR / "run_daily.ps1")

        if code == 0:
            st.success("完整流程运行成功。")
        else:
            st.error(f"完整流程运行失败，ExitCode={code}")

        st.code(output[-8000:], language="text")

    if st.button("只生成中文简报", use_container_width=True):
        with st.spinner("正在生成中文简报..."):
            code, output = run_command("python generate_chinese_brief.py", timeout=600)

        if code == 0:
            st.success("中文简报生成成功。")
        else:
            st.error(f"中文简报生成失败，ExitCode={code}")

        st.code(output[-8000:], language="text")

    if st.button("只发送邮件", use_container_width=True):
        with st.spinner("正在发送邮件..."):
            code, output = run_command("python send_email_report.py", timeout=300)

        if code == 0:
            st.success("邮件发送成功。")
        else:
            st.error(f"邮件发送失败，ExitCode={code}")

        st.code(output[-8000:], language="text")

    st.markdown("---")
    st.caption("文件更新时间")
    st.write("latest.md:", get_file_mtime(LATEST_MD))
    st.write("latest_zh.md:", get_file_mtime(LATEST_ZH_MD))
    st.write("latest.json:", get_file_mtime(LATEST_JSON))


tabs = st.tabs(
    [
        "总览",
        "中文简报",
        "英文报告",
        "Top20 表格",
        "历史归档",
        "运行日志",
        "定时任务",
    ]
)


with tabs[0]:
    st.subheader("运行总览")

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    c1.metric("Final Events", metrics["total"])
    c2.metric("Max Coverage", metrics["max_coverage"])
    c3.metric("Multi-source", metrics["multi_source"])
    c4.metric("Single-source", metrics["single_source"])
    c5.metric("Source Count", metrics["source_count"])
    c6.metric("Top Source", metrics["top_source"])

    st.markdown("---")

    left, right = st.columns(2)

    with left:
        st.subheader("来源分布")
        if metrics["sources"]:
            st.table(
                [
                    {"source": k, "count": v}
                    for k, v in sorted(
                        metrics["sources"].items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                ]
            )
        else:
            st.info("暂无来源数据。")

    with right:
        st.subheader("Provider 分布")
        if metrics["providers"]:
            st.table(
                [
                    {"provider": k, "count": v}
                    for k, v in sorted(
                        metrics["providers"].items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                ]
            )
        else:
            st.info("暂无 Provider 数据。")

    st.markdown("---")
    display_downloads()


with tabs[1]:
    st.subheader("中文简报 latest_zh.md")

    text = read_text(LATEST_ZH_MD)

    if text:
        st.markdown(text)
    else:
        st.warning("未找到 outputs/latest_zh.md。")


with tabs[2]:
    st.subheader("英文报告 latest.md")

    text = read_text(LATEST_MD)

    if text:
        st.markdown(text)
    else:
        st.warning("未找到 outputs/latest.md。")


with tabs[3]:
    st.subheader("Top20 表格")

    if articles:
        st.dataframe(articles_table(articles), use_container_width=True)
    else:
        st.warning("未找到 outputs/latest.json 或数据为空。")


with tabs[4]:
    st.subheader("历史归档")

    dates = list_history_dates()

    if not dates:
        st.warning("暂无历史归档。")
    else:
        selected_date = st.selectbox("选择日期", dates)
        date_dir = HISTORY_DIR / selected_date

        st.write("目录：", str(date_dir))

        files = [
            ("中文简报", date_dir / "top20_zh.md"),
            ("英文报告", date_dir / "top20.md"),
            ("CSV", date_dir / "top20.csv"),
            ("JSON", date_dir / "top20.json"),
        ]

        cols = st.columns(4)

        for idx, item in enumerate(files):
            label, path = item
            with cols[idx]:
                if path.exists():
                    st.download_button(
                        label=f"下载 {label}",
                        data=read_bytes(path),
                        file_name=path.name,
                        use_container_width=True,
                    )
                else:
                    st.button(f"{label} 不存在", disabled=True, use_container_width=True)

        st.markdown("---")

        view_file = st.radio(
            "查看文件",
            ["top20_zh.md", "top20.md", "top20.csv", "top20.json"],
            horizontal=True,
        )

        target = date_dir / view_file

        if target.exists():
            if target.suffix == ".md":
                st.markdown(read_text(target))
            else:
                st.code(read_text(target, max_chars=50000), language="text")
        else:
            st.warning(f"{view_file} 不存在。")


with tabs[5]:
    st.subheader("自动运行日志 scheduled_run.log")

    max_chars = st.slider("显示日志末尾字符数", 5000, 50000, 15000, step=5000)

    log_text = read_text(SCHEDULED_LOG, max_chars=max_chars)

    if log_text:
        st.code(log_text, language="text")
    else:
        st.warning("未找到 logs/scheduled_run.log。")


with tabs[6]:
    st.subheader("Windows 定时任务状态")
    display_task_status()
