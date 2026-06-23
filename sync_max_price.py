"""
sync_max_price.py — monitored_lists_backup.json 데이터 기반 최고가 및 오늘 신고가 관리 모듈

주요 기능:
    1. monitored_lists_backup.json 백업 데이터를 데이터베이스(apt_max_price)에 최초/강제 동기화 (마이그레이션)
    2. 수집된 신규 실거래가 중에서 최고가 경신 건(신고가) 감지 및 DB 테이블(apt_max_price, apt_today_max_price) 반영
    3. 감지된 신규 신고가 데이터를 기반으로 monitored_lists_backup.json 파일 자체 업데이트 및 저장
"""

import os
import json
import logging
import argparse
from datetime import datetime
from db import get_conn

logger = logging.getLogger(__name__)


def migrate_json_to_db(json_path: str):
    """
    monitored_lists_backup.json 파일을 읽어서 apt_max_price 테이블에 적재합니다. (최초 1회 마이그레이션용)
    """
    logger.info(f"JSON 데이터를 DB(apt_max_price)로 마이그레이션 시작: {json_path}")
    if not os.path.exists(json_path):
        logger.error(f"파일을 찾을 수 없습니다: {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    lists = data.get("lists", {})
    records = []

    for region, apts in lists.items():
        if region == "★ 전체 통합":
            # 전체 통합 리스트는 개별 지역 리스트와 중복되므로 스킵하여 데이터 중복 입력 방지
            continue
        for apt in apts:
            monitored_id = apt.get("id")
            if not monitored_id:
                continue

            # 문자열 수치값 파싱
            prev_max_price = apt.get("prev_max_price")
            if prev_max_price == "" or prev_max_price is None:
                prev_max_price = 0
            else:
                try:
                    prev_max_price = int(prev_max_price)
                except ValueError:
                    prev_max_price = 0

            last_max_price = apt.get("last_max_price")
            if last_max_price == "" or last_max_price is None:
                last_max_price = 0
            else:
                try:
                    last_max_price = int(last_max_price)
                except ValueError:
                    last_max_price = 0

            # 업데이트 시각 파싱
            last_update_str = apt.get("last_update")
            last_update = None
            if last_update_str:
                for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        last_update = datetime.strptime(last_update_str, fmt)
                        break
                    except ValueError:
                        continue

            records.append((
                monitored_id,
                apt.get("sido"),
                apt.get("sigungu"),
                apt.get("dong"),
                apt.get("sigungu_code"),
                apt.get("apt_name"),
                str(apt.get("area")),
                apt.get("jibun_addr"),
                str(apt.get("build_year")),
                prev_max_price,
                apt.get("prev_max_date") or None,
                str(apt.get("prev_max_floor")) if apt.get("prev_max_floor") is not None else None,
                apt.get("prev_max_dong") or None,
                last_max_price,
                apt.get("max_price_date") or None,
                str(apt.get("max_price_floor")) if apt.get("max_price_floor") is not None else None,
                apt.get("max_price_dong") or None,
                last_update
            ))

    if not records:
        logger.warning("마이그레이션할 레코드가 없습니다.")
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            sql = """
                INSERT INTO apt_max_price (
                    monitored_id, sido, sigungu, dong, sigungu_code, apt_name, area, jibun_addr, build_year,
                    prev_max_price, prev_max_date, prev_max_floor, prev_max_dong,
                    last_max_price, max_price_date, max_price_floor, max_price_dong, last_update
                ) VALUES %s
                ON CONFLICT (monitored_id) DO UPDATE SET
                    sido = EXCLUDED.sido,
                    sigungu = EXCLUDED.sigungu,
                    dong = EXCLUDED.dong,
                    sigungu_code = EXCLUDED.sigungu_code,
                    apt_name = EXCLUDED.apt_name,
                    area = EXCLUDED.area,
                    jibun_addr = EXCLUDED.jibun_addr,
                    build_year = EXCLUDED.build_year,
                    prev_max_price = EXCLUDED.prev_max_price,
                    prev_max_date = EXCLUDED.prev_max_date,
                    prev_max_floor = EXCLUDED.prev_max_floor,
                    prev_max_dong = EXCLUDED.prev_max_dong,
                    last_max_price = EXCLUDED.last_max_price,
                    max_price_date = EXCLUDED.max_price_date,
                    max_price_floor = EXCLUDED.max_price_floor,
                    max_price_dong = EXCLUDED.max_price_dong,
                    last_update = EXCLUDED.last_update
            """
            execute_values(cur, sql, records)
            conn.commit()
            logger.info(f"성공적으로 {len(records)}개의 모니터링 아파트 최고가 정보를 DB에 마이그레이션했습니다.")
    except Exception as e:
        conn.rollback()
        logger.error(f"마이그레이션 실패: {e}")
        raise e
    finally:
        conn.close()


def check_and_update_max_prices(conn) -> list:
    """
    최근 수집된 실거래가(최근 1일 이내) 중에서 기존 최고가(apt_max_price)를 경신한 거래를 찾아냅니다.
    경신된 경우:
      1. apt_max_price 테이블 업데이트 (last_max_price, max_price_date 등 갱신 및 기존 값은 prev_max_price로 이동)
      2. apt_today_max_price 테이블에 신규 신고가 이력 기록 (주소, 단지명, 면적 등 기본 정보를 포함하여 저장)
    """
    logger.info("신규 신고가 검사 시작...")
    
    # 쿼리: apt_trade와 silv_trade 테이블에서 각각 최근 1일 이내 생성된 건 중
    # monitored 리스트 단지와 매핑되고 deal_amount가 기존 최고가보다 높은 건을 추출
    # 단, 취소거래(cancel_deal_type가 'O'이거나 값이 있는 경우)는 제외
    sql = """
    WITH union_trades AS (
        -- 1. 아파트 매매 실거래가
        SELECT 
            m.monitored_id,
            t.deal_amount,
            -- deal_ymd(YYYYMM)와 deal_day(일)를 결합하여 YYYY-MM-DD 형식으로 포맷팅
            TO_CHAR(TO_DATE(t.deal_ymd || LPAD(t.deal_day::text, 2, '0'), 'YYYYMMDD'), 'YYYY-MM-DD') as deal_date,
            t.floor::text as floor,
            t.bldg_nm as dong_nm, -- 아파트 동 정보는 bldg_nm에 파싱됨
            m.last_max_price as prev_max_price,
            t.exclu_use_ar,
            'apt_trade' as src_table
        FROM apt_trade t
        JOIN apt_max_price m ON 
            t.lawd_cd = m.sigungu_code 
            AND t.apt_nm = m.apt_name
            AND (TRUNC(t.exclu_use_ar)::text = m.area OR t.exclu_use_ar::text = m.area)
        WHERE t.created_at >= NOW() - INTERVAL '1 day'
          AND t.deal_amount > COALESCE(m.last_max_price, 0)
          AND (t.cancel_deal_type IS NULL OR t.cancel_deal_type = '')
          
        UNION ALL
        
        -- 2. 분양권 전매 실거래가
        SELECT 
            m.monitored_id,
            t.deal_amount,
            TO_CHAR(TO_DATE(t.deal_ymd || LPAD(t.deal_day::text, 2, '0'), 'YYYYMMDD'), 'YYYY-MM-DD') as deal_date,
            t.floor::text as floor,
            NULL as dong_nm, -- 분양권은 동 정보 없음
            m.last_max_price as prev_max_price,
            t.exclu_use_ar,
            'silv_trade' as src_table
        FROM silv_trade t
        JOIN apt_max_price m ON 
            t.lawd_cd = m.sigungu_code 
            AND t.apt_nm = m.apt_name
            AND (TRUNC(t.exclu_use_ar)::text = m.area OR t.exclu_use_ar::text = m.area)
        WHERE t.created_at >= NOW() - INTERVAL '1 day'
          AND t.deal_amount > COALESCE(m.last_max_price, 0)
          AND (t.cancel_deal_type IS NULL OR t.cancel_deal_type = '')
    ),
    ranked_trades AS (
        SELECT 
            *,
            ROW_NUMBER() OVER (PARTITION BY monitored_id ORDER BY deal_amount DESC, deal_date DESC) as rn
        FROM union_trades
    )
    SELECT 
        monitored_id,
        deal_amount,
        deal_date,
        floor,
        dong_nm,
        prev_max_price,
        exclu_use_ar
    FROM ranked_trades 
    WHERE rn = 1;
    """
    
    with conn.cursor() as cur:
        # 매일 새로운 신고가 단지 데이터만 남기기 위해 기존 오늘 신고가 데이터를 비웁니다.
        cur.execute("TRUNCATE TABLE apt_today_max_price;")
        
        cur.execute(sql)
        new_max_list = cur.fetchall()
        
        if not new_max_list:
            logger.info("새로운 신고가가 발견되지 않았습니다.")
            return []
            
        logger.info(f"신규 신고가 {len(new_max_list)}건 감지됨. DB 및 JSON 반영 작업 진행...")
        
        inserted_today = []
        for row in new_max_list:
            monitored_id, deal_amount, deal_date, floor, dong_nm, prev_max_price, exclu_use_ar = row
            
            # 1. 오늘 신고가 테이블(apt_today_max_price)에 이력 추가 (기본 정보를 apt_max_price 테이블에서 복사)
            cur.execute("""
                INSERT INTO apt_today_max_price (
                    monitored_id, sido, sigungu, dong, sigungu_code, apt_name, area, jibun_addr,
                    deal_amount, deal_date, floor, dong_nm, prev_max_price
                )
                SELECT 
                    monitored_id, sido, sigungu, dong, sigungu_code, apt_name, area, jibun_addr,
                    %s, %s, %s, %s, %s
                FROM apt_max_price
                WHERE monitored_id = %s
                RETURNING id;
            """, (deal_amount, deal_date, floor, dong_nm, prev_max_price, monitored_id))
            
            # 2. 최고가 테이블(apt_max_price) 갱신
            cur.execute("""
                UPDATE apt_max_price
                SET 
                    prev_max_price = last_max_price,
                    prev_max_date = max_price_date,
                    prev_max_floor = max_price_floor,
                    prev_max_dong = max_price_dong,
                    last_max_price = %s,
                    max_price_date = %s,
                    max_price_floor = %s,
                    max_price_dong = %s,
                    last_update = NOW()
                WHERE monitored_id = %s;
            """, (deal_amount, deal_date, floor, dong_nm, monitored_id))
            
            inserted_today.append({
                "monitored_id": monitored_id,
                "deal_amount": deal_amount,
                "deal_date": deal_date,
                "floor": floor,
                "dong_nm": dong_nm,
                "prev_max_price": prev_max_price,
                "exclu_use_ar": float(exclu_use_ar) if exclu_use_ar is not None else 0.0
            })
            
        return inserted_today


def update_json_file(json_path: str, new_max_prices: list):
    """
    새로운 신고가 목록을 monitored_lists_backup.json 파일에 반영하여 업데이트합니다.
    """
    if not new_max_prices:
        return
        
    logger.info(f"JSON 파일 업데이트 시작: {json_path}")
    if not os.path.exists(json_path):
        logger.error(f"업데이트할 파일을 찾을 수 없습니다: {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    lists = data.get("lists", {})
    updates_map = {item["monitored_id"]: item for item in new_max_prices}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    updated_count = 0
    for region, apts in lists.items():
        # "★ 전체 통합" 리스트는 나중에 일괄 적용하거나, 개별 갱신
        for apt in apts:
            apt_id = apt.get("id")
            if apt_id in updates_map:
                up = updates_map[apt_id]
                
                # 기존 최고가를 prev로 밀어냄
                apt["prev_max_price"] = apt.get("last_max_price")
                apt["prev_max_date"] = apt.get("max_price_date")
                apt["prev_max_floor"] = apt.get("max_price_floor")
                apt["prev_max_dong"] = apt.get("max_price_dong") or ""
                
                # 신규 최고가 반영
                apt["last_max_price"] = up["deal_amount"]
                apt["max_price_date"] = up["deal_date"]
                apt["max_price_floor"] = up["floor"]
                apt["max_price_dong"] = up["dong_nm"] or ""
                apt["last_update"] = now_str
                
                # trade_data 추가
                if "trade_data" not in apt:
                    apt["trade_data"] = []
                
                trade_exists = any(
                    t.get("price") == float(up["deal_amount"]) and t.get("date") == up["deal_date"]
                    for t in apt["trade_data"]
                )
                if not trade_exists:
                    apt["trade_data"].append({
                        "price": float(up["deal_amount"]),
                        "date": up["deal_date"],
                        "area": up["exclu_use_ar"],
                        "floor": int(up["floor"]) if up["floor"] and up["floor"].isdigit() else up["floor"],
                        "dong": up["dong_nm"] or ""
                    })
                updated_count += 1

    # 백업 파일 타임스탬프 갱신
    data["backup_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    logger.info(f"JSON 파일 갱신 완료 ({updated_count}개 단지 데이터가 JSON 파일에 갱신되었습니다)")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    parser = argparse.ArgumentParser(description="monitored_lists_backup.json 신고가 동기화 툴")
    parser.add_argument("--migrate", action="store_true", help="JSON 데이터를 DB로 최초 마이그레이션")
    parser.add_argument("--file", default="monitored_lists_backup.json", help="대상 JSON 파일 경로")
    parser.add_argument("--check", action="store_true", help="수동 신규 신고가 체크 및 갱신 실행")
    
    args = parser.parse_args()
    
    if args.migrate:
        migrate_json_to_db(args.file)
    elif args.check:
        conn = get_conn()
        try:
            new_max = check_and_update_max_prices(conn)
            conn.commit()
            if new_max:
                update_json_file(args.file, new_max)
        except Exception as e:
            conn.rollback()
            logger.error(f"오류 발생: {e}")
        finally:
            conn.close()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
