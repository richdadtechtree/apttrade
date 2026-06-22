"""
run_collect.py — 15년치 부동산 실거래가 일괄 수집 스크립트

사용법:
    python run_collect.py                       # 전체 (2010-01 ~ 현재)
    python run_collect.py --from 202001         # 특정 월부터
    python run_collect.py --type apt_trade      # 특정 데이터 유형만
    python run_collect.py --lawd 11680          # 특정 지역만 (강남구)
    python run_collect.py --workers 4           # 병렬 워커 수 (기본 3)

환경변수 (.env):
    SERVICE_KEY       공공데이터포털 인증키
    POSTGRES_HOST     DB 호스트
    POSTGRES_PORT     DB 포트 (기본 5432)
    POSTGRES_DB       데이터베이스명
    POSTGRES_USER     DB 사용자
    POSTGRES_PASSWORD DB 비밀번호
"""

import os
import sys
import logging
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from dotenv import load_dotenv
from tqdm import tqdm

from db import get_conn, init_db, upsert_rows, already_collected, save_collect_log
from collector import fetch_all_pages
from lawd_codes import LAWD_CODES

load_dotenv()

# ─────────────────────────────────────────────────
# 로깅 설정
# ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("collect.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_collect")


# ─────────────────────────────────────────────────
# 월 범위 생성
# ─────────────────────────────────────────────────
def generate_months(start_ymd: str, end_ymd: str) -> list[str]:
    """'YYYYMM' 형식 월 목록 반환 (start ≤ x ≤ end)"""
    start = datetime.strptime(start_ymd, "%Y%m")
    end   = datetime.strptime(end_ymd,   "%Y%m")
    months = []
    cur = start
    while cur <= end:
        months.append(cur.strftime("%Y%m"))
        cur += relativedelta(months=1)
    return months


# ─────────────────────────────────────────────────
# 단일 수집 작업
# ─────────────────────────────────────────────────
def collect_one(data_type: str, lawd_cd: str, deal_ymd: str, force: bool = False) -> dict:
    """
    (data_type, lawd_cd, deal_ymd) 조합 1건 수집 → DB 저장.
    반환: {ok, rows_saved, skipped}
    """
    conn = get_conn()
    try:
        # 이미 수집 완료된 경우 스킵 (force=True인 경우 캐시 무시하고 강제 수집)
        if not force and already_collected(data_type, lawd_cd, deal_ymd, conn):
            return {"ok": True, "rows_saved": 0, "skipped": True}

        rows, columns = fetch_all_pages(data_type, lawd_cd, deal_ymd)

        if not rows:
            save_collect_log(data_type, lawd_cd, deal_ymd, 0, "empty", "", conn)
            conn.commit()
            return {"ok": True, "rows_saved": 0, "skipped": False}

        saved = upsert_rows(data_type, columns, rows, conn)
        save_collect_log(data_type, lawd_cd, deal_ymd, saved, "ok", "", conn)
        conn.commit()
        return {"ok": True, "rows_saved": saved, "skipped": False}

    except Exception as exc:
        conn.rollback()
        save_collect_log(data_type, lawd_cd, deal_ymd, 0, "error", str(exc)[:500], conn)
        conn.commit()
        logger.error(f"[{data_type}] {lawd_cd}/{deal_ymd} 실패: {exc}")
        return {"ok": False, "rows_saved": 0, "skipped": False}
    finally:
        conn.close()


# ─────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="부동산 실거래가 15년치 수집")
    parser.add_argument(
        "--from", dest="from_ymd", default="201001",
        help="수집 시작 월 (기본: 201001)"
    )
    parser.add_argument(
        "--to", dest="to_ymd",
        default=date.today().strftime("%Y%m"),
        help="수집 종료 월 (기본: 이번 달)"
    )
    parser.add_argument(
        "--type", dest="data_type", default="all",
        choices=["all", "apt_trade", "silv_trade", "apt_rent"],
        help="수집할 데이터 유형 (기본: all)"
    )
    parser.add_argument(
        "--lawd", dest="lawd_cd", default=None,
        help="특정 법정동 코드만 수집 (기본: 전국)"
    )
    parser.add_argument(
        "--workers", type=int, default=3,
        help="병렬 스레드 수 (기본: 3, 최대 권장 5)"
    )
    args = parser.parse_args()

    # 인증키 확인
    if not os.getenv("SERVICE_KEY"):
        logger.error("SERVICE_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    # DB 초기화
    logger.info("DB 테이블 초기화 중...")
    init_db()

    # 수집 대상 결정
    data_types = (
        ["apt_trade", "silv_trade", "apt_rent"]
        if args.data_type == "all"
        else [args.data_type]
    )
    lawd_dict = (
        {args.lawd_cd: LAWD_CODES.get(args.lawd_cd, args.lawd_cd)}
        if args.lawd_cd
        else LAWD_CODES
    )
    months = generate_months(args.from_ymd, args.to_ymd)

    # 전체 작업 목록 생성
    tasks = [
        (dt, lawd_cd, ym)
        for dt in data_types
        for lawd_cd in lawd_dict
        for ym in months
    ]

    total = len(tasks)
    logger.info(
        f"수집 시작 — 유형: {data_types}, 지역 수: {len(lawd_dict)}, "
        f"기간: {args.from_ymd}~{args.to_ymd} ({len(months)}개월), "
        f"총 작업: {total:,}건, 워커: {args.workers}"
    )

    stats = {"ok": 0, "error": 0, "skipped": 0, "rows": 0}
    start_ts = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {
            pool.submit(collect_one, dt, lawd_cd, ym): (dt, lawd_cd, ym)
            for dt, lawd_cd, ym in tasks
        }
        with tqdm(total=total, unit="req", desc="수집") as pbar:
            for future in as_completed(future_map):
                dt, lawd_cd, ym = future_map[future]
                try:
                    result = future.result()
                    if result["skipped"]:
                        stats["skipped"] += 1
                    elif result["ok"]:
                        stats["ok"] += 1
                        stats["rows"] += result["rows_saved"]
                    else:
                        stats["error"] += 1
                except Exception as exc:
                    stats["error"] += 1
                    logger.error(f"[{dt}] {lawd_cd}/{ym} 예외: {exc}")

                pbar.update(1)
                pbar.set_postfix(
                    ok=stats["ok"],
                    err=stats["error"],
                    skip=stats["skipped"],
                    rows=f"{stats['rows']:,}",
                )

    elapsed = time.time() - start_ts
    logger.info(
        f"\n수집 완료 — "
        f"성공: {stats['ok']:,} | 스킵(기수집): {stats['skipped']:,} | "
        f"오류: {stats['error']:,} | 저장 행: {stats['rows']:,} | "
        f"소요: {elapsed/60:.1f}분"
    )


if __name__ == "__main__":
    main()
