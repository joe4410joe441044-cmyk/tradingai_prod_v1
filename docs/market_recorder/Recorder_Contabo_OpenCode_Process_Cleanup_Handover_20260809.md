# Recorder Contabo --- OpenCode残留プロセス問題 引継ぎメモ

作成日: 2026-08-09

## 1. 対象

-   Server: Recorder Contabo
-   Hostname: `vmi3473655`
-   Repository: `/opt/market-recorder`

**重要:** Windows PC側ではなく、Recorder Contaboサーバー上の
`/root/.opencode/bin/opencode serve` 残留プロセス問題である。

## 2. 確認済みの問題

2026-08-09、以下を確認した。

-   VS Code Remote SSH reconnectが非常に遅い
-   OpenCode UIが長時間Loadingになる
-   横棒のLoading表示が止まらない
-   OpenCode UI providerが正常に初期化されない場合がある
-   サーバーのメモリ使用率が非常に高い
-   Swapを大量使用
-   Linux OOM KillerによるOpenCode process killも確認

原因調査で `/root/.opencode/bin/opencode serve`
が古いセッションから終了せず、18 process残留していた。

## 3. Cleanup前後

  項目               Cleanup前   Cleanup後
  ---------------- ----------- -----------
  OpenCode serve            18           2
  RAM使用            約3.5 GiB   約1.1 GiB
  Available RAM      約356 MiB   約2.8 GiB
  Swap使用           約3.4 GiB   約123 MiB

古いOpenCode serve
processの残留がメモリ逼迫の主要原因だった可能性が非常に高い。

## 4. 今後の確認方法

Recorder Contaboが重い、SSH
reconnectが遅い、OpenCodeがLoadingのまま等の場合、まずサーバー再起動ではなく次を確認する。

``` bash
ps -eo pid,lstart,rss,cmd | \
grep '/root/.opencode/bin/opencode serve' | \
grep -v grep
```

PID、開始日時、RSS、portを確認する。

## 5. Cleanup安全ルール

いきなり以下を実行しない。

``` bash
pkill opencode
killall opencode
```

現在使用中のOpenCode sessionまで終了する可能性がある。

明らかに古い残留processのみ選び、最初はTERMを使用する。

``` bash
kill -TERM <PID...>
sleep 5
```

その後、再確認する。

``` bash
ps -eo pid,lstart,rss,cmd | \
grep '/root/.opencode/bin/opencode serve' | \
grep -v grep

free -h
swapon --show
```

TERMで終了しないprocessがある場合のみ、対象PIDを再確認してからKILLを検討する。

## 6. Cleanupで触らないもの

-   `market-recorder.service`
-   `market-recorder-read-api.service`
-   Redis
-   Nginx
-   Recorder Runtime
-   Recording data
-   Manifest
-   Archive
-   UFW
-   systemd configuration
-   Git working tree

OpenCode残留processの整理だけを行う。

## 7. サーバー再起動の判断

OpenCode残留processが原因の場合、Contabo server
rebootは第一選択ではない。

推奨順序:

1.  OpenCode process確認
2.  古い残留processだけTERM
3.  RAM確認
4.  Swap確認
5.  VS Code / OpenCode UI確認
6.  必要なら `Developer: Reload Window`
7.  それでも異常なら追加調査
8.  最後にserver rebootを検討

## 8. 正常状態の目安

今回Cleanup直後:

-   OpenCode serve: 2 processes
-   RAM: 1.1 GiB used
-   Available RAM: 2.8 GiB
-   Swap: 123 MiB used

process数は利用セッション数で変わるため「必ず2個」とは判断しない。

重要なのは、古い日時のserve processが多数残っていないこと。

## 9. 将来の恒久対策

候補タスク:

`MR-OPS-OPENCODE-1A — OpenCode Orphan Process Investigation & Safe Cleanup`

目的:

-   Remote SSH切断後もOpenCode serveが残る原因調査
-   orphan判定方法の確立
-   使用中sessionを誤終了しないcleanup方式
-   必要な場合のみsystemd timer等の安全な自動cleanupを検討

単純な「一定時間以上古いprocessを全部kill」は禁止。

## 10. Recorder開発再開位置

現在:

`MR-RECORDER-CONTROL-5A — Private Control Enablement Phase 1`

その後:

1.  TradingAI Control Proxy
2.  UI START / STOP
3.  Final E2E
4.  Recorder Phase 1完成

## 11. 別GPTへの引継ぎ要点

Recorder Contaboが重い場合、サーバー再起動から始めない。

まず `/root/.opencode/bin/opencode serve`
の残留状況を確認し、現在使用中のOpenCodeを保護しながら、明らかに古い残留processだけを安全に終了する。
