$ErrorActionPreference = "Stop"

$ProjectDir = "C:\Users\Administrator\Desktop\news20\fixed_clean\global-news-ranker_fixed"

Set-Location $ProjectDir

python -m streamlit run app_ui.py --server.address 127.0.0.1 --server.port 8501
