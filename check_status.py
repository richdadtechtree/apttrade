"""
check_status.py — 15년치 수집 현황 점검 스크립트

사용법:
    python check_status.py            # 전체 요약
    python check_status.py --detail   # 에러 목록 포함 상세 출력
"""

import os
import sys
import argparse
from dotenv import load_dotenv
from db import get_conn

load_dotenv()


def separator(title=""):
    w = 70
    if title:
        side = (w - len(title) - 2) // 2
        print("=" * side + f" {title} " + "=" * side)
    else:
        print("=" * w)


def run(detail: bool):
    conn = get_conn()
    cur = conn.cursor()

    separator("📊 테이블별 전체 행 수")
    for tbl in ["apt_trade", "silv_trade", "apt_rent", "apt_max_price", "apt_today_max_price"]:
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        cnt = cur.fetchone()[0]
        print(f"  {tbl:<20} : {cnt:>12,} 행")

    separator()

    # ── collect_log 요약 ──────────────────────────────────────
    separator("📋 collect_log 수집 현황 (테이블별)")
    cur.execute("""
        SELECT
            table_name,
            COUNT(*)                                    AS total_jobs,
            COUNT(*) FILTER (WHERE status = 'ok')       AS ok,
            COUNT(*) FILTER (WHERE status = 'empty')    AS empty,
            COUNT(*) FILTER (WHERE status = 'error')    AS error,
            COALESCE(SUM(rows_saved), 0)                AS total_rows_saved,
            MIN(deal_ymd)                               AS earliest,
            MAX(deal_ymd)                               AS latest,
            MIN(collected_at)::date                     AS first_collected,
            MAX(collected_at)::date                     AS last_collected
        FROM collect_log
        GROUP BY table_name
        ORDER BY table_name
    """)
    rows = cur.fetchall()
    if not rows:
        print("  ⚠️  collect_log 에 데이터가 없습니다. 수집이 아직 시작되지 않았거나 테이블이 비어 있습니다.")
    else:
        header = f"  {'테이블':<14} {'전체':>7} {'OK':>7} {'빈값':>7} {'에러':>7} {'저장행':>12} {'시작월':>8} {'종료월':>8}"
        print(header)
        print("  " + "-" * 68)
        for r in rows:
            tbl, total, ok, empty, error, saved, earliest, latest, fc, lc = r
            print(
                f"  {tbl:<14} {total:>7,} {ok:>7,} {empty:>7,} {error:>7,} "
                f"{saved:>12,} {earliest or '-':>8} {latest or '-':>8}"
            )
            print(f"    └─ 수집일: {fc} ~ {lc}")

    separator()

    # ── 기간 커버리지 ─────────────────────────────────────────
    separator("📅 기간 커버리지 분석 (2010-01 ~ 현재)")
    cur.execute("""
        SELECT
            table_name,
            COUNT(DISTINCT deal_ymd) FILTER (WHERE status IN ('ok','empty')) AS covered_months,
            COUNT(DISTINCT deal_ymd)                                          AS total_logged
        FROM collect_log
        GROUP BY table_name
        ORDER BY table_name
    """)
    coverage = cur.fetchall()
    # 2010-01 ~ 현재까지 몇 개월?
    cur.execute("SELECT EXTRACT(YEAR FROM AGE(NOW(), '2010-01-01')) * 12 + "
                "EXTRACT(MONTH FROM AGE(NOW(), '2010-01-01'))")
    total_months = int(cur.fetchone()[0]) + 1
    lawd_count_q = "SELECT COUNT(DISTINCT lawd_cd) FROM collect_log"
    cur.execute(lawd_count_q)
    lawd_cnt = cur.fetchone()[0]

    print(f"  기준 기간 : 2010-01 ~ 현재 (약 {total_months}개월)")
    print(f"  수집 지역 코드 수 : {lawd_cnt}개")
    print()
    for r in coverage:
        tbl, covered, logged = r
        expected = total_months * lawd_cnt if lawd_cnt > 0 else 0
        pct = covered / expected * 100 if expected > 0 else 0
        print(f"  {tbl:<15}: {covered:,}개월 커버 / {expected:,}개 예상 작업 ({pct:.1f}%)")

    separator()

    # ── 에러 상세 (--detail 옵션) ─────────────────────────────
    if detail:
        separator("❌ 에러 목록 (최근 50건)")
        cur.execute("""
            SELECT table_name, lawd_cd, deal_ymd, message, collected_at
            FROM collect_log
            WHERE status = 'error'
            ORDER BY collected_at DESC
            LIMIT 50
        """)
        errs = cur.fetchall()
        if not errs:
            print("  에러 없음 ✅")
        else:
            for r in errs:
                tbl, lawd, ymd, msg, ts = r
                print(f"  [{tbl}] {lawd}/{ymd} @ {ts}")
                print(f"    └─ {msg}")
        separator()

    # ── 미수집 월 샘플 (에러/미기록) ──────────────────────────
    separator("🔍 아파트 매매 기준 — 가장 최근 수집 미완성 월 (에러)")
    cur.execute("""
        SELECT lawd_cd, deal_ymd, message
        FROM collect_log
        WHERE table_name = 'apt_trade' AND status = 'error'
        ORDER BY deal_ymd DESC
        LIMIT 10
    """)
    missing = cur.fetchall()
    if not missing:
        print("  apt_trade 에러 없음 ✅")
    else:
        for r in missing:
            lawd, ymd, msg = r
            print(f"  lawd={lawd}  ymd={ymd}  msg={msg or '(없음)'}")

    separator()
    cur.close()
    conn.close()
    print("✅ 점검 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="15년치 수집 현황 점검")
    parser.add_argument("--detail", action="store_true", help="에러 목록 상세 출력")
    args = parser.parse_args()
    run(args.detail)
