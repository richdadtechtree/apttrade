"""
scheduler.py — 매월 자동 수집 스케줄러

전월 데이터를 매달 5일 새벽 2시에 자동 수집합니다.
(실거래 신고 기한이 계약일로부터 30일이므로 전월 데이터는 익월 초 수집)

실행:
    python scheduler.py

백그라운드 실행 (Linux/서버):
    nohup python scheduler.py &> scheduler.log &

또는 systemd 서비스로 등록 권장 (README 참고)
"""

import logging
import sys
from datetime import date
from dateutil.relativedelta import relativedelta
from apscheduler.schedulers.blocking import BlockingScheduler

from dotenv import load_dotenv
from run_collect import collect_one, init_db
from lawd_codes import LAWD_CODES

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scheduler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("scheduler")

DATA_TYPES = ["apt_trade", "silv_trade", "apt_rent"]


def monthly_job():
    """전월 데이터 전국 수집"""
    prev_month = (date.today().replace(day=1) - relativedelta(months=1)).strftime("%Y%m")
    logger.info(f"월간 수집 시작: {prev_month}")

    total_rows = 0
    errors = 0
    for data_type in DATA_TYPES:
        for lawd_cd in LAWD_CODES:
            result = collect_one(data_type, lawd_cd, prev_month)
            if result["ok"]:
                total_rows += result["rows_saved"]
            else:
                errors += 1

    logger.info(f"월간 수집 완료: {prev_month} — 저장 행 {total_rows:,}, 오류 {errors}건")


def daily_job():
    """등록단지 대상 최근 4개월 실거래가 강제 업데이트"""
    recent_months = []
    today = date.today()
    for i in range(4):
        d = today - relativedelta(months=i)
        recent_months.append(d.strftime("%Y%m"))
        
    logger.info(f"일간 등록단지 업데이트 시작. 대상 월: {recent_months}")
    
    from db import get_registered_lawd_codes
    lawd_codes = get_registered_lawd_codes()
    
    if not lawd_codes:
        logger.warning("업데이트할 등록단지 지역 코드가 없습니다. 작업을 건너뜁니다.")
        return

    logger.info(f"대상 지역 코드 수: {len(lawd_codes)}개")
    
    total_rows = 0
    errors = 0
    for data_type in DATA_TYPES:
        for lawd_cd in lawd_codes:
            for ym in recent_months:
                # force=True로 설정하여 기수집 여부와 무관하게 데이터 강제 동기화 (취소 거래 반영 등)
                result = collect_one(data_type, lawd_cd, ym, force=True)
                if result["ok"]:
                    total_rows += result["rows_saved"]
                else:
                    errors += 1

    logger.info(f"일간 등록단지 업데이트 완료 — 저장/업데이트 행 {total_rows:,}, 오류 {errors}건")

    # 신규 신고가 분석 및 DB/JSON 동기화 작업 실행
    logger.info("신규 신고가 분석 및 DB/JSON 동기화 작업 시작...")
    from sync_max_price import check_and_update_max_prices, update_json_file
    from db import get_conn
    conn = get_conn()
    try:
        new_max_prices = check_and_update_max_prices(conn)
        conn.commit()
        if new_max_prices:
            update_json_file("monitored_lists_backup.json", new_max_prices)
    except Exception as e:
        logger.error(f"신고가 동기화 중 오류 발생: {e}")
        conn.rollback()
    finally:
        conn.close()


def main():
    init_db()

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    # 매월 5일 02:00 KST (전국 전월 데이터 수집)
    scheduler.add_job(monthly_job, "cron", day=5, hour=2, minute=0)
    # 매일 03:00 KST (등록단지 최근 4개월 데이터 업데이트)
    scheduler.add_job(daily_job, "cron", hour=3, minute=0)

    logger.info("스케줄러 시작 — 매월 5일 02:00 KST에 전월 데이터 수집 / 매일 03:00 KST에 등록단지 최근 4개월 데이터 업데이트")
    logger.info("Ctrl+C로 종료")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러 종료")


if __name__ == "__main__":
    main()
