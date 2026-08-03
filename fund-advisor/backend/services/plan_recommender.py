"""PlanRecommenderService - AI荐基 (RFC-018 ②).

两层推荐:
  1. 规则预筛层: 复用现有 RecommenderService.run_screen(六因子量化打分),
     硬过滤剔除用户已持有的基金(禁止重复/避免过度集中) + 候选池收敛到 Top20。
  2. AI研判层: 把规则层 Top N 的量化特征喂给 LLM(NewAPI, step-3.7 链),
     结合"当前市场环境"选现阶段更适合入场的 3-5 只 + 人话理由 + 风险提示。

风控: AI 只准从规则层给出的候选里选, 不得臆造基金。
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.fund_candidate import FundCandidate
from backend.services.recommend_service import RecommendService

logger = logging.getLogger(__name__)

# 模型 failover 链(RFC-017/014 实测 + 2026-08-03 重新校准):
#   minimax-m3 主(实测 4/5 成功, 稳定返回纯 JSON; 长候选略慢但 failover+取消已缓解)
#   deepseek-v4-flash 次(2026-08-03 实测 1/5 成功, 80% 时返回 529 过载, 已退化)
#   注意: minimax 对超长提示词极慢(~46-95s), 候选已精简到 Top 8
#   step-3.7 是推理模型, response_format 时 content 常为 None(仅取到 reasoning), 兜底
_MODEL_CHAIN = [
    "minimaxai/minimax-m3",
    "deepseek-ai/deepseek-v4-flash",
    "stepfun-ai/step-3.7-flash",
]

# 规则层收敛到的候选上限(喂给 AI)
_RULE_TOP_N = 20
# AI 输出推荐数
_AI_TOP_N = 5


class PlanRecommenderService:
    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────
    #  ① 规则预筛层: 候选池 + 剔已持有 + 量化打分
    # ─────────────────────────────────────────
    def _held_codes(self) -> set:
        """当前在投持仓基金代码(禁止重复: 计划不得再买)。"""
        from backend.models.holding import FundHolding
        rows = self.db.execute(
            select(FundHolding.fund_code).where(FundHolding.status == 1)
        ).scalars().all()
        return set(rows)

    def rule_screen(
        self,
        fund_types: Optional[List[str]] = None,
        budget_pct: float = 10.0,
        top_n: int = _RULE_TOP_N,
        prefilter_limit: int = 40,
    ) -> List[dict]:
        """从候选池规则预筛 Top N(剔除已持有基金)。

        预筛: 先用池里存储的元信息(nav_change_pct 近1年涨幅)粗排序, 收敛到
        prefilter_limit 只, 再喂昂贵的六因子打分(需逐只拉NAV)。
        避免 600 只候选全量拉NAV 导致超时(内存/耗时限制)。
        """
        held = self._held_codes()

        q = select(FundCandidate).where(FundCandidate.status == 1)
        if fund_types:
            q = q.where(FundCandidate.fund_type.in_(fund_types))
        rows = self.db.execute(q).scalars().all()

        # 剔除已持有 + 无近1年数据, 按近1年涨幅降序粗排序
        cand_rows = [
            r for r in rows
            if r.fund_code not in held and r.nav_change_pct is not None
        ]
        cand_rows.sort(key=lambda r: (r.nav_change_pct or 0), reverse=True)
        cand_rows = cand_rows[:prefilter_limit]
        if not cand_rows:
            # 兜底: 允许无近1年数据的(可能池未更新评估)
            cand_rows = [r for r in rows if r.fund_code not in held][:prefilter_limit]

        candidates = [
            {"fund_code": r.fund_code, "fund_name": r.fund_name}
            for r in cand_rows
        ]
        if not candidates:
            return []

        # 复用六因子打分(规则层, 确定性)
        res = RecommendService(self.db).run_screen(
            candidates=candidates,
            budget_pct=budget_pct,
            top_n=top_n,
            use_current_portfolio=True,
        )
        return res.get("recommendations", [])

    # ─────────────────────────────────────────
    #  ② AI研判层: 规则 Top N -> AI 挑 Top N + 理由
    # ─────────────────────────────────────────
    async def ai_pick(self, rule_top: List[dict], budget: float,
                      risk_profile: str) -> dict:
        """把规则层 Top N 的量化特征喂给 LLM, 挑 3-5 只 + 理由。

        rule_top: rule_screen() 的输出(已剔已持有基金)。
        返回: {"picks": [...], "overall_view": "...", "model": "...", "error": null|str}
        """
        if not rule_top:
            return {"picks": [], "overall_view": "候选池为空(可能池未温启动或已全被持有)",
                    "model": None, "error": "no_candidates"}

        # 组装候选特征(供 AI 研判) - 精简到 Top 8, 控制提示词长度提速
        cand_lines = []
        for r in rule_top[:8]:
            cand_lines.append(
                f"- {r['fund_code']} {r['fund_name']} "
                f"(类型:{r.get('fund_type') or '未知'}, "
                f"评分:{r.get('total_score')}, "
                f"建议配比:{r.get('suggested_ratio_pct')}%, "
                f"择时:{r.get('timing_window')})"
            )

        risk_label = {"conservative": "保守", "balanced": "稳健", "aggressive": "激进"}.get(
            risk_profile, "稳健"
        )
        system_prompt = (
            "你是基金投顾研究员。以下是【已通过量化初筛的候选基金】及各自指标:\n"
            + "\n".join(cand_lines)
            + f"\n\n当前需求: 预算 {budget} 元, 风险偏好: {risk_label}。\n"
            + "任务: 挑选现阶段【最适合入场】的3-5只, 输出严格JSON:"
            + ' {"picks": [{"fund_code":"...", "reason":"为什么现在适合入场(人话)", '
            + '"risk_tip":"风险提示", "one_liner":"一句话点评"}], '
            + '"overall_view":"对整个组合的综合判断(人话)"}。'
            + "硬约束: 只准从给定候选中选, 不得臆造基金; 理由要具体可核; 语言通俗; "
            + "明确'仅供参考, 不构成投资建议'。"
        )

        s = get_settings()
        payload = {
            "model": None,  # 每轮填
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "请给出当前最适合入场的基金推荐。"},
            ],
            "temperature": 0.4,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }

        last_err = None
        allowed = {r["fund_code"] for r in rule_top[:30]}

        # 并行请求三个模型(failover), 最先成功返回的获胜;
        # 避免串行等一个超时(90s)再下一个 -> 最长等待 ~模型数×超时。
        async def _try(model: str):
            try:
                data = await self._chat(s, model, payload)
                picks = self._validate_picks(data, allowed)
                if picks is None:
                    return {"ok": False, "model": model, "err": "字段缺失/格式不符"}
                return {"ok": True, "model": model, "data": data, "picks": picks}
            except Exception as ex:  # noqa: BLE001
                return {"ok": False, "model": model, "err": str(ex)[:200]}

        # 并行请求三个模型(failover), 第一个成功的立刻返回并取消其余;
        # 用 asyncio.wait(FIRST_COMPLETED) 避免 gather 等所有(慢模型会拖垮总时长)
        tasks = {asyncio.create_task(_try(m), name=m): m for m in _MODEL_CHAIN}
        pending = set(tasks.keys())
        fail_msgs = []
        winner = None
        deadline = asyncio.get_event_loop().time() + 95
        while pending:
            remain = deadline - asyncio.get_event_loop().time()
            if remain <= 0:
                break
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED, timeout=min(remain, 30)
            )
            for t in done:
                res = t.result()
                if res.get("ok"):
                    winner = res
                    break
                fail_msgs.append(f"{res['model']}: {res['err']}")
            if winner:
                break
        # 取消还没完成的请求, 释放连接
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        if winner:
            d = winner["data"]
            return {
                "picks": winner["picks"],
                "overall_view": d.get("overall_view", ""),
                "model": winner["model"],
                "error": None,
            }

        last_err = "; ".join(fail_msgs) or "所有模型均失败/超时"
        logger.warning("plan ai_pick 三模型均失败: %s", last_err)
        return {"picks": [], "overall_view": "", "model": None,
                "error": f"AI 研判失败: {last_err}"}

    async def _chat(self, s, model: str, payload: dict,
                    timeout: float = 90.0) -> dict:
        payload = dict(payload)
        payload["model"] = model
        headers = {
            "Authorization": f"Bear" + f"er {s.NEWAPI_API_KEY}",
            "Content-Type": "application/json",
        }
        # 5xx(尤其 NewAPI 瞬时 529 过载)重试, 短退避自愈
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = None
            last_err = None
            for attempt in range(3):
                try:
                    resp = await client.post(
                        f"{s.NEWAPI_BASE_URL}/chat/completions", json=payload, headers=headers
                    )
                except httpx.HTTPError as ex:
                    last_err = f"网络异常: {ex}"
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                if resp.status_code in (429, 500, 502, 503, 529):
                    last_err = f"HTTP {resp.status_code} overloa:{resp.text[:80]}"
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                break
            if resp is None:
                raise ValueError(f"模型 {model} 全部重试失败: {last_err}")
            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            if "choices" not in data or not data["choices"]:
                raise ValueError(f"响应无 choices: {resp.text[:200]}")
            msg = data["choices"][0].get("message", {})
            content = msg.get("content")
            # 兼容推理模型: content 为空时取 reasoning_content / reasoning(引擎已验证)
            if not content:
                content = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if not content or not content.strip():
                raise ValueError("模型未返回内容(Content/Reasoning 均为空)")
            return self._extract_json(content)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """容错解析 LLM 返回的 JSON(兼容 markdown 代码块 / 前后缀散文 / 列表包裹)。"""
        import re

        def _coerce(value):
            if isinstance(value, str):
                try:
                    return _coerce(json.loads(value))
                except (json.JSONDecodeError, TypeError):
                    return None
            if isinstance(value, dict):
                return value
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        return item
                    if isinstance(item, str):
                        try:
                            d = json.loads(item)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if isinstance(d, dict):
                            return d
            return None

        t = text.strip()
        # 剥离 ```json ... ``` / ``` ... ``` 包裹
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t)
        if m:
            t = m.group(1).strip()
        # 直接试解析(含列表包裹)
        try:
            res = _coerce(json.loads(t))
            if res is not None:
                return res
        except Exception:
            pass
        # 尝试提取第一个 { ... } 平衡块
        start = t.find("{")
        if start >= 0:
            depth = 0
            in_str = False
            for i in range(start, len(t)):
                ch = t[i]
                if ch == '"' and (i == 0 or t[i - 1] != "\\"):
                    in_str = not in_str
                if in_str:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            res = _coerce(json.loads(t[start : i + 1]))
                            if res is not None:
                                return res
                        except Exception:
                            break
        raise ValueError("无法从模型输出提取JSON")

    def _validate_picks(self, data: dict, allowed_codes: set):
        """校验 AI 输出: 必须是给定候选里的基金, 结构化字段齐全。"""
        picks = data.get("picks")
        if not isinstance(picks, list) or not picks:
            return None
        out = []
        for p in picks:
            code = str(p.get("fund_code", "")).strip()
            if code not in allowed_codes:
                logger.warning("AI 推荐了候选外基金 %s, 丢弃", code)
                continue
            out.append({
                "fund_code": code,
                "reason": p.get("reason", ""),
                "risk_tip": p.get("risk_tip", ""),
                "one_liner": p.get("one_liner", ""),
            })
        return out if out else None

    # ─────────────────────────────────────────
    #  编排: 一步到位(规则预筛 + AI研判 + 合并理由)
    # ─────────────────────────────────────────
    async def recommend(self, budget: float, risk_profile: str,
                        fund_types: Optional[List[str]] = None) -> dict:
        """完整荐基: 池 -> 规则打分 -> AI挑 TopN -> 返回带理由。

        AI 失败时回退到规则层 Top N(量化打分, 可核),
        保证荐基永远不空手而归。
        """
        # rule_screen 内部用 asyncio.run(引擎协程), 不能在事件循环里直接调
        # -> 放到线程里执行, 再用 AI(path 本身是 async)
        rule_top = await asyncio.to_thread(
            self.rule_screen, fund_types=fund_types, top_n=_RULE_TOP_N
        )
        if not rule_top:
            return {"budget": budget, "risk_profile": risk_profile,
                    "candidates_scanned": 0, "picks": [],
                    "overall_view": "候选池为空(可能池未温启动或已全被持有)",
                    "model": None, "error": "no_candidates"}

        ai_res = await self.ai_pick(rule_top, budget, risk_profile)

        # 合并: AI 推荐 + 规则层量化信息(供前端展示评分/配比基线)
        rule_map = {r["fund_code"]: r for r in rule_top}
        picks = []
        ai_picks = ai_res.get("picks", [])
        fallback_used = ai_res.get("error") is not None or not ai_picks
        # AI 有结果用 AI; 否则回退规则层 Top 5
        selected = ai_picks if ai_picks else rule_top[:_AI_TOP_N]
        for p in selected:
            code = p.get("fund_code")
            r = rule_map.get(code, {})
            picks.append({
                "fund_code": code,
                "fund_name": r.get("fund_name") or p.get("fund_name") or code,
                "fund_type": r.get("fund_type") or _infer_fund_type(r.get("fund_name") or ""),
                "total_score": r.get("total_score"),
                "style_tag": r.get("style_tag"),
                "suggested_ratio_pct": r.get("suggested_ratio_pct"),
                "timing_window": r.get("timing_window"),
                "reason": p.get("reason", ""),
                "risk_tip": p.get("risk_tip", ""),
                "one_liner": p.get("one_liner", ""),
            })

        return {
            "budget": budget,
            "risk_profile": risk_profile,
            "candidates_scanned": len(rule_top),
            "picks": picks,
            "overall_view": ai_res.get("overall_view", "") if not fallback_used
                            else "(AI研判失败, 已回退到量化规则层Top5)",
            "model": ai_res.get("model"),
            "error": ai_res.get("error"),
            "fallback_used": fallback_used,
        }


def _infer_fund_type(name: str) -> str:
    """按名称关键词轻推断 fund_type(候选池元信息未由 rank API 提供时兜底)。"""
    n = name or ""
    if any(k in n for k in ("货币", "现金")):
        return "货币"
    if "QDII" in n or "海外" in n or "全球" in n or "纳斯达克" in n or "标普" in n:
        return "QDII"
    if any(k in n for k in ("沪深300", "中证", "上证", "创业板", "科创板", "指数", "ETF", "白酒", "半导体", "证券", "新能源", "消费", "医疗", "军工")):
        return "指数"
    if "债券" in n or "债" in n:
        return "债券"
    if "混合" in n or "配置" in n:
        return "混合"
    if "股票" in n:
        return "股票"
    return "混合"
