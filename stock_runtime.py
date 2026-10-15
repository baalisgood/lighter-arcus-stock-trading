"""Dedicated stock profile. Account configuration never comes from shared YAML/dotenv."""
import asyncio
import os
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from math import lcm
from pathlib import Path

from stock_profile import SYMBOLS, SLIPPAGE, validate_stock_profile
ROOT = Path(__file__).resolve().parent
D = Decimal


def positive(value):
    value = D(str(value))
    if not value.is_finite() or value <= 0:
        raise ValueError('Expected positive finite market/account value')
    return value


def load_stock_environment():
    from dotenv import dotenv_values
    path = ROOT / '.env.stock'
    if path.is_symlink() or not path.is_file():
        raise ValueError('Create a local regular .env.stock file from .env.stock.example')
    values = dotenv_values(path, interpolate=False)
    allowed = {'STOCK_LIGHTER_PRIVATE_KEY', 'STOCK_LIGHTER_ACCOUNT_INDEX', 'STOCK_LIGHTER_API_KEY_INDEX',
               'STOCK_ARCUS_WALLET_ADDRESS', 'STOCK_ARCUS_API_KEY', 'STOCK_ARCUS_SIGNING_KEY', 'STOCK_ARCUS_ACCOUNT_INDEX'}
    if set(values) - allowed:
        raise ValueError('Unsupported key in .env.stock')
    if any(not values.get(key) for key in allowed):
        raise ValueError('Both exchanges require explicit dedicated stock credentials and account indices')
    # Adapters have legacy environment fallbacks; never inherit them.
    for key in list(os.environ):
        if key.startswith(('LIGHTER_', 'ARCUS_', 'STOCK_')):
            del os.environ[key]
    os.environ.update(values)


def create_stock_adapters():
    from core.adapters.exchanges.interface import ExchangeConfig
    from core.adapters.exchanges.models import ExchangeType
    from core.adapters.exchanges.adapters.lighter import LighterAdapter
    from core.adapters.exchanges.adapters.arcus import ArcusAdapter
    keys = ('STOCK_LIGHTER_PRIVATE_KEY', 'STOCK_LIGHTER_ACCOUNT_INDEX', 'STOCK_LIGHTER_API_KEY_INDEX',
            'STOCK_ARCUS_WALLET_ADDRESS', 'STOCK_ARCUS_API_KEY', 'STOCK_ARCUS_SIGNING_KEY', 'STOCK_ARCUS_ACCOUNT_INDEX')
    if any(not os.environ.get(k) for k in keys):
        raise ValueError('Missing dedicated stock credentials')
    lighter = ExchangeConfig('lighter', 'Lighter', ExchangeType.PERPETUAL, '', '',
                             extra_params={'stock_profile': True, 'strict_order_state': True})
    lighter.api_key_private_key = os.environ[keys[0]]
    lighter.account_index = int(os.environ[keys[1]])
    lighter.api_key_index = int(os.environ[keys[2]])
    if lighter.account_index < 0 or not 0 <= lighter.api_key_index <= 255:
        raise ValueError('Invalid Lighter account/key index')
    arcus = ExchangeConfig('arcus', 'Arcus', ExchangeType.PERPETUAL, os.environ[keys[4]], '',
                           wallet_address=os.environ[keys[3]],
                           extra_params={'stock_profile': True, 'api_signing_key': os.environ[keys[5]], 'account_index': int(os.environ[keys[6]])})
    # Validate signing key correspondence before creating any network session.
    arcus_adapter = ArcusAdapter(arcus)
    arcus_adapter._sign({})
    return {'lighter': LighterAdapter(lighter), 'arcus': arcus_adapter}


def field(row, *names):
    for name in names:
        value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
        if value is not None:
            return value
    raise ValueError(f'Missing authoritative market field: {names[0]}')


def lighter_metadata(row):
    price = int(field(row, 'supported_price_decimals', 'price_decimals'))
    size = int(field(row, 'supported_size_decimals', 'size_decimals'))
    if not 0 <= price <= 12 or not 0 <= size <= 12:
        raise ValueError('Invalid Lighter precision metadata')
    return {'price_decimals': price, 'size_decimals': size,
            'step': D(10) ** -size,
            'min_quantity': positive(field(row, 'min_base_amount')),
            'min_notional': positive(field(row, 'min_quote_amount'))}


def common_step(a, b):
    a, b = positive(a), positive(b)
    scale = D(10) ** max(-a.as_tuple().exponent, -b.as_tuple().exponent, 0)
    return D(lcm(int(a * scale), int(b * scale))) / scale


async def load_stock_constraints(orc):
    lighter, arcus = orc.exchange_adapters['lighter'], orc.exchange_adapters['arcus']
    response = await asyncio.wait_for(lighter._rest.order_api.order_books(), timeout=10)
    rows = field(response, 'order_books')
    meta = {}
    for row in rows:
        base = field(row, 'symbol')
        if base not in {s.split('-')[0] for s in SYMBOLS}:
            continue
        if base in meta or str(field(row, 'status')).lower() != 'active':
            raise ValueError('Duplicate or inactive stock market')
        meta[base] = lighter_metadata(row)
    constraints = {}
    for symbol in SYMBOLS:
        base = symbol.split('-')[0]
        lm = meta[base]
        am = arcus._market(symbol)
        step = common_step(lm['step'], am['stepSize'])
        constraints[base] = {'price_tick_by_exchange': {'lighter': D(10) ** -lm['price_decimals'], 'arcus': max([positive(am['tickSize'])] + [positive(t['tick']) for t in am.get('tickTiers', [])])}, 'quantity_step': step, 'min_quantity': max(lm['min_quantity'], positive(am['minOrderSize'])),
                             'min_notional_by_exchange': {'lighter': lm['min_notional'], 'arcus': positive(am['minOrderNotional'])}}
    lighter._rest._stock_market_metadata = meta
    orc.executor.market_constraints = constraints


