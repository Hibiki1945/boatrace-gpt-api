# BOAT RACE GPT Action — 場優先度・手動貼り付け評価対応版

BOAT RACE公式情報を取得し、Custom GPT Actionsへ返すためのRender向け一式です。既存の24場攻略情報に加え、`boatrace_venue_priority.json` の場優先度を返します。

## 変更点

- 全24場を★★★★★〜★★☆☆☆へ区分し、購入判断と日次予算上限に反映
- 1日最大3レース、3連単は原則6点まで
- 進入不明・直前情報不足・リスク60以上などを即NO BET条件化
- ★★★☆☆・★★☆☆☆での購入に追加条件を設定
- APIレスポンスへ `場優先度` を追加
- `POST /boatrace/prediction` を追加。ユーザーが手動で貼り付けた展示、平均ST、モーター、枠別成績、決まり手を解析する
- 外部サイトへの自動アクセスは行わず、手動貼り付け本文だけを解析する
- 今期と直近6ヶ月の成績比較、F持ち、決まり手、逃げシミュレーション、評価コメントを返す

## GitHub / Renderへの配置

1. このフォルダの内容をGitHubリポジトリ直下へ配置します。
2. RenderでGitHubリポジトリを指定して新規Web Serviceを作成します。
3. `render.yaml` の設定を使用し、環境変数 `BOATRACE_ACTION_API_KEY` を必要に応じて設定します。
4. 公開URLを `boatrace_gpt_action_openapi.json` の `servers.url` へ設定し、Custom GPT ActionsへOpenAPIファイルを登録します。

`boatrace_prediction_engine.py`、`boatrace_venue_priority.json`、`boatrace_place_prompt.txt`、`競艇予想テンプレート_v1.0.json` は同じディレクトリに置いたままデプロイしてください。

## Custom GPT Instructionsへ追加する文面

```text
レース予想ではActionの「場優先度」を最初に確認すること。
判定順は、場優先度 → 展示・進入・気象水面 → 最終評価と期待値 → GO / SMALL / NO BET → 点数・資金配分とする。
APIの即NO BET条件に該当する場合は舟券を提示しない。
★★★☆☆は原則見送り。★★☆☆☆は展示・モーター・進入が揃い、最終評価A以上の場合だけ検討する。上位ランク場にGO候補がある日は★★☆☆☆を優先しない。
1日3レース以内、3連単は原則6点以内。7点以上は★★★★☆以上かつ最終評価S以上で、増点理由・各買い目の役割・期待払戻を説明できる場合だけ許可する。
回答には、場ランク、GO / SMALL / NO BET、点数、合計金額または日次予算比率、購入理由または見送り理由を必ず含める。
```

## 動作確認

ローカルで次を実行します。

```powershell
python boatrace_action_server.py --host 127.0.0.1 --port 8787
```

別のターミナルから、次を開きます。

```text
http://127.0.0.1:8787/boatrace/race-data?date=20260619&place=戸田&race=12
```

レスポンス内の `場優先度` に、戸田の `★★☆☆☆`、`原則見送り`、追加条件が返ることを確認してください。

手動貼り付け評価は、Custom GPT ActionsまたはHTTPクライアントから `POST /boatrace/prediction` を呼び出します。入力は場名、風、F持ち艇番、展示情報のコピー全文が必須で、平均ST・モーター・枠別成績・決まり手は任意です。

## 運用上の注意

場ランクは購入判断の入口です。直前展示・進入・気象・オッズが悪い場合、★★★★★でもNO BETにします。場ランクや資金上限は、レース後検証の蓄積に基づき定期的に見直してください。
