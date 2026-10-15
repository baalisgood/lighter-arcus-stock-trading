"""Validate every stock configuration before constructing any exchange adapter."""
from decimal import Decimal
from pathlib import Path
import yaml

SYMBOLS = tuple(f'{s}-USDC-PERP' for s in ('MU', 'SNDK', 'NVDA', 'AMD', 'INTC'))
EXCHANGES = {'lighter', 'arcus'}
SLIPPAGE = Decimal('0.0001')


def load_mapping(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Missing regular stock configuration: {path.name}')
    try:
        value = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f'Malformed stock configuration: {path.name}') from exc
    if not isinstance(value, dict) or not value:
        raise ValueError(f'Empty or invalid stock configuration: {path.name}')
    return value


def require(condition, name):
    if not condition:
        raise ValueError(f'Invalid or missing stock profile field: {name}')


def number(value, name, *, minimum=0, maximum=None):
    try:
        value = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f'Invalid stock numeric field: {name}') from exc
    require(value.is_finite() and value >= minimum and (maximum is None or value <= maximum), name)
    return value


def validate_stock_profile(root):
    root = Path(root)
    directory = root / 'config/arbitrage'
    require(not any(p.is_symlink() for p in (root / 'config', directory)), 'config directories')
    names = ('stock_monitor', 'stock_segmented', 'stock_execution', 'stock_pairs', 'multi_leg_pairs')
    docs = {name: load_mapping(directory / f'{name}.yaml') for name in names}
    try:
        mon, seg, exe, pairs, multi = (docs[name] for name in names)
        require(mon['symbols'] == list(SYMBOLS) and set(mon['exchanges']) == EXCHANGES and len(mon['exchanges']) == 2, 'monitor universe')
        number(mon['thresholds']['min_spread_pct'], 'monitor spread', minimum=Decimal('.241'))
        for name in ('analysis_interval_ms', 'ui_refresh_interval_ms'):
            number(mon['performance'][name], name, minimum=1)
        for name in ('interval', 'data_timeout'):
            number(mon['health_check'][name], name, minimum=1)
        require(multi == {'pairs': []}, 'empty multi-leg profile')
        require(pairs['enabled'] is True and pairs['mode'] == 'one_to_many' and
                pairs['center_exchange'] == 'lighter' and pairs['counter_exchanges'] == ['arcus'] and
                pairs['symbols'] == list(SYMBOLS) and pairs['allow_reverse'] is True, 'stock pairs')
        mode = seg['system_mode']
        require(mode['stock_profile'] is True and mode['monitor_only'] is False, 'live mode')
        for name in ('bootstrap_positions_on_startup', 'bootstrap_positions_block_open_until_success', 'bootstrap_positions_block_open_on_mismatch'):
            require(mode[name] is True, name)
        number(mode['data_freshness_seconds'], 'freshness', minimum=Decimal('.001'), maximum=Decimal('2.5'))
        require(mode['bootstrap_positions_qty_tolerance'] == 0, 'recovery tolerance')
        number(mode['bootstrap_positions_empty_confirm_attempts'], 'recovery confirmations', minimum=2)
        number(mode['bootstrap_positions_empty_confirm_interval_seconds'], 'recovery interval', minimum=Decimal('.01'))
        require(set(seg['symbol_configs']) == set(SYMBOLS), 'explicit stock symbols')
        defaults = seg['default_config']
        for symbol in SYMBOLS:
            override = seg['symbol_configs'][symbol]
            require(isinstance(override, dict) and not (set(override) - {'grid_config', 'quantity_config', 'risk_config'}), symbol)
            grid, qty, risk = ({**defaults[key], **override.get(key, {})} for key in ('grid_config', 'quantity_config', 'risk_config'))
            for name in ('initial_spread_threshold', 'grid_step', 'profit_per_segment'):
                number(grid[name], name, minimum=Decimal('.000001'))
            require(isinstance(grid['max_segments'], int) and 1 <= grid['max_segments'] <= 4, 'max_segments')
            require(grid['strict_persistence_check'] is True and grid['require_orderbook_liquidity'] is True and
                    grid['orderbook_aggregate_levels'] == 1 and grid['skip_orderbook_liquidity_exchanges'] == [], 'first-level stock liquidity')
            number(grid['spread_persistence_seconds'], 'persistence', minimum=1)
            require(Decimal(str(grid['slippage_tolerance'])) == SLIPPAGE, 'grid slippage')
            for name in ('segment_quantity_ratio', 'segment_partial_order_ratio'):
                require(grid[name] == 1, name)
            require(qty['base_quantity'] == 0 and qty['quantity_mode'] == 'value', 'unanchored stock quantity')
            number(qty['target_value_usdc'], 'order target', minimum=Decimal('.01'), maximum=500)
            require(isinstance(qty['quantity_precision'], int) and 0 <= qty['quantity_precision'] <= 12, 'quantity precision')
            number(qty['min_order_size'], 'minimum quantity')
            number(risk['max_position_value'], 'symbol cap', minimum=Decimal('.01'), maximum=2000)
            number(risk['max_loss_percent'], 'loss threshold', minimum=Decimal('.000001'))
        guard = seg['risk_control']['open_only_close']
        require(guard['max_exchange_position_value']['enabled'] is True, 'exchange cap enabled')
        number(guard['max_exchange_position_value']['max_value_usdc'], 'exchange cap', minimum=Decimal('.01'), maximum=8000)
        require(seg['decision']['deduct_fees'] is True, 'fee deduction')
        execution = exe['arbitrage_execution']
        require(execution['enabled'] is True and set(execution['exchange_order_modes']) == EXCHANGES, 'explicit execution modes')
        require(all(row == {'order_mode': 'market'} for row in execution['exchange_order_modes'].values()), 'market-only execution')
        require(execution['order_execution']['enable_dual_limit_mode'] is False and
                Decimal(str(execution['order_execution']['max_slippage'])) == SLIPPAGE, 'execution slippage')
        for fees in (seg['decision']['exchange_fee_config'], execution['exchange_fees']):
            require(set(fees) == EXCHANGES, 'explicit exchange fees')
            for exchange, expected in (('lighter', Decimal('.00028')), ('arcus', Decimal('.000225'))):
                require(all(Decimal(str(fees[exchange][name])) == expected for name in ('limit_fee_rate', 'market_fee_rate')), 'round-trip fees')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f'Missing or invalid required stock profile field: {exc}') from exc
    from core.services.arbitrage_monitor_v2.config.monitor_config import ConfigManager
    ConfigManager(directory / "stock_monitor.yaml", public_only=True)
    return docs
