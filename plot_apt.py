"""
plot_apt.py — 단지별 매매가 시계열 점도표

사용법:
    python plot_apt.py --apt "래미안대치팰리스"
    python plot_apt.py --apt "래미안대치팰리스" --lawd 11680   # 강남구로 범위 좁히기
    python plot_apt.py --list                                  # 검색 가능한 단지명 목록 출력
    python plot_apt.py --search 래미안                         # 단지명 검색

출력: plot_<단지명>.html  (브라우저로 열면 인터랙티브 그래프)
"""

import os
import sys
import argparse
import psycopg2
import pandas as pd
import plotly.graph_objects as go
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "realestate"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


def search_apt(keyword: str, lawd_cd: str = None):
    """단지명 검색"""
    conn = get_conn()
    where = "WHERE apt_nm ILIKE %s"
    params = [f"%{keyword}%"]
    if lawd_cd:
        where += " AND lawd_cd = %s"
        params.append(lawd_cd)

    query = f"""
        SELECT apt_nm, lawd_cd, COUNT(*) AS cnt,
               MIN(deal_ymd) AS from_ym, MAX(deal_ymd) AS to_ym
        FROM apt_trade
        {where}
        GROUP BY apt_nm, lawd_cd
        ORDER BY cnt DESC
        LIMIT 30
    """
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df


def load_trade_data(apt_nm: str, lawd_cd: str = None) -> pd.DataFrame:
    """특정 단지 매매 데이터 로드"""
    conn = get_conn()
    where = "WHERE apt_nm = %s"
    params = [apt_nm]
    if lawd_cd:
        where += " AND lawd_cd = %s"
        params.append(lawd_cd)

    query = f"""
        SELECT
            deal_ymd,
            deal_day,
            exclu_use_ar,
            floor,
            deal_amount,
            dong,
            build_year,
            deal_type
        FROM apt_trade
        {where}
        ORDER BY deal_ymd, deal_day
    """
    df = pd.read_sql(query, conn, params=params)
    conn.close()

    # 날짜 컬럼 생성
    df["deal_day"] = df["deal_day"].fillna(1).astype(int).astype(str).str.zfill(2)
    df["date"] = pd.to_datetime(df["deal_ymd"] + df["deal_day"], format="%Y%m%d", errors="coerce")

    # 단가(만원/㎡) 계산
    df["unit_price"] = (df["deal_amount"] / df["exclu_use_ar"]).round(0)

    # 면적 구간 라벨
    def area_label(ar):
        if ar is None:
            return "기타"
        if ar < 50:
            return f"~50㎡"
        elif ar < 85:
            return f"~85㎡"
        elif ar < 135:
            return f"~135㎡"
        else:
            return f"135㎡~"

    df["area_grp"] = df["exclu_use_ar"].apply(area_label)
    return df


