# RIN GARDEN SYSTEM

JRA中央競馬 / 地方競馬（NAR）/ BOAT RACE / 競輪 を対象とした、私的利用の公営競技
分析・検証システムです。実購入・自動投票システムではありません。

思想・禁止事項の詳細は [`CLAUDE.md`](./CLAUDE.md) を参照してください。

## RIN GARDENとは何か

RIN GARDEN SYSTEM は「的中数」ではなく **長期ROI・純利益・市場価格に対する優位性** を
目的とした分析基盤です。最大の特徴は、結果を知った後に予想を書き換えることを
コード・テスト・監査ログによって強制的に禁止している点です（**NO POST-HOC**）。

- **PRE-FIX**: 発走前に確定させる予想の原本（immutable、レース単位で1件）
- **FINAL-LOCK**: 直前情報を反映した最終判断（`race_id + account` 単位。revisionのみ許可、上書き禁止）
- **Account**: 予測ロジック（共通PRE）と資金・選別ロジック（AccountPolicy）を分離する仕組み。`config/accounts.yaml` で管理し、1レースに複数Account（FORCED-ALL / SELECT-B+ 等）を独立して持てる
- **GARDEN-6**: 6人の独立分析担当（凜・美羽香・花奈・英梨紗・黒音・瑠那）による多角的分析
- **Race Master**: `race_id` を中心とした厳密なレース同一性管理（レース単位で1件、Accountでは複製しない）

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
で動作します。`python -m rin_garden sheets-check` で、認証情報・Sheet IDの設定状況と
（接続できる場合は）既存タブの構成を読み取り専用で確認できます。処理を止めることはありません。

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
python -m rin_garden sheets-check
```

### 競輪データの取り込み

現時点で稼働中の実行環境からは競輪の公式データソースへネットワークで到達できない
(egressポリシーによりブロックされる)ため、`get_schedule()`等のライブ取得系メソッドは
`DATA_INCOMPLETE`を返すダミーのままです。代わりに、ユーザーが正規の一次情報源から
取得したデータをJSONファイルとして取り込む経路を用意しています。

```python
from rin_garden.collectors.keirin.collector import KeirinCollector

collector = KeirinCollector()
result = collector.load_race_card_from_file("path/to/race_card.json")
```

JSONの形式は `config/keirin.yaml` の `race_fields` に対応します
(`tests/fixtures/keirin_race_card_sample.json` にサンプル構造があります)。
Identityフィールド(`sport/date/venue/race_number/event_id/scheduled_start`)が
欠けているファイルは取り込みを拒否し、出走者ごとのフィールド欠落は
`DATA_INCOMPLETE`/`ESTIMATED`として明示します(推測で埋めません)。

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
最重要ルールです。`scheduled_start` と操作時刻を比較する pre-write validation に加え、
`race_master.status` が `RESULT_LOCKED/SETTLED/AUDITED` に進んでいる場合は時刻計算に
依存せず無条件で拒否する多重防御も備えています。詳細は `rin_garden/core/locks.py`、
`rin_garden/core/pre_fix.py`、`rin_garden/core/final_lock.py` と `tests/test_locks.py`、
`tests/test_audit_finalize.py`。Google Sheetsへの書き込み(`sheets/writer.py`)でも
結果確定後のPRE書き込みは同様に拒否されます。

## GARDEN-6

6人の独立分析担当が、それぞれの専門領域から独立して分析し、最後に凜が統合してBUY/WAIT/SKIPを
決定します。人格定義は `agents/` 配下、`rin_garden/analysis/members.py` の
`Garden6Member` Interfaceが同一の `RaceSnapshot` を6担当全員へ渡して独立した
`MemberFinding` を得るところまでを担い、最終統合は `rin_garden/analysis/garden6.py` の
`integrate()`(凜)が担当します。まだLLM接続はしておらず、各担当は構造上のスタブです。

## Settlement / Audit の状態遷移

```text
SCHEDULED -> PRE_FIXED -> FINAL_LOCKED -> RESULT_LOCKED -> SETTLED -> AUDITED
```

`AUDITED` はCoverage(PRE/FINAL/Result/Settlementが揃っているか)を確認した上での
最終確定です(`rin_garden/audit/finalize.py`)。PRE/FINAL/Result/Settlementの内容は
一切書き換えません。

## Google Sheets 正本の移行状況(v3.0)

RIN GARDEN Google Sheets正本は **v3.0 へ全面移行** しました。以前の台帳(競輪:
`RIN_GARDEN_Keirin_Virtual_Ledger_v2.1`)は **ARCHIVE ONLY** です。新規書き込み・
結果追加・精算・集計・通常参照のいずれにも使いません。

v2.1構造調査に基づく設定(`config/sheet_write_policy.yaml` /
`config/sheet_tab_layout.yaml`)は `keirin_v2_1_archive` というsport識別子の下に
アーカイブされており、現行の `keirin`(=v3.0)としてロードしても何も取得できません
(=v2.1のMappingが誤ってv3.0へ適用されることをコード上防いでいます)。v3.0用の
Mapping/Adapterは、v3.0の実タブ構成をREAD ONLYで確認してから別途追加します。

v3.0のSpreadsheet ID(競輪・地方競馬・BOAT RACE)は判明していますが、このセッション
からは実Sheetへ接続できないため未検証です。JRAのSpreadsheet IDは未確認であり、
このリポジトリ側で推測した値は一切含めていません。`python -m rin_garden sheets-check`
でローカル環境から現在の設定値・接続状態を確認してください。

## 現状のステータス

Race Master / Lock機構(PRE-FIX・FINAL-LOCK・NO POST-HOC、Account単位対応) /
Ticket(`race_id + account + ticket_id`) / Settlement(Account単位で独立精算) /
Coverage / Audit finalize / CLI骨格 / GARDEN-6 Interface に加え、Google Sheetsは
User OAuth優先の認証(`sheets/client.py`)、タブ名を前提としない読み取り専用調査
(`sheets/inspector.py`)、数式セルを判別するFORMULA読み取り専用調査
(`sheets/formula_inspector.py`)、whitelist方式のSafe Writer(`sheets/adapter.py`、
未知タブ・数式列・READ ONLYタブ・ヘッダー不一致・Race ID不一致・NO POST-HOCを
それぞれ拒否)まで実装済みです(認証情報が無い環境ではdry-runで動作を確認できます)。
**ただし実際のGoogle Sheetsへの書き込みはまだ一度も実行していません**(すべてFake
backendでの検証のみ)。競輪のみ、正規の一次情報をJSONファイルとして取り込む経路
(`collectors/keirin/snapshot.py`)を実装済みです。JRA/NAR/BOATのライブ取得、
GARDEN-6の実LLM分析、v3.0台帳への実接続検証・Mapping確定は今後の対応対象です。
詳細は各モジュール内のコメントを参照してください。
