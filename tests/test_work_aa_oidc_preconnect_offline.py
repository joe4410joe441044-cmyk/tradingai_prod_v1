"""Local acceptance for the measured OIDC preconnect contract.  No network."""
import json

from backend.observation_auth.oidc_config import ObservationOidcConfig
from tools.work_aa.observation_oidc_preconnect import (
    BACKEND_CALLBACK_PATH, callback_url, cookie_flags, evaluate_preconnect,
    proxy_method)


MEASURED = {
    'source': 'sites-enabled/tradingai first https server',
    'scheme': 'https',
    'host': 'tradingai-joe.mooo.com',
    'port': 443,
    'proxy_pass_host': '127.0.0.1',
    'proxy_pass_port': 8001,
    'path_rewrite': False,
    'api_methods': ('GET', 'HEAD', 'OPTIONS'),
    'logout_post_explicit': False,
    'forwards_host': True,
    'forwards_forwarded_proto': True,
    'forwards_cookie': True,
    'hides_set_cookie': False,
}


def test_f11d15_01_measured_callback_url_is_exact():
    result = evaluate_preconnect(MEASURED)
    assert result['callback_url'] == (
        'https://tradingai-joe.mooo.com/api/observation/auth/oidc/callback')
    assert result['callback_url'].endswith(BACKEND_CALLBACK_PATH)
    assert not result['callback_url'].endswith('/')


def test_f11d15_02_redirect_uri_rejects_dynamic_or_mismatched_forms():
    assert callback_url('https://tradingai-joe.mooo.com') is not None
    assert callback_url('http://tradingai-joe.mooo.com') is None
    assert callback_url('https://tradingai-joe.mooo.com/') is None
    assert callback_url('https://tradingai-joe.mooo.com:8443') is None
    assert callback_url('https://user@tradingai-joe.mooo.com') is None
    assert callback_url('https://169.58.111.142') != (
        'https://tradingai-joe.mooo.com/api/observation/auth/oidc/callback')


def test_f11d15_03_get_callback_passes_and_post_logout_does_not():
    assert proxy_method(MEASURED, 'GET', BACKEND_CALLBACK_PATH) == 'ALLOW'
    assert proxy_method(MEASURED, 'POST', '/api/observation/auth/oidc/logout') == 'DENY'
    result = evaluate_preconnect(MEASURED)
    assert result['logout_post'] == 'DENY'
    assert result['reason'] == 'POST_LOGOUT_BLOCKED_BY_PROXY'
    assert result['preconnect_ready'] is False


def test_f11d15_04_secure_httponly_lax_cookie_is_required():
    flags = cookie_flags(ObservationOidcConfig({
        'enabled': True, 'secure_cookie': True}))
    assert flags['secure'] is True
    assert flags['httponly'] is True
    assert flags['samesite'] == 'lax'
    assert flags['path'] == '/api/observation'


def test_f11d15_05_samesite_strict_is_not_the_oauth_callback_policy():
    source = open('backend/observation_auth/oidc_api.py', encoding='utf-8').read()
    assert "['samesite'] = 'lax'" in source
    assert 'strict' not in source.lower()


def test_f11d15_06_default_config_stays_off_without_a_secret():
    result = evaluate_preconnect(MEASURED)
    assert result['feature_flag'] == 'FEATURE_DISABLED'
    sample = json.load(open(
        'backend/observation_auth/observation_oidc.sample.json', encoding='utf-8'))
    assert sample['enabled'] is False
    assert 'client_secret' not in sample
    idle = ObservationOidcConfig({'enabled': False, 'client_secret': 'x' * 32})
    assert idle.disabled_reason() == 'FEATURE_DISABLED'
    denied = ObservationOidcConfig({'enabled': True, 'password': 'x' * 32})
    assert denied.disabled_reason() == 'SECRET_CONFIG_REJECTED'


def test_f11d15_07_stage_b_stays_unauthorized():
    result = evaluate_preconnect(MEASURED)
    assert result['stage_b_decision'] == 'DENY'
    assert result['stage_b_authorized'] is False
    assert result['permission'] == 'WORK_AA_READONLY_POSITION_OBSERVATION_APPROVER'


def test_f11d15_08_checker_does_not_call_google_or_read_credentials():
    source = open('tools/work_aa/observation_oidc_preconnect.py', encoding='utf-8').read()
    assert 'urlopen' not in source
    assert 'os.environ' not in source
    assert 'kucoin_trade' not in source
    assert 'kucoin_position_stage_b_adapter' not in source
    assert '/etc/tradingai' not in source
    assert 'client_secret' not in source
    assert evaluate_preconnect(MEASURED)['issuer'] == 'https://accounts.google.com'
