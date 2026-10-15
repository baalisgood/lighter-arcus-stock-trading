"""Offline public stock monitoring contracts; no credentials or network."""
import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from core.adapters.exchanges.adapters.lighter import LighterAdapter


def run(coro): return asyncio.run(coro)


STOCK_PROFILE = Path("config/arbitrage/stock_monitor.yaml")
STOCKS = ["MU", "SNDK", "NVDA", "AMD", "INTC"]

def test_public_profile_is_strict_and_never_loads_trading_config(monkeypatch, tmp_path):
    from core.services.arbitrage_monitor_v2.config.monitor_config import ConfigManager
    from core.services.arbitrage_monitor_v2.config.multi_leg_pairs_config import MultiLegPairsConfigManager
    monkeypatch.setattr(MultiLegPairsConfigManager, '__init__', Mock(side_effect=AssertionError('strategy read')))
    manager = ConfigManager(STOCK_PROFILE, public_only=True)
    assert manager.validate() and manager.config.symbols == [s + '-USDC-PERP' for s in STOCKS]
    with pytest.raises(ValueError): ConfigManager(tmp_path / 'missing.yaml', public_only=True)
    for bad in [None, [], {}, {'symbols': ['SPCX-USDC-PERP'], 'exchanges': ['lighter', 'arcus']},
                {'symbols': ['MU-USDC-PERP'], 'exchanges': ['lighter']},
                {'symbols': ['MU-USDC-PERP', 'MU-USDC-PERP'], 'exchanges': ['lighter', 'arcus']}]:
        path = tmp_path / 'bad.yaml'; path.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValueError): ConfigManager(path, public_only=True)
    baseline = yaml.safe_load(STOCK_PROFILE.read_text())
    for change in [dict(api_key='injected'), dict(thresholds={'auth': 'injected'}), dict(thresholds={'min_spread_pct': float('nan')}),
                   dict(performance={'analysis_interval_ms': -1}), dict(thresholds={'min_spread_pct': {'api_key': 'injected'}}),
                   dict(multi_exchange_config_path='forbidden.yaml'),
                   dict(spread_history={'enabled': True, 'data_dir': '/tmp/escape'})]:
        path = tmp_path / 'bad.yaml'; path.write_text(yaml.safe_dump({**baseline, **change}))
        with pytest.raises(ValueError): ConfigManager(path, public_only=True)


def test_public_lighter_never_reads_credentials_or_creates_signer(monkeypatch):
    import os
    from core.adapters.exchanges.interface import ExchangeConfig
    from core.adapters.exchanges.models import ExchangeType
    from core.adapters.exchanges.adapters.lighter_base import LighterBase
    original = os.getenv
    def getenv(name, *args):
        assert name not in {'LIGHTER_API_KEY_PRIVATE_KEY', 'LIGHTER_ACCOUNT_INDEX', 'LIGHTER_API_KEY_INDEX'}
        return original(name, *args)
    monkeypatch.setattr(os, 'getenv', getenv)
    monkeypatch.setattr(LighterAdapter, '_load_lighter_config', Mock(side_effect=AssertionError('credential YAML')))
    monkeypatch.setattr(LighterBase, '_create_signer_client', Mock(side_effect=AssertionError('signer')))
    a = LighterAdapter(ExchangeConfig('lighter', 'Lighter', ExchangeType.PERPETUAL, '', '', extra_params={'public_only': True}))
    async def scenario():
        for component in (a._base, a._rest, a._websocket, a._rest._websocket):
            assert component.public_only and not component.auth_enabled
            assert component.ws_url == 'wss://mainnet.zklighter.elliot.ai/stream?readonly=true'
            assert component.account_index is None and component.api_key_index is None
            assert component.signer_client is None and component.api_key_private_key == ''
        await a._websocket.connect()
        assert await a._websocket._create_auth_token() is None
        await a._restart_connections()
        assert a._rest.public_only and a._websocket.public_only and a._config_dict['public_only']
        for component in (a._rest, a._websocket, a._rest._websocket):
            assert component.ws_url == 'wss://mainnet.zklighter.elliot.ai/stream?readonly=true'
        await a.disconnect()
    run(scenario())
    with pytest.raises(ValueError):
        LighterAdapter(ExchangeConfig('lighter', 'Lighter', ExchangeType.PERPETUAL, 'injected', '', extra_params={'public_only': True}))


