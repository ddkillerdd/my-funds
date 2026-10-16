"""当次下单页确认输入：不接收账号、密钥、截图或自动交易参数。"""
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from backend.services.purchase_channel_service import decimal_value


class PurchaseConfirmation(BaseModel):
    """仅接受手动确认的小额申购信息，绝不将公开抓取字段自动升级。"""

    model_config = ConfigDict(extra='forbid')

    fund_code: str = Field(pattern=r'^\d{6}$', min_length=6, max_length=6)
    platform: Literal['支付宝', '天天基金']
    payment_method: Literal['银行卡', '支付宝余额', '余额宝', '活期宝']
    purchase_status: Literal['open', 'paused', 'unknown']
    account_eligible: StrictBool
    subscription_fee_rate_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=9, decimal_places=6)
    min_purchase_rmb: Decimal | None = Field(default=None, ge=Decimal('0.01'), max_digits=15, decimal_places=2)
    verified_capacity_rmb: Decimal | None = Field(default=None, ge=0, le=20, max_digits=4, decimal_places=2)
    observed_at: AwareDatetime
    confirmed_by_user: StrictBool

    @field_validator('subscription_fee_rate_pct', 'min_purchase_rmb', 'verified_capacity_rmb', mode='before')
    @classmethod
    def validate_money(cls, value):
        """空值表示未知，拒绝布尔值、非有限值、负数及超大输入。"""
        return None if value is None else decimal_value(value)

    @field_validator('min_purchase_rmb', 'verified_capacity_rmb')
    @classmethod
    def validate_cents(cls, value):
        """金额只接受到分，避免提交与显示时发生静默取整差异。"""
        if value is not None and value != value.quantize(Decimal('0.01')):
            raise ValueError('金额最多两位小数')
        return value

    @model_validator(mode='after')
    def validate_confirmation(self):
        """必须主动确认且支付方式与平台一致；不接受银行卡号等自由文本。"""
        if self.confirmed_by_user is not True:
            raise ValueError('请先核对下单页并主动确认')
        allowed = {'支付宝': {'银行卡', '支付宝余额', '余额宝'}, '天天基金': {'银行卡', '活期宝'}}
        if self.payment_method not in allowed[self.platform]:
            raise ValueError('支付方式与平台不一致')
        return self

    def as_quote(self) -> dict:
        """仅在当次内存试算中转换证据，不保存、不声称独立平台API已验证。"""
        return {
            'fund_code': self.fund_code, 'platform': self.platform, 'payment_method': self.payment_method,
            'purchase_status': self.purchase_status, 'account_eligible': self.account_eligible,
            'subscription_fee_rate_pct': self.subscription_fee_rate_pct,
            'min_purchase_rmb': self.min_purchase_rmb,
            # 这是用户核对的可付款下界，不是平台完整余额或账户总额度。
            'daily_remaining_rmb': self.verified_capacity_rmb,
            'capacity_basis': 'user_confirmed_lower_bound',
            'observed_at': self.observed_at.isoformat(),
            'source': '请求者当次手动核对下单页（非平台API独立验证）',
            'evidence_scope': 'account_confirmed', 'fee_mode': 'proportional',
        }
