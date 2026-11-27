#!/usr/bin/env bash
# 推 main 带防护（审计项 1/2/4）：
#   ① 凭据拦截：tokens.env / 私钥被 git 跟踪就拒绝推送
#   ② 版本集体倒退熔断：对照远端 main 的 data.json（tools/check_no_rollback.py）
#   ③ push 竞态重试：被拒（并发轮次抢跑）→ fetch+rebase 重试，最多 3 次；
#      rebase 冲突按文件类型自动解决——*cache.json 取本地新缓存、
#      data.json/index.html 取远端（另一轮更新鲜的检测结果），其余冲突交给人
set -euo pipefail

# ① 凭据卫生
if git ls-files --cached | grep -E '(^|/)(tokens\.env|id_ed25519|id_rsa)$' >/dev/null; then
  echo "::error::凭据文件被 git 跟踪，拒绝推送："
  git ls-files | grep -E '(^|/)(tokens\.env|id_ed25519|id_rsa)$'
  exit 1
fi

# ② 版本集体倒退熔断（对照远端；远端还没有 data.json 时跳过）
git fetch origin main
if git show origin/main:data.json > /tmp/push_base_data.json 2>/dev/null; then
  python3 tools/check_no_rollback.py /tmp/push_base_data.json data.json --threshold 3
fi

# ③ push 竞态重试
for i in 1 2 3; do
  if git push origin HEAD:main; then
    echo "push OK（第 ${i} 次尝试）"
    exit 0
  fi
  echo "push 被拒（并发轮次抢跑），fetch+rebase 后重试（${i}/3）..."
  git fetch origin main
  if ! git rebase origin/main; then
    conflicted=$(git diff --name-only --diff-filter=U || true)
    other=''
    for f in $conflicted; do
      case "$f" in
        *cache.json)      git checkout --theirs -- "$f" ;;   # rebase 中 theirs=本地提交（更新的缓存）
        data.json|index.html) git checkout --ours -- "$f" ;; # 取远端（另一轮的检测结果）
        *) other="$other $f" ;;
      esac
      git add -- "$f"
    done
    if [ -n "$other" ]; then
      echo "::error::非缓存/数据文件冲突，中止（人工处理）: $other"
      git rebase --abort || true
      exit 1
    fi
    GIT_EDITOR=true git rebase --continue
  fi
  sleep $((i * 5))
done
echo "::error::push 重试 3 次仍失败"
exit 1
