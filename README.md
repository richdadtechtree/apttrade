# 부동산 실거래가 데이터 수집 시스템

국토교통부 공공데이터포털 3개 API에서 15년치 부동산 거래 데이터를 수집·저장합니다.

## 수집 데이터

| 테이블 | 설명 | 엔드포인트 |
|--------|------|------------|
| `apt_trade` | 아파트 매매 실거래가 | `RTMSDataSvcAptTrade` |
| `silv_trade` | 분양권 전매 실거래가 | `RTMSDataSvcSilvTrade` |
| `apt_rent` | 아파트 전월세 실거래가 | `RTMSDataSvcAptRent` |

## 파일 구조

```
AptTrade/
├── .env                 # 인증키 및 DB 연결 정보 (서버에서 직접 생성)
├── requirements.txt     # Python 패키지 목록
├── db.py                # PostgreSQL 연결 및 테이블 DDL
├── collector.py         # API 호출 / 파싱 / 페이지네이션
├── lawd_codes.py        # 전국 시군구 법정동 코드 딕셔너리
├── run_collect.py       # 일괄 수집 메인 스크립트
├── scheduler.py         # 월간 자동 수집 스케줄러
└── collect.log          # 수집 로그 (자동 생성)
```

## 서버 설정

### 1. `.env` 파일 생성

```dotenv
# 공공데이터포털 인증키 (디코딩된 키 사용)
SERVICE_KEY=your_decoded_service_key_here

# PostgreSQL 연결
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=realestate
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password_here
```

### 2. 패키지 설치

```bash
pip install -r requirements.txt
# dateutil 별도 설치 필요
pip install python-dateutil
```

### 3. PostgreSQL 데이터베이스 생성

```sql
CREATE DATABASE realestate;
```

## 실행 방법

### 15년치 전체 수집 (최초 1회)

```bash
# 전체 전국 데이터 (2010년 1월 ~ 현재), 워커 3개
python run_collect.py

# 특정 기간만
python run_collect.py --from 202001 --to 202412

# 특정 유형만 (매매)
python run_collect.py --type apt_trade

# 특정 지역만 (강남구)
python run_collect.py --lawd 11680

# 병렬 워커 수 조정 (API 과호출 주의, 최대 5 권장)
python run_collect.py --workers 5
```

> **참고**: 전국 시군구 ~250개 × 15년 × 12개월 × 3유형 ≈ **135,000건** 요청.  
> 워커 3개 기준 약 **8~12시간** 소요 예상.

### 수집 이어받기

`collect_log` 테이블에 완료 기록이 있는 조합은 자동 스킵되므로  
중단 후 `python run_collect.py`를 다시 실행하면 이어서 수집됩니다.

### 월간 자동 수집 스케줄러

```bash
# 백그라운드 실행
nohup python scheduler.py &> scheduler.log &

# 또는 systemd 서비스 등록 (권장)
```

#### systemd 서비스 예시 (`/etc/systemd/system/apt-trade-scheduler.service`)

```ini
[Unit]
Description=AptTrade Monthly Scheduler
After=network.target postgresql.service

[Service]
WorkingDirectory=/path/to/AptTrade
ExecStart=/usr/bin/python3 /path/to/AptTrade/scheduler.py
Restart=always
EnvironmentFile=/path/to/AptTrade/.env
User=ubuntu

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable apt-trade-scheduler
sudo systemctl start apt-trade-scheduler
```

## 수집 상태 확인

```sql
-- 테이블별 수집 행 수 확인
SELECT 'apt_trade' AS tbl, COUNT(*) FROM apt_trade
UNION ALL
SELECT 'silv_trade', COUNT(*) FROM silv_trade
UNION ALL
SELECT 'apt_rent', COUNT(*) FROM apt_rent;

-- 수집 오류 목록 확인
SELECT * FROM collect_log WHERE status = 'error' ORDER BY collected_at DESC;

-- 특정 지역/월 수집 현황
SELECT table_name, deal_ymd, SUM(rows_saved) AS rows
FROM collect_log
WHERE lawd_cd = '11680' AND status = 'ok'
GROUP BY table_name, deal_ymd
ORDER BY deal_ymd;
```

## 주요 설계 사항

- **중복 방지**: `ON CONFLICT DO NOTHING` + `collect_log` 기반 스킵
- **재시도**: 최대 5회, 지수 백오프 (2^n초)
- **페이지네이션**: `numOfRows=1000`, `totalCount` 기반 자동 페이지 순회
- **병렬 수집**: `ThreadPoolExecutor` (기본 워커 3개)
- **요청 딜레이**: 페이지 간 0.2초 슬립 (과도한 호출 방지)
