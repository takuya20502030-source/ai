"""RIN GARDEN SYSTEM CLI。

python -m rin_garden schedule --sport jra --date today
python -m rin_garden pre --sport jra --date today
python -m rin_garden final --sport jra --race-id XXXXX
python -m rin_garden settle --sport jra --date today
python -m rin_garden audit --date today
python -m rin_garden sheets-check
python -m rin_garden sheets-raw-inspect --sport keirin

初回構築時点では、各サブコマンドは骨格(拡張可能なInterface)であり、
実際のGARDEN-6分析・本格的なデータ取得は未実装(collectorsはDATA_INCOMPLETEを返す)。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date as date_cls
from pathlib import Path
from typing import Any

from rin_garden.audit.coverage import daily_coverage
from rin_garden.audit.posthoc import scan_day_for_post_hoc_violations
from rin_garden.collectors.registry import get_collector
from rin_garden.core.config import PROJECT_ROOT, load_system_config, resolve_paths
from rin_garden.core.logging import AuditLogger
from rin_garden.core.pre_fix import PreFixService
from rin_garden.core.race_master import RaceMasterStore
from rin_garden.settlement.aggregation import aggregate_day
from rin_garden.sheets.client import SheetsClient
from rin_garden.sheets.inspector import inspect_spreadsheet, inspect_spreadsheet_raw


def _resolve_date(value: str) -> str:
    if value == "today":
        return date_cls.today().isoformat()
    return value


def _build_context(root: Path | None = None) -> dict[str, Any]:
    root = root or PROJECT_ROOT
    system_config = load_system_config(root)
    paths = resolve_paths(system_config, root)
    audit_logger = AuditLogger(paths["audit_log_file"])
    race_master_store = RaceMasterStore(paths["normalized_dir"])
    return {
        "root": root,
        "system_config": system_config,
        "paths": paths,
        "audit_logger": audit_logger,
        "race_master_store": race_master_store,
    }


def cmd_schedule(args: argparse.Namespace) -> int:
    date = _resolve_date(args.date)
    collector = get_collector(args.sport)
    result = collector.get_schedule(date)
    print(f"[schedule] sport={args.sport} date={date} ok={result.ok} confidence={result.confidence}")
    if result.message:
        print(f"  message: {result.message}")
    if result.ok:
        print(f"  data: {result.data}")
    return 0


def cmd_pre(args: argparse.Namespace) -> int:
    ctx = _build_context()
    date = _resolve_date(args.date)
    race_ids = ctx["race_master_store"].list_race_ids(args.sport, date)
    PreFixService(ctx["paths"]["pre_dir"], ctx["race_master_store"], ctx["audit_logger"])  # constructed for future use
    if not race_ids:
        print(f"[pre] no Race Master found for sport={args.sport} date={date}.")
        print("      run schedule/data collection and Race Master registration first.")
        return 0
    print(f"[pre] {len(race_ids)} race(s) found for sport={args.sport} date={date}: {race_ids}")
    print("      PRE-FIX creation requires GARDEN-6 analysis output as input (see rin_garden.core.pre_fix.PreFixService.create).")
    return 0


def cmd_final(args: argparse.Namespace) -> int:
    ctx = _build_context()
    date = args.date and _resolve_date(args.date) or date_cls.today().isoformat()
    rm = ctx["race_master_store"].load(args.sport, date, args.race_id)
    if rm is None:
        print(f"[final] no Race Master found for sport={args.sport} date={date} race_id={args.race_id}")
        return 1
    print(f"[final] race_id={args.race_id} status={rm.status} pre_fixed_at={rm.pre_fixed_at}")
    print("        FINAL-LOCK creation requires final marks/bets input (see rin_garden.core.final_lock.FinalLockService).")
    return 0


def cmd_settle(args: argparse.Namespace) -> int:
    ctx = _build_context()
    date = _resolve_date(args.date)
    summary = aggregate_day(args.sport, date, ctx["paths"]["results_dir"], ctx["race_master_store"])
    print(f"[settle] sport={args.sport} date={date}")
    print(
        f"  races_settled={summary['races_settled']} stake={summary['stake']} "
        f"payout={summary['payout']} profit={summary['profit']} roi={summary['roi']:.3f}"
    )
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    ctx = _build_context()
    date = _resolve_date(args.date)
    sports = ctx["system_config"].get("sports", [])
    for sport in sports:
        coverage = daily_coverage(
            sport,
            date,
            ctx["race_master_store"],
            ctx["paths"]["pre_dir"],
            ctx["paths"]["final_dir"],
            ctx["paths"]["results_dir"],
        )
        violations = scan_day_for_post_hoc_violations(sport, date, ctx["race_master_store"])
        print(
            f"[audit] sport={sport} date={date} scheduled={coverage['scheduled_races']} "
            f"pre_fixed={coverage['pre_fixed']} final_locked={coverage['final_locked']} "
            f"settled={coverage['settled']} missing={coverage['missing']}"
        )
        if violations:
            print(f"  POST_HOC violations detected: {violations}")
    return 0


def cmd_sheets_check(args: argparse.Namespace) -> int:
    """Google Sheets接続状態を報告する。認証情報・Sheet IDが無くても処理を止めない。

    読み取り専用でタブ構成を調査するのみで、一切書き込みを行わない。
    """
    client = SheetsClient()
    status = client.status()

    print(f"[sheets-check] dry_run={status.dry_run}")
    print("  認証方式の優先順位: 1) User OAuth  2) ADC  3) Service Account  4) dry-run")
    print(f"  [1] User OAuth: client_secret={status.oauth_client_secret_path} exists={status.oauth_client_secret_exists} "
          f"/ token={status.oauth_token_path} exists={status.oauth_token_exists}")
    print(f"  [2] ADC (Application Default Credentials): available={status.adc_available}")
    print(f"  [3] Service Account: GOOGLE_APPLICATION_CREDENTIALS={status.credentials_path or '(未設定)'} exists={status.credentials_file_exists}")
    print(f"  利用可能な認証方式(優先順): {status.available_auth_methods() or '(なし)'}")
    for sport, sheet_id in status.sheet_ids.items():
        print(f"  GOOGLE_SHEET_ID_{sport.upper()}={sheet_id or '(未設定)'}")

    missing = status.missing_items()
    if missing:
        print("  [不足している設定]")
        for item in missing:
            print(f"    - {item}")

    sports = [args.sport] if args.sport else list(status.sheet_ids.keys())
    for sport in sports:
        inspection = inspect_spreadsheet(client, sport)
        if not inspection.connected:
            print(f"  [{sport}] not connected: {inspection.message}")
            continue
        print(f"  [{sport}] connected (auth_method={client.auth_method}). tabs:")
        for name, tab in inspection.tabs.items():
            print(f"    - {name}: exists={tab.exists} headers={tab.headers} rows={tab.row_count} race_ids={len(tab.race_ids)}")
    return 0


def cmd_sheets_raw_inspect(args: argparse.Namespace) -> int:
    """既存Google Sheetsのタブ構成を、タブ名を一切前提とせず読み取り専用で調査する。

    こちらの正規スキーマ(RaceMaster/PRE/FINAL/...)のタブ名とは無関係に、
    実際に存在する全タブのタイトル・ヘッダー行・使用範囲・先頭数行のみを表示する。
    書き込みは一切行わない(add_worksheet/update等は呼ばない)。
    """
    client = SheetsClient()
    if client.dry_run:
        print("[sheets-raw-inspect] dry-run mode: no usable credentials configured. Nothing to inspect.")
        return 0

    sheet_id = client.sheet_id_for(args.sport)
    if not sheet_id:
        print(f"[sheets-raw-inspect] GOOGLE_SHEET_ID_{args.sport.upper()} is not set.")
        return 0

    result = inspect_spreadsheet_raw(client, args.sport, sample_rows=args.sample_rows)
    if not result["connected"]:
        print(f"[sheets-raw-inspect] not connected: {result['message']}")
        return 1

    print(f"[sheets-raw-inspect] sport={args.sport} auth_method={client.auth_method} "
          f"spreadsheet_title={result['spreadsheet_title']!r}")
    tabs = result["tabs"]
    print(f"  tab count: {len(tabs)}")
    print(f"  tab titles (in sheet order): {list(tabs.keys())}")
    for title, tab in tabs.items():
        print(f"\n  --- tab: {title!r} ---")
        if tab is None:
            print("    (could not be read)")
            continue
        print(f"    header_row: {tab.header_row}")
        print(f"    data_row_count: {tab.data_row_count} / sheet_col_count: {tab.sheet_col_count}")
        for i, row in enumerate(tab.sample_rows, start=1):
            print(f"    sample_row[{i}]: {row}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rin_garden", description="RIN GARDEN SYSTEM CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_schedule = sub.add_parser("schedule", help="開催スケジュールを取得する")
    p_schedule.add_argument("--sport", required=True)
    p_schedule.add_argument("--date", required=True)
    p_schedule.set_defaults(func=cmd_schedule)

    p_pre = sub.add_parser("pre", help="PRE-FIXを作成する")
    p_pre.add_argument("--sport", required=True)
    p_pre.add_argument("--date", required=True)
    p_pre.set_defaults(func=cmd_pre)

    p_final = sub.add_parser("final", help="FINAL-LOCKを作成する")
    p_final.add_argument("--sport", required=True)
    p_final.add_argument("--race-id", required=True)
    p_final.add_argument("--date", required=False)
    p_final.set_defaults(func=cmd_final)

    p_settle = sub.add_parser("settle", help="精算・集計を行う")
    p_settle.add_argument("--sport", required=True)
    p_settle.add_argument("--date", required=True)
    p_settle.set_defaults(func=cmd_settle)

    p_audit = sub.add_parser("audit", help="Coverage/NO POST-HOC監査を行う")
    p_audit.add_argument("--date", required=True)
    p_audit.set_defaults(func=cmd_audit)

    p_sheets_check = sub.add_parser("sheets-check", help="Google Sheets接続状態を読み取り専用で確認する")
    p_sheets_check.add_argument("--sport", required=False, help="省略時は全競技分を確認する")
    p_sheets_check.set_defaults(func=cmd_sheets_check)

    p_sheets_raw_inspect = sub.add_parser(
        "sheets-raw-inspect",
        help="既存Google Sheetsの実際のタブ構成をタブ名を前提とせず読み取り専用で調査する(書き込みなし)",
    )
    p_sheets_raw_inspect.add_argument("--sport", required=True)
    p_sheets_raw_inspect.add_argument("--sample-rows", type=int, default=3, help="各タブから表示するサンプル行数")
    p_sheets_raw_inspect.set_defaults(func=cmd_sheets_raw_inspect)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