def test_public_rest_initialization_and_reconnect_use_only_public_client(monkeypatch):
    import core.adapters.exchanges.adapters.lighter_rest as module
    calls = []
    def fail(*args, **kwargs): raise AssertionError('private client constructed')
    for name in ('AccountApi', 'TransactionApi', 'CandlestickApi', 'FundingApi'):
        monkeypatch.setattr(module, name, fail)
    monkeypatch.setattr(module.LighterRest, '_create_signer_client', fail)
    monkeypatch.setattr(module, 'ApiClient', lambda configuration: NS(close=AsyncMock(), configuration=configuration))
    monkeypatch.setattr(module, 'OrderApi', lambda client: NS(order_books=AsyncMock(return_value=NS(order_books=[NS(symbol='MU', market_id=164)]))))
    r = module.LighterRest({'public_only': True})
    async def scenario():
        for _ in range(2):
            await r.initialize()
            assert r._connected and r.markets['MU']['market_id'] == 164
            assert r.account_api is None and r.transaction_api is None and r.signer_client is None
            assert r.api_client.configuration.verify_ssl is True
            calls.append(r.api_client)
            await r.close()
        r._load_markets = AsyncMock(side_effect=ConnectionError('offline'))
        with pytest.raises(ConnectionError): await r.initialize()
        assert not r._connected and r.api_client is None
    run(scenario())
    assert len(calls) == 2 and calls[0] is not calls[1]


def test_public_orchestrator_uses_empty_auth_and_requires_active_symbols(monkeypatch):
    from core.services.arbitrage_monitor_v2.core.orchestrator import ArbitrageOrchestrator
    from core.adapters.exchanges.adapters.arcus import ArcusAdapter
    from core.utils.config_loader import ExchangeConfigLoader
    monkeypatch.setattr(ExchangeConfigLoader, '__init__', Mock(side_effect=AssertionError('auth loader')))
    monkeypatch.setattr(LighterAdapter, '_load_lighter_config', Mock(side_effect=AssertionError('credential YAML')))
    missing = []
    async def connect_lighter(a):
        assert not any((a.config.api_key, a.config.api_secret, a.config.private_key, a.config.wallet_address))
        a._supported_symbols = STOCKS.copy()
        a._market_info = {s: {'status': 'inactive' if s in missing else 'active'} for s in STOCKS}
        return True
    async def connect_arcus(a):
        assert not a.api_key and not a._seed and not a.address
        a._set_markets([{'marketDisplayName': s + '-USD', 'marketId': i, 'status': 'ONLINE'} for i, s in enumerate(STOCKS)])
        return True
    monkeypatch.setattr(LighterAdapter, 'connect', connect_lighter)
    monkeypatch.setattr(ArcusAdapter, 'connect', connect_arcus)
    async def scenario():
        o = ArbitrageOrchestrator(STOCK_PROFILE, public_only=True)
        await o._init_adapters()
        assert set(o.data_receiver.adapters) == {'lighter', 'arcus'}
        assert not hasattr(o, 'executor')
        await o.data_receiver.cleanup()
        missing.append('MU')
        with pytest.raises(Exception, match='缺少启用的股票市场'):
            await ArbitrageOrchestrator(STOCK_PROFILE, public_only=True)._init_adapters()
    run(scenario())


def test_public_entry_import_does_not_load_dotenv(monkeypatch):
    import importlib.util
    import dotenv
    monkeypatch.setattr(dotenv, 'load_dotenv', Mock(side_effect=AssertionError('dotenv read')))
    spec = importlib.util.spec_from_file_location('stock_entry_offline', 'run_arbitrage_monitor_v2.py')
    entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)
    monkeypatch.setattr('sys.argv', ['monitor', '--public-only', '--config', '/missing/public-profile'])
    with pytest.raises(ValueError): run(entry.main())