from core.services.arbitrage_monitor_v2.core.unified_orchestrator import UnifiedOrchestrator


class StockOrchestrator(UnifiedOrchestrator):
    stock_profile = True

    def __init__(self):
        validate_stock_profile(ROOT)
        super().__init__(segmented_config_path=ROOT / 'config/arbitrage/stock_segmented.yaml',
                         monitor_config_path=ROOT / 'config/arbitrage/stock_monitor.yaml',
                         execution_config_path=ROOT / 'config/arbitrage/stock_execution.yaml',
                         multi_exchange_config_path=ROOT / 'config/arbitrage/stock_pairs.yaml')
        if tuple(self.monitor_config.symbols) != SYMBOLS or set(self.exchange_adapters) != {'lighter', 'arcus'}:
            raise ValueError('Stock profile requires exactly the five supported stocks and two exchanges')
        self.executor.stock_profile = True
        self.decision_engine.stock_profile = self

    def stock_order_quantity(self, symbol):
        symbol = self.config_manager.get_config(symbol).symbol
        if symbol not in SYMBOLS:
            raise ValueError('Unsupported stock symbol')
        rows, depth = [], []
        for exchange in ('lighter', 'arcus'):
            book = self.data_processor.get_orderbook(exchange, symbol, max_age_seconds=self.get_data_freshness_seconds(exchange))
            if not book or not book.best_ask or not book.best_bid:
                return D(0)
            rows.extend((positive(book.best_ask.price), positive(book.best_bid.price)))
            depth.extend((positive(book.best_ask.size), positive(book.best_bid.size)))
        constraints = self.executor.market_constraints.get(symbol.split('-')[0])
        if not constraints:
            return D(0)
        step = positive(constraints['quantity_step'])
        qty = (min(min(D(500), self.config_manager.get_config(symbol).quantity_config.target_value_usdc) / self.stock_protected_price(symbol, max(rows)), min(depth)) / step).to_integral_value(rounding=ROUND_DOWN) * step
        if qty < constraints['min_quantity'] or any(qty * p < n for p in rows for n in constraints['min_notional_by_exchange'].values()):
            return D(0)
        return qty

    def stock_close_quantity(self, symbol, available):
        position = self.decision_engine.get_position(symbol)
        if not position:
            return D(0)
        depths = []
        for exchange, leg, is_buy in ((position.exchange_buy, position.buy_symbol, False),
                                      (position.exchange_sell, position.sell_symbol, True)):
            book = self.data_processor.get_orderbook(exchange, leg or symbol, max_age_seconds=self.get_data_freshness_seconds(exchange))
            level = (book.best_ask if is_buy else book.best_bid) if book else None
            if not level:
                return D(0)
            positive(level.price)
            depths.append(positive(level.size))
        cfg = self.config_manager.get_config(symbol)
        constraints = self.executor.market_constraints[cfg.symbol.split('-')[0]]
        step = positive(constraints['quantity_step'])
        quantity = (min(positive(available), *depths) / step).to_integral_value(rounding=ROUND_DOWN) * step
        return quantity if quantity >= constraints['min_quantity'] else D(0)

    def stock_protected_price(self, symbol, price):
        cfg = self.config_manager.get_config(symbol)
        ticks = self.executor.market_constraints[cfg.symbol.split('-')[0]]['price_tick_by_exchange']
        value = positive(price) * (D(1) + SLIPPAGE)
        return max((value / positive(tick)).to_integral_value(rounding=ROUND_UP) * positive(tick) for tick in ticks.values())

    def stock_validate_open(self, request, exchange, gross, symbol_gross, added):
        if request.symbol not in SYMBOLS and self.config_manager.get_config(request.symbol).symbol not in SYMBOLS:
            raise ValueError('Unsupported stock')
        if set((request.exchange_buy, request.exchange_sell)) != {'lighter', 'arcus'}:
            raise ValueError('Unsupported stock exchange pair')
        if added > D(500) or symbol_gross + added > D(2000) or gross + added > D(8000):
            raise ValueError('Stock nominal limit exceeded')
        # Conservative 1x margin reservation: no assumed leverage or cross-symbol offsets.
        if gross + added > D(1500):
            raise ValueError('Conservative stock margin budget exceeded')
        for ex, is_buy, leg in ((request.exchange_buy, True, request.buy_symbol), (request.exchange_sell, False, request.sell_symbol)):
            book = self.data_processor.get_orderbook(ex, leg or request.symbol, max_age_seconds=self.get_data_freshness_seconds(ex))
            level = (book.best_ask if is_buy else book.best_bid) if book else None
            if level is None or positive(level.size) < request.quantity:
                raise ValueError('Insufficient fresh first-level stock depth')
