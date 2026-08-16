# RIN GARDEN SYSTEM

JRA中央競馬 / 地方競馬（NAR）/ BOAT RACE / 競輪 を対象とした、私的利用の公営競技
分析・検証システムです。実購入・自動投票システムではありません。

思想・禁止事項の詳細は [`CLAUDE.md`](./CLAUDE.md) を参照してください。

## RIN GARDENとは何か

RIN GARDEN SYSTEM は「的中数」ではなく **長期ROI・純利益・市場価格に対する優位性** を
目的とした分析基盤です。最大の特徴は、結果を知った後に予想を書き換えることを
コード・テスト・監査ログによって強制的に禁止している点です（**NO POST-HOC**）。

- **PRE-FIX**: 発走前に確定させる予想の原本（immutable）
- **FINAL-LOCK**: 直前情報を反映した最終判断（revisionのみ許可、上書き禁止）
- **GARDEN-6**: 6人の独立分析担当（凜・美羽香・花奈・英梨紗・黒音・瑠那）による多角的分析
- **Race Master**: `race_id` を中心とした厳密なレース同一性管理

## ディレクトリ構成

```text
RIN_GARDEN/
├── CLAUDE.md              # 行動規範・禁止事項
├── README.md              # このファイル
├── .env.example            # 環境変数テンプレート
├── config/                 # 競技別・システム全体の設定（YAML）
├── agents/                 # GARDEN-6 各担当の人格定義（Markdown）
├── rin_garden/              # Pythonパッケージ本体
│   ├── core/                # Race Master / Identity / Lock / Validation / Logging
│   ├── collectors/           # 競技別データ取得（共通Interfaceを実装）
│   ├── analysis/             # GARDEN-6統合分析 / ランク / VALUE / シナリオ
│   ├── sheets/               # Google Sheets 抽象化層（表示・確認・集計用途）
│   ├── settlement/           # 結果登録・精算・集計（予想処理とは分離）
│   ├── audit/                # Coverage / NO POST-HOC監査 / 整合性検証
│   ├── cli.py / __main__.py  # CLIエントリポイント
├── data/
│   ├── raw/                  # 取得した生データ（Gitでは追跡しない）
│   ├── normalized/            # 正規化済みRace Master
│   ├── pre/                   # PRE-FIXスナップショット
│   ├── final/                 # FINAL-LOCK（+revision履歴）
│   └── results/                # Result / Settlement
├── logs/                    # 監査ログ（audit.log）
├── tests/                   # pytest
└── scripts/                 # 補助スクリプト
```

## セットアップ

### Python環境構築

Python 3.10 以上を推奨します。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 環境変数

`.env.example` を `.env` にコピーし、値を設定してください。`.env` はGitにコミットしないでください。

```bash
cp .env.example .env
```

| 変数 | 用途 |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Google サービスアカウントのJSON鍵へのパス |
| `GOOGLE_SHEET_ID_JRA` | JRA用 Google Sheet ID |
| `GOOGLE_SHEET_ID_NAR` | 地方競馬用 Google Sheet ID |
| `GOOGLE_SHEET_ID_BOAT` | BOAT RACE用 Google Sheet ID |
| `GOOGLE_SHEET_ID_KEIRIN` | 競輪用 Google Sheet ID |

認証情報が未設定の場合、Sheets連携層は自動的に **dry-run モード**（ログ出力のみ、実書き込みなし）
で動作します。

### テスト方法

```bash
pytest -v
```

### 実行方法（CLI）

現時点ではダミー処理を含む骨格です。

```bash
python -m rin_garden schedule --sport jra --date today
python -m rin_garden pre --sport jra --date today
python -m rin_garden final --sport jra --race-id XXXXX
python -m rin_garden settle --sport jra --date today
python -m rin_garden audit --date today
```

## PRE-FIX

発走前に確定させる予想の原本です。`race_id / timestamp / data_snapshot / garden6_analysis /
rank / chaos / confidence / predicted_scenario / bets / fair_probability / fair_odds /
market_odds / expected_value` を保持し、一度保存すると変更できません。
発走時刻を過ぎてからの新規作成は `POST_HOC_BLOCKED` として拒否されます。

## FINAL-LOCK

直前情報を反映した最終判断です。印・評価・買い目・金額・BUY/WAIT/SKIPを保持します。
作成後の変更は上書きではなく revision として記録され、発走後のrevisionは禁止されます。

## NO POST-HOC

結果取得後にPRE/FINALを新規作成・有利な方向へ改変することをコードレベルで禁止する
最重要ルールです。`scheduled_start` と操作時刻を比較する pre-write validation により
強制されます。詳細は `rin_garden/core/locks.py` と `tests/test_locks.py`。

## GARDEN-6

6人の独立分析担当が、それぞれの専門領域から独立して分析し、最後に凜が統合してBUY/WAIT/SKIPを
決定します。人格定義は `agents/` 配下、統合ロジックは `rin_garden/analysis/garden6.py` を
参照してください。

## 現状のステータス

初回構築フェーズでは、安全で壊れにくいローカル基盤（Race Master / Lock機構 / Sheets抽象化 /
Settlement / Coverage / CLI骨格 / テスト）を優先しています。各競技の本格的なデータ取得・
本格的なGARDEN-6分析ロジックは今後の拡張対象です。詳細は各モジュール内のTODOコメントを
参照してください。