def test_stock_launcher_rejects_live_and_duplicate_lock():
    import fcntl
    import os
    import subprocess
    import sys
    root = STOCK_PROFILE.resolve().parents[2]
    command = [str(root / 'start_stock_monitor.sh')]
    result = subprocess.run(command + ['live'], cwd=root, capture_output=True, text=True)
    assert result.returncode == 2 and 'live is unavailable' in result.stderr
    (root / 'run').mkdir(exist_ok=True)
    with (root / 'run/stock.lock').open('a') as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(command, cwd=root, env={**os.environ, 'STOCK_MONITOR_PYTHON': sys.executable}, capture_output=True, text=True, timeout=5)
        assert result.returncode != 0 and 'already running' in result.stderr


@pytest.mark.parametrize('stock', STOCKS)
def test_stock_bbo_both_directions_empty_one_sided_stale_and_recovery(stock):
    from core.services.arbitrage_monitor_v2.core.orchestrator import ArbitrageOrchestrator
    from core.adapters.exchanges.models import OrderBookData, OrderBookLevel
    o = ArbitrageOrchestrator(STOCK_PROFILE, public_only=True)
    o.data_processor.scroller = None; o.opportunity_finder.scroller = None
    symbol = stock + '-USDC-PERP'
    callbacks = {}
    async def lighter_subscribe(symbols, callback): callbacks['lighter'] = callback
    async def arcus_subscribe(symbol, callback): callbacks[('arcus', symbol)] = callback
    o.data_receiver.register_adapter('lighter', NS(batch_subscribe_orderbooks=lighter_subscribe,
                                                  batch_subscribe_tickers=AsyncMock()))
    o.data_receiver.register_adapter('arcus', NS(subscribe_orderbook=arcus_subscribe, subscribe_ticker=AsyncMock()))
    run(o.data_receiver.subscribe_all(o.config.symbols))
    def publish(venue, bid, ask, *, age=0, invalid=None):
        stamp = datetime.now() - timedelta(seconds=age)
        bids = [OrderBookLevel(D(bid), D('1'))]; asks = [OrderBookLevel(D(ask), D('1'))]
        if invalid == 'empty': bids = []; asks = []
        elif invalid == 'bid_only': asks = []
        elif invalid == 'ask_only': bids = []
        elif invalid == 'zero_price': bids[0].price = D(0)
        elif invalid == 'negative_price': asks[0].price = D(-1)
        elif invalid == 'zero_size': bids[0].size = D(0)
        elif invalid == 'negative_size': asks[0].size = D(-1)
        elif invalid == 'nan_price': bids[0].price = D('NaN')
        elif invalid == 'infinite_size': asks[0].size = D('Infinity')
        elif invalid == 'string_price': bids[0].price = '99'
        elif invalid == 'missing_size': asks[0].size = None
        elif invalid == 'crossed': bids[0].price = asks[0].price
        native = stock if venue == 'lighter' else stock + '-USD'
        ob = OrderBookData(symbol=native, bids=bids, asks=asks, timestamp=stamp)
        if venue == 'lighter': callbacks['lighter'](ob)
        else: callbacks[('arcus', native)](native, ob)
        assert o.orderbook_queue.qsize() == 1
        o.data_processor._process_orderbook(o.orderbook_queue.get_nowait())
    def analyze():
        books = {venue: o.data_processor.get_orderbook(venue, symbol) for venue in ('lighter', 'arcus')}
        spreads = o.spread_calculator.calculate_spreads(symbol, {k: v for k, v in books.items() if v is not None})
        return spreads, o.opportunity_finder.find_opportunities(spreads)
    publish('lighter', '99', '100'); publish('arcus', '101', '102')
    observed, opportunities = analyze()
    assert {(s.exchange_buy, s.exchange_sell) for s in observed} == {('lighter', 'arcus'), ('arcus', 'lighter')}
    assert observed[0].spread_pct == 1.0 and len(opportunities) == 1
    for venue in ('lighter', 'arcus'):
        bid, ask = ('99', '100') if venue == 'lighter' else ('101', '102')
        for invalid in ('empty', 'bid_only', 'ask_only', 'zero_price', 'negative_price',
                        'zero_size', 'negative_size', 'nan_price', 'infinite_size',
                        'string_price', 'missing_size', 'crossed'):
            publish(venue, bid, ask, invalid=invalid)
            assert analyze() == ([], [])
            assert not o.opportunity_finder.get_all_opportunities()
            publish(venue, bid, ask)
            spreads, opportunities = analyze()
            assert len(spreads) == 2 and len(opportunities) == 1
        publish(venue, bid, ask, age=5); assert analyze() == ([], [])
        publish(venue, bid, ask); assert len(analyze()[0]) == 2
    assert not hasattr(o, 'executor')


