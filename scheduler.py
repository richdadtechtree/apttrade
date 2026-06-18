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


def main():
    init_db()

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    # 매월 5일 02:00 KST
    scheduler.add_job(monthly_job, "cron", day=5, hour=2, minute=0)

    logger.info("스케줄러 시작 — 매월 5일 02:00 KST에 전월 데이터 수집")
    logger.info("Ctrl+C로 종료")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러 종료")


if __name__ == "__main__":
    main()
