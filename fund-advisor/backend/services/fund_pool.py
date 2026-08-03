"""FundPoolService - 基金候选池 (RFC-018 ①).

提供全市场候选基金元信息, 供 AI 主动荐基。
- 温启动: 拉天天基金全市场排行列表 -> 建候选池(分批, 避免超时)
- 增量刷新: 覆盖更新 fund_candidate
- 查询: 按 fund_type / style / label 筛选
- 关键: 池子只存候选元信息, 净值按需拉取缓存(不强占库)
"""

import logging
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.models.fund_candidate import FundCandidate

logger = logging.getLogger(__name__)

# 天天基金全市场排行接口(近1年涨幅排序)
_RANK_URL = "https://fund.eastmoney.com/data/rankhandler.aspx"
_DEFAULT_PAGE_SIZE = 200

# 小候选集兜底(冷启动/温启动失败时, 至少能荐基): code, name, type
_PRESET_CANDIDATES = [
    ("000311", "景顺长城沪深300增强", "指数"),
    ("161725", "招商中证白酒指数", "指数"),
    ("018044", "广发高端制造股票", "股票"),
    ("005827", "易方达蓝筹精选混合", "混合"),
    ("110011", "易方达优质精选混合", "混合"),
    ("003096", "中欧医疗健康混合A", "混合"),
    ("001938", "中欧时代先锋股票A", "股票"),
    ("260108", "景顺长城新兴成长混合", "混合"),
    ("001714", "工银瑞信文体产业股票A", "股票"),
    ("004997", "广发高端制造混合A", "混合"),
    ("005668", "鹏华安盈宝货币A", "货币"),
    ("510300", "华泰柏瑞沪深300ETF联接A", "指数"),
    ("007300", "国联安中证全指半导体ETF联接A", "指数"),
    ("160632", "鹏华酒指数A", "指数"),
    ("012414", "国泰中证全指证券公司ETF联接A", "指数"),
    ("110020", "易方达沪深300ETF联接A", "指数"),
    ("161028", "富国中证新能源汽车指数A", "指数"),
    ("008854", "南方中证500ETF联接A", "指数"),
    ("000478", "建信中证500指数增强A", "指数"),
    ("000248", "汇添富中证主要消费ETF联接A", "指数"),
]