def plot(df: pd.DataFrame, apt_nm: str, output: str):
    """인터랙티브 점도표 생성"""
    colors = {
        "~50㎡":   "#60a5fa",
        "~85㎡":   "#34d399",
        "~135㎡":  "#f97316",
        "135㎡~":  "#f43f5e",
        "기타":    "#a78bfa",
    }

    fig = go.Figure()

    for grp in ["~50㎡", "~85㎡", "~135㎡", "135㎡~", "기타"]:
        sub = df[df["area_grp"] == grp]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["date"],
            y=sub["deal_amount"],
            mode="markers",
            name=grp,
            marker=dict(
                color=colors.get(grp, "#888"),
                size=6,
                opacity=0.7,
                line=dict(width=0.5, color="white"),
            ),
            customdata=sub[["exclu_use_ar", "floor", "unit_price", "deal_type", "dong"]].values,
            hovertemplate=(
                "<b>%{x|%Y년 %m월 %d일}</b><br>"
                "거래금액: <b>%{y:,}만원</b><br>"
                "전용면적: %{customdata[0]:.1f}㎡<br>"
                "층: %{customdata[1]}층<br>"
                "단가: %{customdata[2]:,.0f}만원/㎡<br>"
                "법정동: %{customdata[4]}<br>"
                "거래유형: %{customdata[3]}<extra></extra>"
            ),
        ))

    # 6개월 이동평균선
    df_sorted = df.sort_values("date").copy()
    df_sorted = df_sorted.set_index("date").resample("ME")["deal_amount"].median().reset_index()
    if len(df_sorted) > 1:
        fig.add_trace(go.Scatter(
            x=df_sorted["date"],
            y=df_sorted["deal_amount"],
            mode="lines",
            name="월별 중앙값",
            line=dict(color="white", width=2, dash="dot"),
            opacity=0.6,
        ))

    total_cnt = len(df)
    min_yr = df["date"].dt.year.min()
    max_yr = df["date"].dt.year.max()

    fig.update_layout(
        title=dict(
            text=f"<b>{apt_nm}</b> 매매 실거래가 ({min_yr}~{max_yr}) — 총 {total_cnt:,}건",
            font=dict(size=20, color="white"),
            x=0.02,
        ),
        plot_bgcolor="#0f172a",
        paper_bgcolor="#0f172a",
        font=dict(color="#cbd5e1", family="Pretendard, Noto Sans KR, sans-serif"),
        xaxis=dict(
            title="거래일",
            gridcolor="#1e293b",
            linecolor="#334155",
            showspikes=True,
            spikecolor="#64748b",
        ),
        yaxis=dict(
            title="거래금액 (만원)",
            gridcolor="#1e293b",
            linecolor="#334155",
            tickformat=",",
            showspikes=True,
            spikecolor="#64748b",
        ),
        legend=dict(
            bgcolor="#1e293b",
            bordercolor="#334155",
            borderwidth=1,
            font=dict(size=13),
        ),
        hovermode="closest",
        height=620,
        margin=dict(l=60, r=30, t=70, b=60),
        # 범위 선택 버튼
        xaxis_rangeslider_visible=True,
        xaxis_rangeslider=dict(bgcolor="#1e293b", bordercolor="#334155"),
    )

    fig.write_html(output)
    print(f"✅ 저장 완료: {output}")
    print(f"   브라우저에서 열어보세요: file://{os.path.abspath(output)}")


def main():
    parser = argparse.ArgumentParser(description="단지별 매매가 시계열 점도표")
    parser.add_argument("--apt",    help="단지명 (정확히 일치)")
    parser.add_argument("--lawd",   help="법정동 코드 (예: 11680 강남구)")
    parser.add_argument("--search", help="단지명 부분 검색")
    parser.add_argument("--list",   action="store_true", help="거래 건수 상위 단지 목록")
    parser.add_argument("--out",    help="출력 파일명 (기본: plot_<단지명>.html)")
    args = parser.parse_args()

    if args.list:
        print("\n[ 거래 건수 상위 아파트 단지 ]\n")
        conn = get_conn()
        df = pd.read_sql("""
            SELECT apt_nm, lawd_cd, COUNT(*) cnt
            FROM apt_trade
            GROUP BY apt_nm, lawd_cd
            ORDER BY cnt DESC LIMIT 30
        """, conn)
        conn.close()
        print(df.to_string(index=False))
        return

    if args.search:
        df = search_apt(args.search, args.lawd)
        if df.empty:
            print(f"'{args.search}' 검색 결과 없음")
        else:
            print(f"\n[ '{args.search}' 검색 결과 ]\n")
            print(df.to_string(index=False))
        return

    if not args.apt:
        parser.print_help()
        sys.exit(1)

    print(f"📥 [{args.apt}] 데이터 로딩 중...")
    df = load_trade_data(args.apt, args.lawd)

    if df.empty:
        print(f"데이터 없음. --search 로 단지명을 먼저 확인해보세요.")
        sys.exit(1)

    print(f"   {len(df):,}건 로드 완료")

    safe_name = args.apt.replace(" ", "_").replace("/", "_")
    output = args.out or f"plot_{safe_name}.html"
    plot(df, args.apt, output)


if __name__ == "__main__":
    main()
