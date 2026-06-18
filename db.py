"""
db.py — PostgreSQL 연결 관리 및 테이블 DDL

환경변수 (.env):
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
"""

import os
import logging
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def get_conn():
    """PostgreSQL 커넥션 반환"""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "realestate"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


# ─────────────────────────────────────────────────
# DDL
# ─────────────────────────────────────────────────

DDL_APT_TRADE = """
CREATE TABLE IF NOT EXISTS apt_trade (
    id               BIGSERIAL PRIMARY KEY,
    lawd_cd          CHAR(5)        NOT NULL,           -- 법정동 코드(시군구)
    deal_ymd         CHAR(6)        NOT NULL,           -- 계약년월 YYYYMM
    deal_day         SMALLINT,                          -- 계약일
    apt_nm           TEXT,                              -- 아파트명
    jibun            TEXT,                              -- 지번
    road_nm          TEXT,                              -- 도로명
    road_nm_bonbun   TEXT,                              -- 도로명 본번
    road_nm_bubun    TEXT,                              -- 도로명 부번
    bldg_nm          TEXT,                              -- 건물명
    dong             TEXT,                              -- 법정동
    exclu_use_ar     NUMERIC(10,2),                     -- 전용면적(㎡)
    floor            SMALLINT,                          -- 층
    build_year       SMALLINT,                          -- 건축년도
    deal_amount      BIGINT,                            -- 거래금액(만원)
    deal_type        TEXT,                              -- 거래유형 (중개/직거래)
    cancel_deal_type TEXT,                              -- 해제여부
    cancel_deal_day  TEXT,                              -- 해제사유발생일
    req_gbn          TEXT,                              -- 거래구분
    rdealer_lawdnm   TEXT,                              -- 중개사 소재지
    created_at       TIMESTAMPTZ    DEFAULT NOW(),
    UNIQUE (lawd_cd, deal_ymd, deal_day, apt_nm, dong, jibun, exclu_use_ar, floor, deal_amount)
);
CREATE INDEX IF NOT EXISTS idx_apt_trade_lawd_deal ON apt_trade (lawd_cd, deal_ymd);
"""

DDL_SILV_TRADE = """
CREATE TABLE IF NOT EXISTS silv_trade (
    id               BIGSERIAL PRIMARY KEY,
    lawd_cd          CHAR(5)        NOT NULL,           -- 법정동 코드(시군구)
    deal_ymd         CHAR(6)        NOT NULL,           -- 계약년월 YYYYMM
    deal_day         SMALLINT,                          -- 계약일
    apt_nm           TEXT,                              -- 아파트/분양단지명
    jibun            TEXT,                              -- 지번
    dong             TEXT,                              -- 법정동
    exclu_use_ar     NUMERIC(10,2),                     -- 전용면적(㎡)
    floor            SMALLINT,                          -- 층
    deal_amount      BIGINT,                            -- 거래금액(만원)
    deal_type        TEXT,                              -- 거래유형
    cancel_deal_type TEXT,                              -- 해제여부
    cancel_deal_day  TEXT,                              -- 해제사유발생일
    created_at       TIMESTAMPTZ    DEFAULT NOW(),
    UNIQUE (lawd_cd, deal_ymd, deal_day, apt_nm, dong, jibun, exclu_use_ar, floor, deal_amount)
);
CREATE INDEX IF NOT EXISTS idx_silv_trade_lawd_deal ON silv_trade (lawd_cd, deal_ymd);
"""

DDL_APT_RENT = """
CREATE TABLE IF NOT EXISTS apt_rent (
    id               BIGSERIAL PRIMARY KEY,
    lawd_cd          CHAR(5)        NOT NULL,           -- 법정동 코드(시군구)
    deal_ymd         CHAR(6)        NOT NULL,           -- 계약년월 YYYYMM
    deal_day         SMALLINT,                          -- 계약일
    apt_nm           TEXT,                              -- 아파트명
    jibun            TEXT,                              -- 지번
    dong             TEXT,                              -- 법정동
    exclu_use_ar     NUMERIC(10,2),                     -- 전용면적(㎡)
    floor            SMALLINT,                          -- 층
    build_year       SMALLINT,                          -- 건축년도
    deposit          BIGINT,                            -- 보증금액(만원)
    monthly_rent     BIGINT,                            -- 월세금액(만원, 전세=0)
    contract_type    TEXT,                              -- 계약구분 (신규/갱신)
    contract_period  TEXT,                              -- 계약기간
    use_reinstate_yn TEXT,                              -- 갱신요구권 사용 여부
    created_at       TIMESTAMPTZ    DEFAULT NOW(),
    UNIQUE (lawd_cd, deal_ymd, deal_day, apt_nm, dong, jibun, exclu_use_ar, floor, deposit, monthly_rent)
);
CREATE INDEX IF NOT EXISTS idx_apt_rent_lawd_deal ON apt_rent (lawd_cd, deal_ymd);
"""

# 수집 진행 상태 기록 테이블 (재시작 시 이어받기용)
DDL_COLLECT_LOG = """
CREATE TABLE IF NOT EXISTS collect_log (
    id          BIGSERIAL PRIMARY KEY,
    table_name  TEXT        NOT NULL,
    lawd_cd     CHAR(5)     NOT NULL,
    deal_ymd    CHAR(6)     NOT NULL,
    rows_saved  INT         DEFAULT 0,
    status      TEXT        DEFAULT 'ok',   -- ok | error | empty
    message     TEXT,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (table_name, lawd_cd, deal_ymd)
);
"""


def init_db():
    """테이블이 없으면 생성"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL_APT_TRADE)
            cur.execute(DDL_SILV_TRADE)
            cur.execute(DDL_APT_RENT)
            cur.execute(DDL_COLLECT_LOG)
        conn.commit()
        logger.info("DB 초기화 완료")
    finally:
        conn.close()


def upsert_rows(table: str, columns: list[str], rows: list[tuple], conn) -> int:
    """
    ON CONFLICT DO NOTHING 방식으로 중복 없이 삽입.
    반환값: 실제 삽입된 행 수
    """
    if not rows:
        return 0
    col_str = ", ".join(columns)
    sql = f"INSERT INTO {table} ({col_str}) VALUES %s ON CONFLICT DO NOTHING"
    with conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=500)
        return cur.rowcount


def already_collected(table: str, lawd_cd: str, deal_ymd: str, conn) -> bool:
    """수집 로그에 해당 (table, lawd_cd, deal_ymd) 조합이 ok 상태로 존재하는지 확인"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM collect_log WHERE table_name=%s AND lawd_cd=%s AND deal_ymd=%s AND status='ok'",
            (table, lawd_cd, deal_ymd),
        )
        return cur.fetchone() is not None


def save_collect_log(table: str, lawd_cd: str, deal_ymd: str,
                     rows_saved: int, status: str, message: str, conn):
    """수집 결과 기록 (upsert)"""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO collect_log (table_name, lawd_cd, deal_ymd, rows_saved, status, message)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (table_name, lawd_cd, deal_ymd)
            DO UPDATE SET rows_saved=EXCLUDED.rows_saved,
                          status=EXCLUDED.status,
                          message=EXCLUDED.message,
                          collected_at=NOW()
            """,
            (table, lawd_cd, deal_ymd, rows_saved, status, message),
        )
