"""顾问任务失败关闭测试，只使用虚构分析与禁止写入的Session。"""
from types import SimpleNamespace

import pytest

from backend.scheduler import advisor_job
from backend.scheduler.advisor_job import AdvisorJob


class ForbiddenDB:
    """禁止分析失败后进入数据库。"""

    # 任意数据库调用都让夹具失败。
    def __getattr__(self, name):
        raise AssertionError('分析失败不应调用数据库：' + name)


# 隔离配置和分析，不构造真实模型客户端。
def isolate(monkeypatch, payload=None, failure=False):
    from backend import config
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(ANALYZER_PRIMARY_MODEL='synthetic'))

    class FakeService:
        """只返回指定夹具或抛出虚构异常。"""

        # 接收Session但不使用。
        def __init__(self, db):
            pass

        # 不调用任何模型。
        def analyze(self, model=None):
            if failure:
                raise RuntimeError('PRIVATE_ANALYSIS_SENTINEL')
            return payload

    monkeypatch.setattr(advisor_job, 'AdvisorService', FakeService)


# 分析异常必须诚实返回失败且不暴露错误正文。
def test_analysis_exception_is_a_structured_failure(monkeypatch, caplog):
    isolate(monkeypatch, failure=True)
    result = AdvisorJob(ForbiddenDB()).run()
    assert result['success'] is False and result['technical_failure'] is True
    assert result['analysis'] is None and result['summary']['report_id'] is None
    assert result['summary']['failure_stage'] == 'analysis'
    assert result['summary']['analysis_ok'] is False and result['email_sent'] is False
    assert 'PRIVATE_ANALYSIS_SENTINEL' not in str(result) + caplog.text


# 未存成新报告时，不能沿用旧编号或继续宣称成功。
def test_persistence_failure_clears_previous_report_id(monkeypatch):
    isolate(monkeypatch, {'portfolio_diagnosis': {'overall_assessment': '合成完成'}, 'actions': []})
    monkeypatch.setattr(AdvisorJob, '_persist_report', lambda self, result: None)
    job = AdvisorJob(ForbiddenDB())
    job.report_id = 123
    result = job.run()
    assert result['success'] is False and result['technical_failure'] is True
    assert result['summary']['failure_stage'] == 'report_persistence'
    assert result['summary']['report_id'] is None and job.report_id is None
    assert result['analysis'] is None and result['email_sent'] is False


# 无法识别的返回形态不能进入数据库或生成假报告。
@pytest.mark.parametrize('payload', [None, [], {'portfolio_diagnosis': None}, {'error': 'no_holdings'}])
def test_invalid_analysis_fails_closed(monkeypatch, payload):
    isolate(monkeypatch, payload)
    result = AdvisorJob(ForbiddenDB()).run()
    assert result['success'] is False and result['technical_failure'] is True
    assert result['analysis'] is None and result['summary']['report_id'] is None
    assert result['email_sent'] is False


# 实际API函数也应返回失败合同而不是未处理的500异常。
def test_scheduler_api_preserves_structured_failure(monkeypatch):
    from backend.api.scheduler import run_advisor_job
    isolate(monkeypatch, failure=True)
    result = run_advisor_job(db=ForbiddenDB(), push_email=False, force=False, model='synthetic', read_only=False)
    assert result['success'] is False and result['technical_failure'] is True
    assert result['summary']['failure_stage'] == 'analysis' and result['analysis'] is None


class PersistenceDB:
    """模拟报告提交与后续清理异常，不连接数据库。"""

    # 初始化提交失败开关及回滚计数。
    def __init__(self, fail_commit=False):
        self.fail_commit = fail_commit
        self.rollbacks = 0

    # 暂存虚构ORM对象，不执行SQL。
    def add(self, obj):
        pass

    # 可选择模拟持久化失败。
    def commit(self):
        if self.fail_commit:
            raise RuntimeError('PRIVATE_PERSISTENCE_SENTINEL')

    # 模拟数据库分配的新报告编号。
    def refresh(self, obj):
        obj.id = 456

    # 模拟报告保存之后的非关键清理失败。
    def query(self, *args):
        raise RuntimeError('PRIVATE_CLEANUP_SENTINEL')

    # 记录回滚而不触及数据库。
    def rollback(self):
        self.rollbacks += 1


# 主记录已提交时，非关键清理失败不得抹去有效编号。
def test_cleanup_failure_preserves_committed_report_id(monkeypatch, caplog):
    import backend.services.backtest_service as backtest
    isolate(monkeypatch)
    monkeypatch.setattr(backtest, 'BacktestService', lambda db: SimpleNamespace(record_advice=lambda **kwargs: 0))
    db = PersistenceDB()
    job = AdvisorJob(db)
    job._persist_report({'model': 'synthetic', 'actions': []})
    assert job.report_id == 456 and db.rollbacks == 1
    assert 'PRIVATE_CLEANUP_SENTINEL' not in caplog.text


# 核心提交失败时不得伪造报告编号，并且错误正文不能进日志。
def test_report_commit_failure_leaves_no_id(monkeypatch, caplog):
    isolate(monkeypatch)
    db = PersistenceDB(fail_commit=True)
    job = AdvisorJob(db)
    job._persist_report({'model': 'synthetic', 'actions': []})
    assert job.report_id is None and db.rollbacks == 1
    assert 'PRIVATE_PERSISTENCE_SENTINEL' not in caplog.text
