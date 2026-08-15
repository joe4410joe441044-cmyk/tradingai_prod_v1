# OpenCode 利用手順（ユーザー向け）

## 1. OpenCodeサーバー起動

``` bash
opencode serve --hostname 127.0.0.1 --port 4096
```

------------------------------------------------------------------------

## 2. ターミナルから接続

``` bash
cd /home/joe4410joe/tradingai_prod_v1

opencode attach http://127.0.0.1:4096
```

------------------------------------------------------------------------

## 3. 誤ってターミナルを閉じた場合

サーバー確認

``` bash
ss -ltn '( sport = :4096 )'
```

ポート4096が LISTEN ならサーバーは動作中。

その後、再接続する。

``` bash
cd /home/joe4410joe/tradingai_prod_v1

opencode attach http://127.0.0.1:4096
```

------------------------------------------------------------------------

## 4. サーバーも終了していた場合

再度サーバーを起動する。

``` bash
opencode serve --hostname 127.0.0.1 --port 4096
```

その後

``` bash
opencode attach http://127.0.0.1:4096
```

------------------------------------------------------------------------

## 5. セッション一覧を確認したい場合

``` bash
opencode session list
```

------------------------------------------------------------------------

## よく使うコマンド

``` bash
opencode serve --hostname 127.0.0.1 --port 4096
opencode attach http://127.0.0.1:4096
opencode session list
ss -ltn '( sport = :4096 )'
```
