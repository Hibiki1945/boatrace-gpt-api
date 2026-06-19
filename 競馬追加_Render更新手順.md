# 同じRenderへ競馬機能を追加する手順

## 追加されるAPI

既存の競艇APIはそのまま維持し、同じRender URLへ以下を追加します。

```text
GET  /boatrace/race-data
GET  /keiba/race-data
POST /keiba/evaluate
GET  /health
GET  /privacy
```

## 競馬APIの役割

### 1. `/keiba/race-data`

JRA公式URLを主情報として取得します。必要に応じて、ユーザーが指定したnetkeibaの馬柱URLを補助確認します。

入力:

```text
jra_url: JRA公式のHTTPS URL（必須）
netkeiba_url: netkeibaの馬柱・競走馬HTTPS URL（任意）
include_result: 予想時false、検証時true
```

netkeibaは以下の制限で扱います。

- 指定URLだけを取得する
- 10分間のメモリキャッシュを使う
- ログイン・会員ページを取得しない
- 連続巡回、アクセス制限回避、結果ページの予想時取得をしない
- JRA公式情報を常に優先する

### 2. `/keiba/evaluate`

既存の `keiba_engine_complete.py` で採点します。

入力は次の形式です。

```json
{
  "レース情報": {
    "レース名": "レース名",
    "開催日": "2026-06-21",
    "開催場": "東京",
    "距離": "芝1600m"
  },
  "出走馬": [
    {
      "馬番": 1,
      "馬名": "馬名",
      "能力評価": 80,
      "再現性評価": 80,
      "距離適性": 80,
      "開催場適性": 80,
      "展開評価": 80,
      "期待値評価": 70
    }
  ]
}
```

出力には全馬評価、S/A/P1/P2/B分類、本命軸、購入判断、三連複フォーメーション、ワイド候補が含まれます。

## GitHubとRenderの更新

1. GitHubの既存Renderリポジトリを開く
2. 更新済みZIPを展開する
3. ZIP内のファイルを既存リポジトリ直下へ上書きアップロードする
4. GitHubへの反映を確認する
5. Renderのサービス画面を開く
6. 自動デプロイを待つ。始まらない場合は `Manual Deploy` -> `Deploy latest commit`
7. デプロイログが `Live` になったら、以下を確認する

```text
https://boatrace-gpt-api.onrender.com/health
https://boatrace-gpt-api.onrender.com/privacy
```

## GPT Actionsの更新

`boatrace_gpt_action_openapi.json` をActionsのスキーマ欄へ貼り直します。

認証設定は既存のままです。

```text
Authentication: API Key
Header Name: X-API-Key
API Key: RenderのBOATRACE_ACTION_API_KEY
```

## 競馬GPTのInstructionsに加える内容

```text
競馬予想時は、JRA公式のレース情報URLを最優先で確認し、ActionsのgetKeibaRaceSourceDataを呼び出す。
netkeibaの馬柱URLを確認できる場合は補助情報として指定する。ただしJRA公式情報と矛盾する場合はJRA公式を優先する。
予想時はinclude_result=falseを使い、結果や払戻を参照しない。
取得した情報を全馬監査表へ反映してから、evaluateKeibaRaceへレース情報と全出走馬の採点入力を渡す。
APIが返せない情報は未確認と記録し、推測で補完しない。
```

