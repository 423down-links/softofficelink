#!/bin/bash
# 423down 安全规则命中分析（在服务器上跑：bash waf_hit_analysis.sh [YYYY-MM-DD] [起小时] [止小时]）
# 只读脚本：不删文件、不改配置、不解封。输出=封禁统计 + 验证码命中 + 误封嫌疑清单。
# 服务器无 python3，全部用 awk/grep/ipset/fail2ban-regex。
D=${1:-$(date +%F)}                      # 2026-09-28
H1=${2:-19}; H2=${3:-23}
LOG=/www/wwwlogs/www.423down.com-access.log
BLOG=/www/wwwlogs/wpcontent_blocked.log
F2B=/var/log/fail2ban.log
DL=$(echo "$D" | awk -F- '{m=strftime("%d/%b/%Y", mktime($1" "$2" "$3" 0 0 0")); print m}')
W=/tmp/f2ban_win_$$.txt

echo "== 0. 时间窗 $D $H1:00-$H2:00 （$DL）=="

# 1. fail2ban 窗口内事件/封禁
awk -v DD="$D" -v A="$H1" -v B="$H2" '$1==DD{h=substr($2,1,2)+0; if(h>=A && h<=B) print}' $F2B > $W
echo "== 1. 窗口内 fail2ban 事件 =="
awk '{for(i=1;i<=NF;i++) if($i ~ /^\[[a-z0-9-]+\]$/) j=$i;
      if($0 ~ /\] Ban /) ev="BAN"; else if($0 ~ /Unban|Restore Ban/) ev="RESTORE/UNBAN";
      else if($0 ~ /Found/) ev="FOUND"; else next; print ev, j}' $W | sort | uniq -c | sort -rn
echo "-- 窗口内被封 IP → 所属 jail --"
awk '/\] Ban /{for(i=1;i<=NF;i++) if($i ~ /^\[[a-z0-9-]+\]$/) j=substr($i,2,length($i)-2);
     for(k=NF;k>=1;k--) if($k ~ /^[0-9.]+$/){print j, $k; break}}' $W | sort -u > /tmp/banw_$$.txt
awk '{print $1}' /tmp/banw_$$.txt | sort | uniq -c | sort -rn
echo "-- 全天各 jail 封禁次数 --"
awk -v DD="$D" '$1==DD && /\] Ban /{for(i=1;i<=NF;i++) if($i ~ /^\[[a-z0-9-]+\]$/) j=$i; c[j]++}
     END{for(k in c) print k, c[k]}' $F2B

