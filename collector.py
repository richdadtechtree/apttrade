"""
collector.py — 공공데이터포털 부동산 실거래가 API 수집 모듈

지원 API:
    - 아파트 매매 실거래가 (RTMSDataSvcAptTrade)
    - 분양권 전매 실거래가 (RTMSDataSvcSilvTrade)
    - 아파트 전월세 실거래가 (RTMSDataSvcAptRent)
"""

import os
import time
import logging
import requests
import xml.etree.ElementTree as ET
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────
SERVICE_KEY = os.getenv("SERVICE_KEY", "")
BASE_URL = "https://apis.data.go.kr/1613000"

ENDPOINTS = {
    "apt_trade": {
        "url": f"{BASE_URL}/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
        "table": "apt_trade",
    },
    "silv_trade": {
        "url": f"{BASE_URL}/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade",
        "table": "silv_trade",
    },
    "apt_rent": {
        "url": f"{BASE_URL}/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
        "table": "apt_rent",
    },
}

MAX_ROWS_PER_PAGE = 1000   # API 최대 허용값
REQUEST_DELAY = 0.2        # 요청 간 딜레이(초) — 과도한 호출 방지
MAX_RETRIES = 5
RETRY_BACKOFF = 2.0        # 재시도 배수 (지수 백오프)


# ─────────────────────────────────────────────────
# 파싱 헬퍼
# ─────────────────────────────────────────────────
def _text(item: ET.Element, tag: str) -> Optional[str]:
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else None


def _int(item: ET.Element, tag: str) -> Optional[int]:
    v = _text(item, tag)
    if v is None:
        return None
    v = v.replace(",", "").strip()
    try:
        return int(v)
    except ValueError:
        return None


def _float(item: ET.Element, tag: str) -> Optional[float]:
    v = _text(item, tag)
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _amount(item: ET.Element, tag: str) -> Optional[int]:
    """'12,000' 형태의 금액 → 정수(만원)"""
    v = _text(item, tag)
    if not v:
        return None
    v = v.replace(",", "").strip()
    try:
        return int(v)
    except ValueError:
        return None