class FundPoolService:
    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────
    #  温启动: 全市场列表 -> 建候选池
    # ─────────────────────────────────────────
    async def warm_start(self, pages: int = 5, page_size: int = _DEFAULT_PAGE_SIZE) -> dict:
        """拉天天基金排行列表建池(分批)。

        pages: 拉多少页(每页200), 默认 5 页 = 1000 只, 足够做候选池。
        返回统计。若全失败则用 _PRESET_CANDIDATES 兜底。
        """
        fetched = 0
        errors = 0
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://fund.eastmoney.com/",
        }
        # 按类型分页拉, 使池内 fund_type 有真实值(rank 接口 ft 参数区分类型)
        type_map = {
            "股票": "gp", "混合": "hh", "指数": "zs",
            "债券": "zq", "QDII": "qdii", "货币": "hb",
        }
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            for ftype, ft_code in type_map.items():
                for page in range(1, pages + 1):
                    url = (
                        f"{_RANK_URL}?op=ph&dt=kf&ft={ft_code}&rs=&gs=0&sc=1nzf"
                        f"&st=desc&sd=2025-01-01&ed=2026-08-03&qdii="
                        f"&tabSubtype=,,,,,&pi={page}&pn={page_size}&dx=1"
                    )
                    try:
                        resp = await client.get(url)
                        rows = _parse_rank(resp.text, fund_type=ftype)
                        if not rows:
                            break
                        for r in rows:
                            FundCandidate.upsert(self.db, **r)
                        fetched += len(rows)
                        logger.info("pool warm_start[%s] page %d: +%d (total %d)",
                                    ftype, page, len(rows), fetched)
                    except Exception as e:  # noqa: BLE001
                        errors += 1
                        logger.warning("pool warm_start[%s] page %d failed: %s",
                                       ftype, page, e)
                        if errors >= 30:
                            break
                if errors >= 30:
                    break

        # 兜底: 若一只都没抓到, 用预设小候选集
        if fetched == 0:
            logger.info("pool warm_start failed, fallback to preset candidates")
            for code, name, ftype in _PRESET_CANDIDATES:
                FundCandidate.upsert(self.db, code, name, fund_type=ftype)
            fetched = len(_PRESET_CANDIDATES)

        total = self.db.execute(
            select(func.count(FundCandidate.id)).where(FundCandidate.status == 1)
        ).scalar_one_or_none() or 0
        return {"fetched": fetched, "errors": errors, "total_in_pool": int(total)}

    # ─────────────────────────────────────────
    #  查询 / 筛选
    # ─────────────────────────────────────────
    def list_candidates(
        self,
        fund_type: Optional[str] = None,
        style: Optional[str] = None,
        label: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        """候选池列表(可按类型/风格/标签/关键词筛选)。"""
        q = select(FundCandidate).where(FundCandidate.status == 1)
        if fund_type:
            q = q.where(FundCandidate.fund_type == fund_type)
        if style:
            q = q.where(FundCandidate.style == style)
        if label:
            q = q.where(FundCandidate.label.like(f"%{label}%"))
        if keyword:
            q = q.where(
                (FundCandidate.fund_code.like(f"%{keyword}%"))
                | (FundCandidate.fund_name.like(f"%{keyword}%"))
            )
        # MySQL 不支持 NULLS LAST (PostgreSQL 语法) -> 用 nav_change_pct 可能为 null, 加 IS NULL 排序保证稳定
        q = q.order_by(
            FundCandidate.nav_change_pct.is_(None),  # False(非空)在前
            FundCandidate.nav_change_pct.desc(),
            FundCandidate.fund_code.asc(),
        ).limit(limit)
        rows = self.db.execute(q).scalars().all()
        return [self._to_dict(r) for r in rows]

    def counts(self) -> dict:
        """候选池统计(总数/各类型数)。"""
        total = self.db.execute(
            select(func.count(FundCandidate.id)).where(FundCandidate.status == 1)
        ).scalar_one() or 0
        by_type = dict(
            self.db.execute(
                select(FundCandidate.fund_type, func.count(FundCandidate.id))
                .where(FundCandidate.status == 1)
                .group_by(FundCandidate.fund_type)
            ).all()
        )
        return {"total": int(total), "by_type": by_type}

    def get_by_code(self, fund_code: str) -> Optional[dict]:
        row = self.db.execute(
            select(FundCandidate).where(
                FundCandidate.fund_code == fund_code, FundCandidate.status == 1
            )
        ).scalar_one_or_none()
        return self._to_dict(row) if row else None

    def _to_dict(self, r: FundCandidate) -> dict:
        return {
            "fund_code": r.fund_code,
            "fund_name": r.fund_name,
            "fund_type": r.fund_type,
            "style": r.style,
            "scale": float(r.scale) if r.scale is not None else None,
            "inception_date": str(r.inception_date) if r.inception_date else None,
            "latest_nav": float(r.latest_nav) if r.latest_nav is not None else None,
            "nav_change_pct": float(r.nav_change_pct) if r.nav_change_pct is not None else None,
            "label": r.label,
            "open_apply": bool(r.open_apply),
        }


def _parse_rank(text: str, fund_type: Optional[str] = None) -> list:
    """解析天天基金排行接口 JSONP -> 候选行列表(可附基金类型)。"""
    import json
    import re

    m = re.search(r"datas:\s*(\[[^\]]*\])", text)
    if not m:
        return []
    try:
        datas = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return []

    rows = []
    for line in datas:
        parts = line.split(",")
        if len(parts) < 18:
            continue
        code = parts[0]
        name = parts[1]
        if not code or not name:
            continue
        try:
            latest_nav = float(parts[4]) if parts[4] else None
        except Exception:  # noqa: BLE001
            latest_nav = None
        try:
            change_pct = float(parts[6]) if parts[6] else None
        except Exception:  # noqa: BLE001
            change_pct = None
        # 近1月/近1年涨幅(估风格: 涨幅激进/稳健可粗判, 先只存原始)
        try:
            month_chg = float(parts[8]) if parts[8] else None
            year_chg = float(parts[11]) if parts[11] else None
        except Exception:  # noqa: BLE001
            month_chg = year_chg = None
        # 成立日期
        inception = None
        if len(parts) > 16 and parts[16]:
            try:
                inception = datetime.strptime(parts[16][:10], "%Y-%m-%d").date()
            except Exception:  # noqa: BLE001
                inception = None
        # 规模(亿)(通常最后一个逗号段)
        scale = None
        for seg in (parts[-1], parts[17] if len(parts) > 17 else ""):
            try:
                v = float(seg)
                if 0 < v < 100000:
                    scale = v
                    break
            except Exception:  # noqa: BLE001
                continue
        # 开放申购标记(部分行含 1=开放)
        open_apply = 1
        rows.append({
            "fund_code": code,
            "fund_name": name,
            "latest_nav": latest_nav,
            "nav_change_pct": change_pct,
            "inception_date": inception,
            "scale": scale,
            "open_apply": open_apply,
            "label": None,
            "fund_type": fund_type,
            "style": None,
        })
    return rows