def test_public_websocket_forces_tls_and_sends_no_auth(monkeypatch):
    import ssl
    import core.adapters.exchanges.adapters.lighter_websocket as module
    monkeypatch.setenv('LIGHTER_VERIFY_SSL', 'false')
    monkeypatch.setattr(module.asyncio, 'sleep', AsyncMock())
    ws = module.LighterWebSocket({'public_only': True})
    from websockets.asyncio import client as sdk
    actual_connect = sdk.connect
    sdk_connections = []
    monkeypatch.setattr(sdk, 'get_proxy', Mock(side_effect=AssertionError('system proxy discovery')))
    sent = []; connection_options = []
    class Connection:
        async def __aenter__(self): return NS(send=AsyncMock(side_effect=lambda text: sent.append(json.loads(text))))
        async def __aexit__(self, *args): return False
    def connect(url, **kwargs):
        connection_options.append(kwargs)
        sdk_connections.append(actual_connect(url, **kwargs))
        return Connection()
    async def listen(_socket): ws._running = len(sdk_connections) < 2
    monkeypatch.setattr(module, 'connect', connect)
    ws._subscribed_market_stats = {164}; ws._subscribed_markets = {164}
    ws._listen_websocket = listen
    ws._send_account_subscriptions = AsyncMock(side_effect=AssertionError('private subscription'))
    async def scenario():
        await ws.connect()
        await ws._run_direct_ws_subscription()
        await ws.disconnect()
        monkeypatch.setattr(asyncio.get_running_loop(), 'create_connection', AsyncMock(side_effect=ConnectionError('offline TCP sentinel')))
        for connection in sdk_connections:
            assert connection.proxy is None
            with pytest.raises(ConnectionError, match='offline TCP sentinel'):
                await connection.create_connection()
    run(scenario())
    assert len(connection_options) == 2 and all(options['proxy'] is None for options in connection_options)
    assert connection_options[0]['ssl'].verify_mode == ssl.CERT_REQUIRED
    assert connection_options[0]['ssl'].check_hostname is True
    assert not any('auth' in message for message in sent)
    assert {m['channel'] for m in sent} == {'market_stats/164', 'order_book/164'}
    assert not any(k in connection_options[0] for k in ('extra_headers', 'additional_headers'))
    ws._send_account_subscriptions.assert_not_awaited()


