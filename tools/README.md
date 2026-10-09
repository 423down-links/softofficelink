# tools/ 说明

这里不放二进制。check_versions.py 会按以下优先级自动找 7z：

1. `tools/7zz`（本地可选，自己拷贝一份放这）
2. 系统路径里的 `7z / 7za / 7zz`（CI 环境 apt install p7zip-full 就能用）
3. `py7zr`（纯 Python，pip install py7zr 即可，check_versions.py 内的 NSIS 版本解析用）

CI 里已经配置好了 `apt-get install p7zip-full` + `pip install py7zr`，不需要额外放二进制。
