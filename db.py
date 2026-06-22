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

# 최고가 관리 테이블 (현재까지 최고가)
DDL_APT_MAX_PRICE = """
CREATE TABLE IF NOT EXISTS apt_max_price (
    id               BIGSERIAL PRIMARY KEY,
    monitored_id     BIGINT         UNIQUE,             -- JSON의 id
    sido             TEXT,                              -- 시도
    sigungu          TEXT,                              -- 시군구
    dong             TEXT,                              -- 법정동
    sigungu_code     CHAR(5)        NOT NULL,           -- 시군구코드
    apt_name         TEXT           NOT NULL,           -- 아파트명
    area             TEXT           NOT NULL,           -- 면적 (예: "59")
    jibun_addr       TEXT,                              -- 지번주소
    build_year       TEXT,                              -- 건축년도
    prev_max_price   BIGINT,                            -- 이전 최고가
    prev_max_date    VARCHAR(10),                       -- 이전 최고가 날짜 YYYY-MM-DD
    prev_max_floor   VARCHAR(10),                       -- 이전 최고가 층
    prev_max_dong    VARCHAR(50),                       -- 이전 최고가 동
    last_max_price   BIGINT,                            -- 최종 최고가
    max_price_date   VARCHAR(10),                       -- 최종 최고가 날짜 YYYY-MM-DD
    max_price_floor  VARCHAR(10),                       -- 최종 최고가 층
    max_price_dong   VARCHAR(50),                       -- 최종 최고가 동
    last_update      TIMESTAMPTZ,                       -- 최종 업데이트 일시
    created_at       TIMESTAMPTZ    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_apt_max_price_key ON apt_max_price (sigungu_code, apt_name, area);
"""

# 오늘 신고가 관리 테이블 (오늘 신규 신고가 발생 내역)
DDL_APT_TODAY_MAX_PRICE = """
CREATE TABLE IF NOT EXISTS apt_today_max_price (
    id               BIGSERIAL PRIMARY KEY,
    monitored_id     BIGINT,                            -- JSON의 id
    sido             TEXT,
    sigungu          TEXT,
    dong             TEXT,
    sigungu_code     CHAR(5)        NOT NULL,
    apt_name         TEXT           NOT NULL,
    area             TEXT           NOT NULL,
    jibun_addr       TEXT,
    deal_amount      BIGINT         NOT NULL,           -- 거래금액
    deal_date        VARCHAR(10)    NOT NULL,           -- 거래일 YYYY-MM-DD
    floor            VARCHAR(10),                       -- 층
    dong_nm          VARCHAR(50),                       -- 동
    prev_max_price   BIGINT,                            -- 이전 최고가
    created_at       TIMESTAMPTZ    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_apt_today_max_price_date ON apt_today_max_price (deal_date);
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
            cur.execute(DDL_APT_MAX_PRICE)
            cur.execute(DDL_APT_TODAY_MAX_PRICE)
        conn.commit()
        logger.info("DB 초기화 완료")
    finally:
        conn.close()


def upsert_rows(table: str, columns: list[str], rows: list[tuple], conn) -> int:
    """
    중복 등록 방지 및 기존 데이터 업데이트(예: 취소 거래 정보 반영).
    반환값: 실제 삽입/업데이트된 행 수
    """
    if not rows:
        return 0
    col_str = ", ".join(columns)
    
    # 테이블별 unique key 컬럼 목록 및 업데이트할 컬럼 정의
    if table == "apt_trade":
        conflict_cols = "lawd_cd, deal_ymd, deal_day, apt_nm, dong, jibun, exclu_use_ar, floor, deal_amount"
        update_cols = ["cancel_deal_type", "cancel_deal_day", "deal_type", "req_gbn", "rdealer_lawdnm"]
    elif table == "silv_trade":
        conflict_cols = "lawd_cd, deal_ymd, deal_day, apt_nm, dong, jibun, exclu_use_ar, floor, deal_amount"
        update_cols = ["cancel_deal_type", "cancel_deal_day", "deal_type"]
    elif table == "apt_rent":
        conflict_cols = "lawd_cd, deal_ymd, deal_day, apt_nm, dong, jibun, exclu_use_ar, floor, deposit, monthly_rent"
        update_cols = ["contract_type", "contract_period", "use_reinstate_yn"]
    else:
        conflict_cols = None
        update_cols = []

    if conflict_cols and update_cols:
        update_str = ", ".join([f"{col}=EXCLUDED.{col}" for col in update_cols])
        sql = f"""
            INSERT INTO {table} ({col_str}) VALUES %s
            ON CONFLICT ({conflict_cols})
            DO UPDATE SET {update_str}
        """
    else:
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


def get_registered_lawd_codes() -> list[str]:
    """
    apt_complex 테이블에서 등록된 단지들의 고유 법정동 코드(시군구 5자리) 목록을 반환.
    만약 테이블이 없거나 데이터가 없으면 빈 리스트 반환.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # apt_complex 테이블이 존재하는지 확인
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'apt_complex'
                );
            """)
            exists = cur.fetchone()[0]
            if not exists:
                logger.warning("apt_complex 테이블이 데이터베이스에 존재하지 않습니다.")
                return []
                
            # bjd_code의 앞 5자리가 lawd_cd 임
            cur.execute("""
                SELECT DISTINCT LEFT(bjd_code, 5) 
                FROM apt_complex 
                WHERE bjd_code IS NOT NULL AND length(bjd_code) >= 5
                ORDER BY 1
            """)
            rows = cur.fetchall()
            return [r[0] for r in rows if r[0]]
    except Exception as e:
        logger.error(f"등록단지 지역 코드 조회 실패: {e}")
        return []
    finally:
        conn.close()
