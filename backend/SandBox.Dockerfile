# ============================================================================
# Heyu Agent Sandbox Image
# ============================================================================
# 基于 DeerFlow all-in-one-sandbox 镜像，预装 skill 运行时依赖。
#
# 当前为「精简版」：保留数据分析（pandas/numpy/duckdb）+ 文档读取（python-docx）
# + Node.js（图表）依赖。
# 其余（ppt-master 文档/图形/格式转换、AI 调用、skill-creator 等）均已注释掉，
# 需要时取消对应注释即可恢复。
#
# 构建:
#   docker build -t skillhub-sandbox:latest -f docker/image/Dockerfile .
#
# 推送到华为云 SWR:
#   docker tag skillhub-sandbox:latest swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:<tag>
#   docker push swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:<tag>
#
# config.yaml 配置:
#   sandbox:
#     image: swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:<tag>
# ============================================================================

FROM enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest

# ── pip 镜像 + 超时配置 ───────────────────────────────────────────────────
# 基础镜像可能有旧版 distutils 包 (如 blinker 1.4)，--ignore-installed 避免卸载冲突。
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
    && pip config set global.trusted-host mirrors.aliyun.com \
    && pip config set global.timeout 300 \
    && pip config set global.retries 5

# ── 系统包 ─────────────────────────────────────────────────────────────────
# Node.js 18.x — chart-visualization skill (generate.js, 纯 Node 标准库)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y --no-install-recommends \
    nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && node --version && npm --version

# ── Python 包（精简版）────────────────────────────────────────────────────
# 所有 pip install 统一加 --ignore-installed，防止基础镜像中 distutils 旧版
# (如 blinker 1.4) 导致的 Cannot uninstall 错误。

# ---- 数据分析（保留）----
RUN pip install --no-cache-dir --ignore-installed \
    pandas \
    numpy \
    duckdb

# ---- 文档读取（保留，docx）----
RUN pip install --no-cache-dir --ignore-installed \
    python-docx>=1.0 \
    lxml

# ════════════════════════════════════════════════════════════════════════════
# 以下依赖已移除，需要时取消注释恢复（按 skill 分组）
# ════════════════════════════════════════════════════════════════════════════

# # ---- 系统包：ffmpeg / pandoc（ppt-master）----
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     ffmpeg \
#     pandoc \
#     && apt-get clean \
#     && rm -rf /var/lib/apt/lists/* \
#     && ffmpeg -version | head -1

# # ---- PPT 生成（ppt-master）----
# RUN pip install --no-cache-dir --ignore-installed \
#     python-pptx>=0.6.21

# # ---- Excel 文件读写（openpyxl / XlsxWriter）----
# RUN pip install --no-cache-dir --ignore-installed \
#     openpyxl>=3.1.0 \
#     XlsxWriter>=3.0.0

# # ---- 格式转换（ppt-master source_to_md）----
# RUN pip install --no-cache-dir --ignore-installed \
#     PyMuPDF>=1.23.0 \
#     mammoth>=1.6.0 \
#     markdownify>=0.11.6 \
#     ebooklib>=0.18 \
#     nbconvert>=7.0.0

# # ---- 图片 / 图形（ppt-master）----
# RUN pip install --no-cache-dir --ignore-installed \
#     Pillow>=9.0.0 \
#     skia-pathops>=0.9.2 \
#     cairosvg \
#     svglib \
#     reportlab

# # ---- AI / API 调用 ----
# RUN pip install --no-cache-dir --ignore-installed \
#     requests>=2.31.0 \
#     beautifulsoup4>=4.12.0 \
#     curl_cffi>=0.7.0 \
#     google-genai>=1.0.0 \
#     edge-tts>=7.2.8 \
#     flask>=3.0.0 \
#     tiktoken

# # ---- skill-creator ----
# RUN pip install --no-cache-dir --ignore-installed pyyaml

# # ---- Playwright（可选，仅 ppt-master visual review 需要）----
# RUN pip install --no-cache-dir --ignore-installed playwright \
#     && playwright install chromium \
#     && playwright install-deps chromium

# # ---- 视频字幕 stable-ts（可选，仅 ppt-master video_subtitles.py 需要）----
# RUN pip install --no-cache-dir --ignore-installed stable-ts

# ── 验证 ───────────────────────────────────────────────────────────────────
RUN python -c "import pandas, numpy, duckdb, docx; print('Data/Docx: OK')" \
    && node -e "console.log('Node.js:', process.version)" \
    && echo "=== All checks passed ==="