# 2. 被封 IP 行为画像（判断是否真人：有没有正常读过内容页）
echo "== 2. 窗口被封 IP 画像（全天日志）=="
awk -v DL="$DL" 'FNR==NR{w[$2]=w[$2]","$1; next}
     substr($4,2,11)==DL && ($1 in w){
       c[$1]++; if($9==200 && ($7 ~ /\.html$/ || $7 ~ /^\/page\// || $7 ~ /^\/search\// || $7=="/")) hum[$1]++;
       if($9>=400){ e[$1]++; if(es[$1]<3){es[$1]++; s[$1]=s[$1]" | "$9" "substr($7,1,40)} } }
     END{for(ip in w) printf "%-16s|%-30s|req=%-5s|正常内容页=%-4s|4xx=%-4s%s\n", ip, substr(w[ip],2), c[ip]+0, hum[ip]+0, e[ip]+0, s[ip]}' \
     /tmp/banw_$$.txt $LOG | sort -t'|' -k4 -rn

# 3. 安全验证码（标记文件 → 302 /verify）
echo "== 3. 验证码链路（全天）=="
awk -v DL="$DL" 'substr($4,2,11)==DL && $7 ~ /^\/verify\//{split($7,a,"?"); print a[1], $9}' $LOG | sort | uniq -c | sort -rn | head -12
awk -v DL="$DL" 'substr($4,2,11)==DL && $7 ~ /^\/verify\/index\.html/{v[$1]++} END{for(i in v) print v[i], i}' $LOG | sort -rn > /tmp/vidx_$$.txt
echo "-- 打开过验证页的独立IP数：$(wc -l < /tmp/vidx_$$.txt) --"
awk '{print $2}' /tmp/vidx_$$.txt | sort -u > /tmp/vips_$$.txt
awk -v DL="$DL" 'FNR==NR{w[$1]=1;next} substr($4,2,11)==DL && ($1 in w){
     if($7 ~ /\/verify\/action/) a[$1]++; if($7 ~ /\/verify\/allow/) al[$1]++;
     if($7 ~ /\/verify\/index/) p[$1]++;
     if($9==200 && ($7 ~ /\.html$/ || $7=="/" || $7 ~ /^\/page\//)) ok[$1]++ }
     END{for(ip in w) if(a[ip]>0) printf "提交过验证码 %s page=%s action=%s allow=%s 之后正常页=%s\n", ip, p[ip], a[ip], al[ip], ok[ip]+0}' \
     /tmp/vips_$$.txt $LOG | sort
echo "-- 当前标记文件（=此刻仍被要求验证码的IP）--"; ls -1 /run/f2b_block_* /run/f2b_state/ 2>/dev/null

# 4. 命中规则的文件/路径
echo "== 4. 窗口内 4xx 命中路径 Top20 =="
awk -v DL="$DL" -v A=$H1 -v B=$H2 'substr($4,2,11)==DL && substr($4,14,2)+0>=A && substr($4,14,2)+0<=B && $9>=400{p=$7; sub(/\?.*/,"",p); print $9, p}' $LOG | sort | uniq -c | sort -rn | head -20
echo "== 5. wp-content PHP 黑名单命中（wpcontent_blocked.log）=="
awk -v DL="$DL" -v A=$H1 -v B=$H2 'substr($4,2,11)==DL && substr($4,14,2)+0>=A && substr($4,14,2)+0<=B{print $1, $7}' $BLOG 2>/dev/null | sort | uniq -c | sort -rn | head -10

# 5. 网络层封禁现状 + 误封筛查
echo "== 6. ipset 当前封禁规模 =="
for s in f2b-sshd f2b-wordpress-high f2b-wordpress-medium f2b-perm-web f2b-perm-blacklist f2b-wordpress-bruteforce; do
  printf "%s=%s " "$s" "$(ipset list $s 2>/dev/null | sed -n '/^Members:/,$p' | tail -n +2 | grep -c .)"; done; echo
for s in f2b-wordpress-high f2b-wordpress-medium f2b-perm-web; do
  ipset list $s 2>/dev/null | sed -n '/^Members:/,$p' | tail -n +2 | awk '{print $1}'; done | sort -u > /tmp/netb_$$.txt
echo "-- 现在被封、但今天有 >=5 次正常内容页 200 的IP（误封嫌疑）-- 封禁IP总数=$(wc -l < /tmp/netb_$$.txt)"
awk -v DL="$DL" 'FNR==NR{w[$1]=1;next} substr($4,2,11)==DL && ($1 in w) && $9==200 &&
     ($7 ~ /\.html$/ || $7 ~ /^\/page\// || $7 ~ /^\/search\// || $7=="/"){c[$1]++}
     END{for(ip in c) if(c[ip]>=5) print ip, c[ip]}' /tmp/netb_$$.txt $LOG | sort -k2 -rn | head -20
echo "-- 上面这些IP还剩多少秒解封 --"
while read ip rest; do for s in f2b-wordpress-high f2b-wordpress-medium f2b-perm-web; do
  t=$(ipset list $s 2>/dev/null | grep "^$ip " | sed -E 's/.*timeout ([0-9]+).*/\1/');
  [ -n "$t" ] && echo "$ip $s ${t}s"; done; done < <(awk -v DL="$DL" 'FNR==NR{w[$1]=1;next}
     substr($4,2,11)==DL && ($1 in w) && $9==200 && ($7 ~ /\.html$/||$7=="/"){c[$1]++}
     END{for(ip in c) if(c[ip]>=5) print ip}' /tmp/netb_$$.txt $LOG | head -20)

# 6. 流量基线（判断有没有"大批量"影响）
echo "== 7. 独立访客IP/小时（今天 vs 昨天同文件）=="
awk -v DL="$DL" 'substr($4,2,11)==DL{print substr($4,14,2)" "$1}' $LOG | sort -u | awk '{c[$1]++} END{for(h=0;h<=23;h++) printf "%02d:%d ",h,c[h]}'; echo
PREV=$(ls -t /www/wwwlogs/www.423down.com-access.log-* 2>/dev/null | head -1)
if [ -n "$PREV" ] && [ -f "$PREV" ]; then
  PD=$(zcat -f "$PREV" 2>/dev/null | awk '{print substr($4,2,11)}' | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')
  echo "-- 对比基线：$PREV（主要日期 $PD）独立IP/小时 --"
  zcat -f "$PREV" 2>/dev/null | awk -v P="$PD" 'substr($4,2,11)==P{print substr($4,14,2)" "$1}' | sort -u | awk '{c[$1]++} END{for(h=0;h<=23;h++) printf "%02d:%d ",h,c[h]}'; echo
else
  echo "-- 对比基线：无历史归档日志（www.423down.com-access.log-*），跳过 --"
fi

# 7. 规则自检（可选：验证 filter 是否把正常页面算作失败）
echo "== 8. 规则自检：站内搜索/静态资源是否被判为攻击 =="
printf '%s\n' '1.1.1.1 - - [28/Sep/2026:17:38:23 +0800] "GET /search/shell HTTP/2.0" 200 4512 "-" "Mozilla/5.0 (Windows NT 10.0) Chrome/132.0"' > /tmp/t1_$$
printf '%s\n' '2.2.2.2 - - [28/Sep/2026:21:49:43 +0800] "GET /favicon.ico HTTP/2.0" 444 0 "-" "okhttp/4.12.0"' > /tmp/t2_$$
echo "[high vs /search/shell]"; fail2ban-regex /tmp/t1_$$ /etc/fail2ban/filter.d/wordpress-high.conf 2>/dev/null | grep 'Lines:'
echo "[medium vs favicon 444]"; fail2ban-regex /tmp/t2_$$ /etc/fail2ban/filter.d/wordpress-medium.conf 2>/dev/null | grep 'Lines:'
rm -f $W /tmp/banw_$$ /tmp/vidx_$$ /tmp/vips_$$ /tmp/netb_$$ /tmp/t1_$$ /tmp/t2_$$