# ─────────────────────────────────────────────────
# API 호출
# ─────────────────────────────────────────────────
def _fetch_page(url: str, lawd_cd: str, deal_ymd: str, page_no: int) -> ET.Element:
    """단일 페이지 XML 응답 반환. 실패 시 재시도."""
    params = {
        "serviceKey": SERVICE_KEY,
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ymd,
        "pageNo": page_no,
        "numOfRows": MAX_ROWS_PER_PAGE,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            # 공공데이터 API 에러 코드 확인
            result_code = root.findtext(".//resultCode")
            if result_code and result_code.strip() not in ("00", "000", "0000"):
                result_msg = root.findtext(".//resultMsg") or ""
                raise ValueError(f"API 오류 [{result_code}]: {result_msg}")
            return root
        except Exception as exc:
            wait = RETRY_BACKOFF ** attempt
            if attempt == MAX_RETRIES:
                raise
            logger.warning(f"재시도 {attempt}/{MAX_RETRIES} — {exc} (대기 {wait:.1f}s)")
            time.sleep(wait)


def _total_count(root: ET.Element) -> int:
    v = root.findtext(".//totalCount")
    try:
        return int(v) if v else 0
    except ValueError:
        return 0


def _items(root: ET.Element) -> list[ET.Element]:
    return root.findall(".//item")


# ─────────────────────────────────────────────────
# 데이터 파싱 — 거래유형별
# ─────────────────────────────────────────────────
def parse_apt_trade(item: ET.Element, lawd_cd: str, deal_ymd: str) -> tuple:
    """아파트 매매 실거래가 1건 파싱 → 튜플 반환"""
    return (
        lawd_cd,
        deal_ymd,
        _int(item, "dealDay"),
        _text(item, "aptNm"),
        _text(item, "jibun"),
        _text(item, "roadNm"),
        _text(item, "roadNmBonbun"),
        _text(item, "roadNmBubun"),
        _text(item, "aptDong"),
        _text(item, "umdNm"),             # 법정동
        _float(item, "excluUseAr"),
        _int(item, "floor"),
        _int(item, "buildYear"),
        _amount(item, "dealAmount"),
        _text(item, "dealingGbn"),         # 거래유형
        _text(item, "cdealType"),          # 해제여부
        _text(item, "cdealDay"),           # 해제사유발생일
        _text(item, "reqGbn"),
        _text(item, "rDealerLawdnm"),
    )


APT_TRADE_COLS = [
    "lawd_cd", "deal_ymd", "deal_day", "apt_nm", "jibun",
    "road_nm", "road_nm_bonbun", "road_nm_bubun", "bldg_nm", "dong",
    "exclu_use_ar", "floor", "build_year", "deal_amount",
    "deal_type", "cancel_deal_type", "cancel_deal_day",
    "req_gbn", "rdealer_lawdnm",
]


def parse_silv_trade(item: ET.Element, lawd_cd: str, deal_ymd: str) -> tuple:
    """분양권 전매 실거래가 1건 파싱"""
    return (
        lawd_cd,
        deal_ymd,
        _int(item, "dealDay"),
        _text(item, "aptNm"),
        _text(item, "jibun"),
        _text(item, "umdNm"),
        _float(item, "excluUseAr"),
        _int(item, "floor"),
        _amount(item, "dealAmount"),
        _text(item, "dealingGbn"),
        _text(item, "cdealType"),
        _text(item, "cdealDay"),
    )


SILV_TRADE_COLS = [
    "lawd_cd", "deal_ymd", "deal_day", "apt_nm", "jibun", "dong",
    "exclu_use_ar", "floor", "deal_amount",
    "deal_type", "cancel_deal_type", "cancel_deal_day",
]


def parse_apt_rent(item: ET.Element, lawd_cd: str, deal_ymd: str) -> tuple:
    """아파트 전월세 1건 파싱"""
    return (
        lawd_cd,
        deal_ymd,
        _int(item, "dealDay"),
        _text(item, "aptNm"),
        _text(item, "jibun"),
        _text(item, "umdNm"),
        _float(item, "excluUseAr"),
        _int(item, "floor"),
        _int(item, "buildYear"),
        _amount(item, "deposit"),
        _amount(item, "monthlyRent"),
        _text(item, "contractType"),
        _text(item, "contractPeriod"),
        _text(item, "useReinstatementYn"),
    )


APT_RENT_COLS = [
    "lawd_cd", "deal_ymd", "deal_day", "apt_nm", "jibun", "dong",
    "exclu_use_ar", "floor", "build_year",
    "deposit", "monthly_rent",
    "contract_type", "contract_period", "use_reinstate_yn",
]


# ─────────────────────────────────────────────────
# 공통 수집 함수
# ─────────────────────────────────────────────────
PARSERS = {
    "apt_trade":  (ENDPOINTS["apt_trade"]["url"],  parse_apt_trade,  APT_TRADE_COLS),
    "silv_trade": (ENDPOINTS["silv_trade"]["url"], parse_silv_trade, SILV_TRADE_COLS),
    "apt_rent":   (ENDPOINTS["apt_rent"]["url"],   parse_apt_rent,   APT_RENT_COLS),
}


def fetch_all_pages(data_type: str, lawd_cd: str, deal_ymd: str) -> tuple[list[tuple], list[str]]:
    """
    지정 API / 지역 / 월의 전체 페이지 수집.

    반환:
        (rows, columns)
    """
    url, parser, columns = PARSERS[data_type]
    all_rows: list[tuple] = []

    page_no = 1
    total = None

    while True:
        root = _fetch_page(url, lawd_cd, deal_ymd, page_no)
        if total is None:
            total = _total_count(root)

        items = _items(root)
        if not items:
            break

        for item in items:
            try:
                all_rows.append(parser(item, lawd_cd, deal_ymd))
            except Exception as e:
                logger.debug(f"파싱 오류 무시: {e}")

        if len(all_rows) >= total or len(items) < MAX_ROWS_PER_PAGE:
            break

        page_no += 1
        time.sleep(REQUEST_DELAY)

    return all_rows, columns
