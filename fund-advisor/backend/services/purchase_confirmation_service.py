"""仅将当次手动确认带入既有报告试算，不持久化、不交易、不生成新报告。"""
from copy import deepcopy
from datetime import timedelta, timezone

from backend.services.purchase_channel_service import SHANGHAI, decimal_value


def prepare_confirmation_report(report: dict, fund_code: str) -> dict:
    """只允许解除单一渠道未知原因，预算、冷却、质量等拦截不能被确认覆盖。"""
    if not isinstance(report, dict) or not isinstance(report.get('actions'), list):
        raise ValueError('报告动作格式异常')
    policy = report.get('execution_policy')
    if not isinstance(policy, dict) or policy.get('purchase_channel_gate') is not True:
        raise ValueError('旧报告不支持当次确认，请等待新版本生成的当天报告')
    result = deepcopy(report)
    if len(result['actions']) > 100:
        raise ValueError('报告动作过多')
    for action in result['actions']:
        if not isinstance(action, dict) or isinstance(action.get('action_amount'), bool):
            raise ValueError('报告动作格式异常')
        if action.get('policy_status') != 'blocked':
            continue
        action['action_amount'] = 0.0
        # 只复核被选中的同一基金，不解除其他基金的单日单只门禁。
        if (action.get('fund_code') == fund_code and action.get('action') in {'buy', 'add', 'increase'}
                and action.get('policy_reasons') == ['purchase_channel_unverified']):
            try:
                action['action_amount'] = float(min(decimal_value(20), decimal_value(action.get('raw_action_amount'))))
            except ValueError:
                action['action_amount'] = 0.0
    return result


def confirmation_valid_until(created_at, observed_at, now):
    """试算至多展示5分钟，且不能超过报告、证据有效期或14:45。"""
    created = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at
    clock = now.astimezone(SHANGHAI)
    return min(clock + timedelta(minutes=5), created.astimezone(SHANGHAI) + timedelta(minutes=30),
               observed_at.astimezone(SHANGHAI) + timedelta(minutes=30), clock.replace(hour=14, minute=45, second=0, microsecond=0))