def test_stock_launcher_drops_inherited_credentials_and_pythonpath(tmp_path):
    import os
    import subprocess
    runtime = tmp_path / 'runtime'
    runtime.write_text('#!/bin/sh\n/usr/bin/env\n')
    runtime.chmod(0o700)
    root = STOCK_PROFILE.resolve().parents[2]
    result = subprocess.run([str(root / 'start_stock_monitor.sh')], cwd=root,
                            env={**os.environ, 'STOCK_MONITOR_PYTHON': str(runtime),
                                 'LIGHTER_API_KEY_PRIVATE_KEY': 'offline-sentinel',
                                 'ARCUS_API_KEY': 'offline-sentinel', 'PYTHONPATH': '/tmp/injected'},
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    names = {line.partition('=')[0] for line in result.stdout.splitlines()}
    assert not names & {'LIGHTER_API_KEY_PRIVATE_KEY', 'ARCUS_API_KEY', 'PYTHONPATH', 'STOCK_MONITOR_PYTHON'}
    assert names <= {'PATH', 'HOME', 'TERM', 'LANG', 'PYTHONDONTWRITEBYTECODE', 'PWD', 'SHLVL', '_', 'STOCK_LAUNCHER_ROOT'}


def test_receiver_default_mode_preserves_empty_snapshot_filter():
    from core.services.arbitrage_monitor_v2.data.data_receiver import DataReceiver
    from core.services.arbitrage_monitor_v2.config.debug_config import DebugConfig
    from core.adapters.exchanges.models import OrderBookData
    receiver = DataReceiver(asyncio.Queue(), asyncio.Queue(), DebugConfig())
    callbacks = {}
    async def batch_subscribe(symbols, callback): callbacks['lighter'] = callback
    async def subscribe(symbol, callback): callbacks['arcus'] = callback
    receiver.register_adapter('lighter', NS(batch_subscribe_orderbooks=batch_subscribe, batch_subscribe_tickers=AsyncMock()))
    receiver.register_adapter('arcus', NS(subscribe_orderbook=subscribe, subscribe_ticker=AsyncMock()))
    run(receiver.subscribe_all(['MU-USDC-PERP']))
    callbacks['lighter'](OrderBookData('MU', [], [], datetime.now()))
    callbacks['arcus']('MU-USD', OrderBookData('MU-USD', [], [], datetime.now()))
    assert receiver.orderbook_queue.empty() and receiver.public_only is False


@pytest.mark.parametrize('public_only', [True, False])
def test_arcus_public_ws_initial_and_reconnect_disable_system_proxy_only_in_public_mode(monkeypatch, public_only):
    from websockets.asyncio import client as sdk
    from core.adapters.exchanges.adapters.arcus import ArcusAdapter
    from core.adapters.exchanges.interface import ExchangeConfig
    from core.adapters.exchanges.models import ExchangeType
    import core.adapters.exchanges.adapters.arcus_websocket as module
    actual_connect = sdk.connect
    sdk_connections = []; options_seen = []
    monkeypatch.setattr(sdk, 'get_proxy', Mock(side_effect=AssertionError('system proxy discovery')))
    monkeypatch.setattr(module.asyncio, 'sleep', AsyncMock())
    a = ArcusAdapter(ExchangeConfig('arcus', 'Arcus', ExchangeType.PERPETUAL, '', '',
                                   extra_params={'public_only': True} if public_only else {}))
    ws = a._websocket
    class Socket:
        def __init__(self, number): self.number = number
        async def send(self, message): pass
        async def close(self): pass
        async def __aiter__(self):
            if self.number == 2: ws._stopping = True
            return
            yield  # async iterator terminates without network or market data.
    async def connect(url, **kwargs):
        options_seen.append(kwargs)
        sdk_connections.append(actual_connect(url, **kwargs))
        return Socket(len(options_seen))
    monkeypatch.setattr(module, 'connect', connect)
    async def scenario():
        await ws.connect()
        await ws._task
        await ws.disconnect()
        assert len(sdk_connections) == 2
        if public_only:
            monkeypatch.setattr(asyncio.get_running_loop(), 'create_connection', AsyncMock(side_effect=ConnectionError('offline TCP sentinel')))
            for connection in sdk_connections:
                assert connection.proxy is None
                with pytest.raises(ConnectionError, match='offline TCP sentinel'):
                    await connection.create_connection()
        else:
            assert all('proxy' not in options for options in options_seen)
            assert all(connection.proxy is True for connection in sdk_connections)
    run(scenario())


@pytest.mark.parametrize('testnet', [False, True])
def test_public_lighter_readonly_url_is_official_and_normal_mode_keeps_url(monkeypatch, testnet):
    import os
    from core.adapters.exchanges.adapters.lighter_base import LighterBase
    monkeypatch.setattr(os, 'getenv', lambda *args: None)
    official = LighterBase.TESTNET_WS_URL if testnet else LighterBase.MAINNET_WS_URL
    public = LighterBase({'public_only': True, 'testnet': testnet, 'ws_url': 'wss://invalid.example/stream'})
    normal = LighterBase({'testnet': testnet})
    with pytest.raises(ValueError, match='endpoints'):
        LighterBase({'testnet': testnet, 'ws_url': official + '?existing=1'})
    assert public.ws_url == official + '?readonly=true'
    assert normal.ws_url == official

