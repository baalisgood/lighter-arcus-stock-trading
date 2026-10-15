"""Offline native configuration checks; no credentials, network or order submission."""
from decimal import Decimal
from pathlib import Path
import yaml
from core.services.arbitrage_monitor_v2.config.symbol_config import SegmentedConfigManager
from core.services.arbitrage_monitor_v2.config.monitor_config import ConfigManager
from core.services.arbitrage_monitor_v2.config.multi_exchange_config import MultiExchangeArbitrageConfigManager

SYMBOLS = {s + '-USDC-PERP' for s in ('MU', 'SNDK', 'AMD', 'NVDA', 'INTC')}

def test_native_loader_uses_only_five_stocks():
    segmented = SegmentedConfigManager(Path('config/arbitrage/arbitrage_segmented.yaml'))
    monitor = ConfigManager(Path('config/arbitrage/monitor_lighter_arcus.yaml'))
    assert set(monitor.config.symbols) == SYMBOLS
    for symbol in SYMBOLS:
        config = segmented.get_config(symbol)
        assert config.quantity_config.quantity_mode == 'fixed'
        assert config.quantity_config.base_quantity == Decimal(str(config.grid_config.split_order_size)) * 2
        assert config.grid_config.max_segments == 2
        assert config.grid_config.initial_spread_threshold == .15
        assert config.grid_config.grid_step == .09
        assert config.grid_config.slippage_tolerance == .0001
        assert config.risk_config.max_position_value == 1000

def test_budget_is_configurable_without_stock_runtime(tmp_path):
    data = yaml.safe_load(Path('config/arbitrage/arbitrage_segmented.yaml').read_text())
    assert data['risk_control']['open_only_close']['max_exchange_position_value']['max_value_usdc'] == 5000
    data['risk_control']['open_only_close']['max_exchange_position_value']['max_value_usdc'] = 6000
    data['symbol_configs']['MU-USDC-PERP']['risk_config']['max_position_value'] = 1200
    target = tmp_path / 'profile.yaml'
    target.write_text(yaml.safe_dump(data))
    loaded = SegmentedConfigManager(target)
    assert loaded.get_config('MU-USDC-PERP').risk_config.max_position_value == 1200
    assert not Path('stock_runtime.py').exists()
    assert not Path('stock_profile.py').exists()

def test_empty_template_supports_original_auth_loader_and_adapter(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core.utils.config_loader import ExchangeConfigLoader
    from core.services.arbitrage_monitor_v2.core.orchestrator_bootstrap import OrchestratorBootstrap
    from core.adapters.exchanges.adapters.lighter import LighterAdapter
    example = yaml.safe_load(Path('examples/lighter_config.yaml.example').read_text())
    auth = example['api_config']['auth']
    assert all(auth[k] == '' for k in ('api_key_private_key', 'account_index', 'api_key_index'))
    auth.update(api_key_private_key='synthetic-test-only', account_index=7, api_key_index=2)
    path = tmp_path / 'config/exchanges/lighter_config.yaml'
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(example))
    monkeypatch.chdir(tmp_path)
    for key in list(__import__('os').environ):
        if key.startswith('LIGHTER_'): monkeypatch.delenv(key)
    loader = ExchangeConfigLoader()
    bootstrap = object.__new__(OrchestratorBootstrap)
    config = bootstrap._load_exchange_config('lighter', path, loader)
    stub = SimpleNamespace(logger=None, _load_lighter_config=lambda: example)
    converted = LighterAdapter._convert_config_to_dict(stub, config)
    assert converted['api_key_private_key'] == 'synthetic-test-only'
    assert converted['account_index'] == 7
    assert converted['api_key_index'] == 2
    assert converted['auth_enabled'] is True
    assert converted['strict_order_state'] is True

def test_launcher_lock_and_sigterm_share_engine_pid(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    import time
    shutil.copy('start.sh', tmp_path / 'start.sh')
    shutil.copytree('config/arbitrage', tmp_path / 'config/arbitrage')
    (tmp_path / 'config/exchanges').mkdir()
    for name in ('lighter', 'arcus'):
        (tmp_path / 'config/exchanges' / (name + '_config.yaml')).write_text('{}')
    (tmp_path / 'main_unified.py').write_text(
        'import os,time\nfrom pathlib import Path\n'
        'assert "LIGHTER_API_KEY_PRIVATE_KEY" not in os.environ\n'
        'Path("pid.txt").write_text(str(os.getpid()))\ntime.sleep(20)\n')
    env = {'PATH': '/usr/bin:/bin', 'STOCK_PYTHON': sys.executable,
           'LIGHTER_API_KEY_PRIVATE_KEY': 'synthetic-not-inherited'}
    def launch():
        return subprocess.Popen(['bash', 'start.sh', 'monitor'], cwd=tmp_path,
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    first = launch()
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / 'pid.txt').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert int((tmp_path / 'pid.txt').read_text()) == first.pid
        second = launch()
        _, err = second.communicate(timeout=5)
        assert second.returncode != 0 and b'already running' in err
        first.terminate()
        first.wait(timeout=5)
        with __import__('pytest').raises(ProcessLookupError): os.kill(first.pid, 0)
        (tmp_path / 'pid.txt').unlink()
        third = launch()
        try:
            deadline = time.monotonic() + 5
            while not (tmp_path / 'pid.txt').exists() and time.monotonic() < deadline:
                time.sleep(.02)
            assert int((tmp_path / 'pid.txt').read_text()) == third.pid
        finally:
            third.terminate(); third.wait(timeout=5)
    finally:
        if first.poll() is None: first.kill(); first.wait(timeout=5)
    lock = tmp_path / 'run/stock.lock'
    lock.unlink()
    sentinel = tmp_path / 'sentinel.txt'
    sentinel.write_text('unchanged')
    lock.symlink_to(sentinel)
    blocked = launch()
    _, error = blocked.communicate(timeout=5)
    assert blocked.returncode != 0 and b'symlink' in error
    assert sentinel.read_text() == 'unchanged'
