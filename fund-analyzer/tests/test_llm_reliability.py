"""纯合成模型可靠性测试，不访问外部服务。"""
import json
import logging

import httpx
import pytest

from engine import llm_client
from engine.llm_client import LLMClient, LLMConfig, parse_json_response


# 通过内存HTTP传输构建客户端，替代真实网络和等待。
def make_client(monkeypatch, responses, retries=0, fallbacks=None):
    seen, sleeps = [], []
    scripted = iter(responses)

    # 每次只返回一个预设的虚构响应。
    def handle(request):
        seen.append(json.loads(request.content))
        status, body = next(scripted)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(llm_client.time, 'sleep', sleeps.append)
    config = LLMConfig(api_base='http://127.0.0.1:1/v1', api_key='synthetic-key',
                       primary_model='synthetic-main', fallback_models=fallbacks or ['synthetic-main'],
                       max_retries_per_model=retries)
    return LLMClient(config, http_client=httpx.Client(transport=httpx.MockTransport(handle))), seen, sleeps


# 构造正式回答格式的虚构响应。
def completion(content, **extra):
    return {'choices': [{'message': {'content': content, **extra}}]}


# JSON模式不得突破配置的零次重试。
def test_json_mode_has_no_hidden_retries(monkeypatch):
    client, seen, sleeps = make_client(monkeypatch, [(200, completion('invalid'))] * 4)
    with pytest.raises(RuntimeError):
        client.call('合成输入', json_mode=True)
    assert len(seen) == 1 and sleeps == []
    assert client.failure_count == 1


# 瞬时错误只按配置重试一次，恢复时不误报最终失败。
def test_configured_retry_can_recover(monkeypatch):
    client, seen, sleeps = make_client(monkeypatch, [(503, {}), (200, completion('{"ok":true}'))], retries=1)
    assert json.loads(client.call('合成输入', json_mode=True)) == {'ok': True}
    assert len(seen) == 2 and sleeps == [2] and client.failure_count == 0


# 无效凭据不能靠重复请求或切换模型来解决。
@pytest.mark.parametrize('status', [401, 403])
def test_auth_failure_stops_without_retry(monkeypatch, status):
    client, seen, sleeps = make_client(monkeypatch, [(status, {})] * 8, retries=1, fallbacks=['synthetic-backup'])
    with pytest.raises(RuntimeError):
        client.call('合成输入', json_mode=True)
    assert len(seen) == 1 and sleeps == []


# 上游正文不应进入日志或最终异常。
@pytest.mark.parametrize('response', [(200, completion('PRIVATE_SENTINEL')), (500, {'error': 'PRIVATE_SENTINEL'})])
def test_error_does_not_echo_response(monkeypatch, caplog, response):
    client, _, _ = make_client(monkeypatch, [response] * 4)
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError) as error:
        client.call('合成输入', json_mode=True)
    assert 'PRIVATE_SENTINEL' not in caplog.text + str(error.value)


# 包装文字中的JSON必须遵守字符串边界而不是直接数括号。
@pytest.mark.parametrize('claim', ['文字 } 仍在字符串内', '文字 { 仍在字符串内', '引号 " 后的 }'])
def test_json_extraction_respects_quoted_braces(claim):
    value = {'claim': claim, 'confidence': 0.7}
    assert parse_json_response('结果：' + json.dumps(value, ensure_ascii=False) + '结束') == value


# 无效代码块不应遮住后面合法的JSON对象。
def test_non_object_fence_does_not_hide_valid_object():
    assert parse_json_response('```json\n[1,2]\n```\n{"ok":true}') == {'ok': True}


# 思考内容不能升级为结构化正式回答。
def test_reasoning_only_is_rejected_in_json_mode(monkeypatch):
    client, seen, _ = make_client(monkeypatch, [(200, completion(None, reasoning_content='{"ok":true}'))] * 4)
    with pytest.raises(RuntimeError):
        client.call('合成输入', json_mode=True)
    assert len(seen) == 1


# 非结构化兼容调用保留原有行为。
def test_non_json_reasoning_compatibility(monkeypatch):
    client, _, _ = make_client(monkeypatch, [(200, completion(None, reasoning_content='合成解释'))])
    assert client.call('合成输入') == '合成解释'


# 重复备用模型不得放大尝试次数。
def test_duplicate_models_are_not_repeated(monkeypatch):
    client, seen, _ = make_client(monkeypatch, [(503, {})] * 8, fallbacks=['synthetic-backup'] * 2)
    with pytest.raises(RuntimeError):
        client.call('合成输入')
    assert [item['model'] for item in seen] == ['synthetic-main', 'synthetic-backup']


# 无效重试预算在构造阶段拒绝，不能产生不受控请求。
@pytest.mark.parametrize('retries', [-1, True, 1.5])
def test_invalid_retry_budget_is_rejected(retries):
    with pytest.raises(ValueError, match='非负整数'):
        LLMConfig(api_base='http://127.0.0.1:1/v1', api_key='synthetic-key', max_retries_per_model=retries)


# 单个模型不支持请求时仍可尝试明确配置的另一模型，但不重复相同错误。
def test_model_specific_bad_request_can_use_configured_fallback(monkeypatch):
    client, seen, sleeps = make_client(monkeypatch, [(400, {}), (200, completion('{"ok":true}'))],
                                       retries=1, fallbacks=['synthetic-backup'])
    assert json.loads(client.call('合成输入', json_mode=True)) == {'ok': True}
    assert [item['model'] for item in seen] == ['synthetic-main', 'synthetic-backup']
    assert sleeps == [] and client.fallback_count == 1
