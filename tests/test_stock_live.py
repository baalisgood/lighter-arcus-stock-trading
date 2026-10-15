"""Offline execution acceptance against the real unified engine and executor."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import stock_runtime as stock
from core.adapters.exchanges.models import OrderBookData, OrderBookLevel, OrderData, OrderStatus, OrderType, OrderSide
from core.services.arbitrage_monitor_v2.analysis.spread_calculator import SpreadData
from core.services.arbitrage_monitor_v2.execution.arbitrage_executor import ExecutionRequest

S = stock.SYMBOLS[0]

def run(coro): return asyncio.run(coro)


class FakeAdapter:
    strict_order_state = True
    def __init__(self, exchange):
        self.exchange_id = exchange
        self.config = NS(exchange_id=exchange)
        self.positions = {}
        self.writes = []
        self.orders = {}
        self._uncertain = set()
        self.fail = False
    async def get_balances(self):
        return [NS(currency='USDC', total=D(10000), free=D(10000), used=D(0), timestamp=datetime.now())]
    async def get_positions(self):
        return [NS(symbol=s, size=abs(q), side='long' if q > 0 else 'short', entry_price=D(100),
                   mark_price=D(100), timestamp=datetime.now()) for s, q in self.positions.items() if q]
    async def get_open_orders(self): return []
    async def get_order(self, identity, symbol=None): return self.orders[identity]
    async def create_order(self, symbol, side, order_type, amount, price=None, params=None):
        from core.adapters.exchanges.order_state import OrderStateUnknownError
        if self.fail:
            raise OrderStateUnknownError(self.exchange_id)
        assert order_type == OrderType.MARKET
        params = params or {}
        self.writes.append((symbol, side, amount, dict(params)))
        qty = amount if side == OrderSide.BUY else -amount
        if params.get('reduce_only') or params.get('reduceOnly'):
            assert self.positions.get(symbol, D(0)) * qty < 0
            assert abs(qty) <= abs(self.positions[symbol])
        self.positions[symbol] = self.positions.get(symbol, D(0)) + qty
        px = D(100) if self.exchange_id == 'lighter' else D(101)
        identity = str(len(self.writes))
        order = OrderData(identity, identity, symbol, side, order_type, amount, price, amount, D(0), amount*px,
                          px, OrderStatus.FILLED, datetime.now(), datetime.now(), {'currency':'USDC','cost': D(0)}, [], {}, {})
        self.orders[identity] = order
        return order


@pytest.fixture
def orc(monkeypatch):
    adapters = {ex: FakeAdapter(ex) for ex in ('lighter','arcus')}
    monkeypatch.setattr(stock, 'create_stock_adapters', lambda: adapters)
    o = stock.StockOrchestrator()
    o._bootstrap_positions_block_open = False
    o.executor.market_constraints = {s.split('-')[0]: {'price_tick_by_exchange':{'lighter':D('.01'),'arcus':D('.01')}, 'quantity_step':D('.01'), 'min_quantity':D('.01'),
        'min_notional_by_exchange': {'lighter':D(1),'arcus':D(1)}} for s in stock.SYMBOLS}
    for ex in adapters:
        for symbol in stock.SYMBOLS:
            px = D(100) if ex == 'lighter' else D(101)
            o.data_processor.orderbooks[ex][symbol] = OrderBookData(symbol,[OrderBookLevel(px,D(100))],[OrderBookLevel(px,D(100))],datetime.now(),received_timestamp=datetime.now())
    return o


def edge(symbol=S, reverse=False):
    a,b = (D(101),D(100)) if reverse else (D(100),D(101))
    return SpreadData(symbol,'arcus' if reverse else 'lighter','lighter' if reverse else 'arcus',a,b,D(100),D(100),b-a,float((b-a)/a*100))


def request(qty='1',symbol=S):
    e=edge(symbol)
    req=ExecutionRequest(symbol,'lighter','arcus',e.price_buy,e.price_sell,D(qty),spread_data=e,grid_threshold_pct=D('.1'))
    req._expected_position_quantity=D(0)
    return req


async def open_stock(o, symbol=S, qty=D(1)):
    await o._execute_open_with_lock(symbol=symbol,open_quantity=qty,spread_data=edge(symbol),funding_rate_data=None,
        is_last_split=False,grid_level=1,slippage_pct=D('.02'),buy_limit_offset=None,sell_limit_offset=None,
        position=o.decision_engine.get_position(symbol),open_key=symbol)


def test_real_unified_executor_open_and_reduce_only_close(orc):
    async def scenario():
        allowed,qty=await orc.decision_engine.should_open(S,edge(),skip_persistence=True)
        assert allowed and D(0)<qty*D('101.0202')<=D(500)
        await open_stock(orc,qty=qty)
        pos=orc.decision_engine.get_position(S)
        assert pos and pos.total_quantity==qty
        for adapter in orc.exchange_adapters.values(): assert len(adapter.writes)==1
        for ex in orc.exchange_adapters:
            book=orc.data_processor.orderbooks[ex][S]
            book.bids[0].price=book.asks[0].price=D('100.5')
        close_edge=edge(reverse=True)
        close_edge.price_buy=close_edge.price_sell=D('100.5')
        await orc._execute_and_record_close(S,qty,close_edge,'FIFO close',True,1,D('.02'),None,None,pos,None)
        assert pos.total_quantity==0
        for adapter in orc.exchange_adapters.values():
            assert len(adapter.writes)==2
            assert adapter.writes[-1][3].get('reduce_only') or adapter.writes[-1][3].get('reduceOnly')
            assert not any(adapter.positions.values())
    run(scenario())


@pytest.mark.parametrize('failure',['orders','positions','balances','unknown','stale','depth','metadata','limit','slip'])
def test_last_gate_failures_never_write(orc,failure):
    a=orc.exchange_adapters['arcus'];req=request()
    if failure=='orders': a.get_open_orders=AsyncMock(return_value=[object()])
    if failure=='positions': a.get_positions=AsyncMock(return_value=None)
    if failure=='balances': a.get_balances=AsyncMock(side_effect=asyncio.TimeoutError())
    if failure=='unknown': a._uncertain.add('unknown')
    if failure=='stale': orc.data_processor.orderbooks['arcus'][S].timestamp=datetime.now()-timedelta(seconds=60)
    if failure=='depth': orc.data_processor.orderbooks['arcus'][S].bids[0].size=D('.1')
    if failure=='metadata': orc.executor.market_constraints={}
    if failure=='limit': req.quantity=D(6)
    if failure=='slip': req.quantity=D('4.95') # 499.95 at raw 101, exceeds 500 at protected price.
    result=run(orc.executor.execute_arbitrage(req))
    assert not result.success
    assert all(not a.writes for a in orc.exchange_adapters.values())


def test_stock_sizing_uses_common_step_and_first_depth(orc):
    orc.executor.market_constraints['MU']['quantity_step']=D('.03')
    orc.data_processor.orderbooks['lighter'][S].asks[0].size=D('1.325')
    qty=orc.stock_order_quantity(S)
    assert qty==D('1.32')
    orc.data_processor.orderbooks['lighter'][S].asks.clear()
    assert orc.stock_order_quantity(S)==0
    with pytest.raises(ValueError): orc.config_manager.get_config('BTC-USDC-PERP')


def test_concurrent_stock_opens_respect_shared_pending_budget(orc):
    async def scenario():
        await asyncio.gather(*(open_stock(orc,symbol=s,qty=D('4.94')) for s in stock.SYMBOLS))
        assert sum(p.total_quantity for _,p in orc.decision_engine.iter_pair_positions())==D('14.82')
        assert len(orc.exchange_adapters['lighter'].writes)==3
        assert len(orc.exchange_adapters['arcus'].writes)==3
    run(scenario())


def test_single_leg_unknown_latches_new_opens(orc):
    orc.exchange_adapters['arcus'].fail=True
    run(open_stock(orc))
    assert orc.executor._unknown_execution_pairs
    count=len(orc.exchange_adapters['lighter'].writes)
    run(open_stock(orc,symbol=stock.SYMBOLS[1]))
    assert len(orc.exchange_adapters['lighter'].writes)==count


def test_missing_credentials_fails_before_adapter_creation(monkeypatch):
    for key in list(stock.os.environ):
        if key.startswith(('STOCK_','LIGHTER_','ARCUS_')): monkeypatch.delenv(key)
    with pytest.raises(ValueError,match='Missing dedicated'): stock.create_stock_adapters()


def test_common_steps_and_missing_metadata():
    assert stock.common_step('.02','.03')==D('.06')
    with pytest.raises(ValueError): stock.lighter_metadata({'price_decimals':2})


@pytest.mark.parametrize('gross,symbol_gross,added', [('0','0','501'),('1600','1600','401'),('7900','0','101')])
def test_independent_nominal_hard_limits(orc,gross,symbol_gross,added):
    with pytest.raises(ValueError,match='nominal'):
        orc.stock_validate_open(request(),'lighter',D(gross),D(symbol_gross),D(added))


def test_margin_budget_boundary(orc):
    orc.stock_validate_open(request(),'lighter',D(1000),D(1000),D(500))
    with pytest.raises(ValueError,match='margin'):
        orc.stock_validate_open(request(),'lighter',D('1000.01'),D(1000),D(500))


def test_lighter_transport_disables_redirects_and_rejects_foreign_host():
    from core.adapters.exchanges.adapters.lighter_transport import harden_client
    response=NS(status=302,close=lambda:None)
    original=AsyncMock(return_value=response)
    session=NS(_request=original)
    client=NS(rest_client=NS(pool_manager=session))
    harden_client(client,'https://mainnet.zklighter.elliot.ai')
    async def scenario():
        with pytest.raises(ValueError,match='destination'):
            await session._request('GET','https://attacker.invalid/api')
        original.assert_not_awaited()
        with pytest.raises(ValueError,match='redirect'):
            await session._request('GET','https://mainnet.zklighter.elliot.ai/api')
        assert original.call_args.kwargs['allow_redirects'] is False
    run(scenario())


@pytest.mark.parametrize('method',['GET','POST'])
def test_arcus_transport_rejects_redirect_without_replay(method):
    from core.adapters.exchanges.adapters.arcus import ArcusAdapter, ArcusRequestRejectedError
    from core.adapters.exchanges.order_state import OrderStateUnknownError
    class Response:
        status=302
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    seen=[]
    def request(*args,**kwargs): seen.append(kwargs);return Response()
    adapter=object.__new__(ArcusAdapter)
    adapter._session=NS(request=request)
    adapter.base_url='https://api.arcus.xyz'
    adapter.api_key='offline-key'
    adapter._invalidate_account_reads=lambda:None
    expected=ArcusRequestRejectedError if method=='GET' else OrderStateUnknownError
    with pytest.raises(expected):run(adapter._request(method,'/v1/test',body={}))
    assert len(seen)==1 and seen[0]['allow_redirects'] is False


def test_stock_metadata_missing_duplicate_and_offline_fail_closed(orc):
    row=NS(symbol='MU',status='active',supported_price_decimals=2,supported_size_decimals=2,min_base_amount='.01',min_quote_amount='1')
    lighter=orc.exchange_adapters['lighter']
    arcus=orc.exchange_adapters['arcus']
    lighter._rest=NS(order_api=NS(order_books=AsyncMock(return_value=NS(order_books=[row,row]))))
    arcus._market=lambda symbol: {'stepSize':'.01','minOrderSize':'.01','minOrderNotional':'1'}
    with pytest.raises(ValueError,match='Duplicate'):run(stock.load_stock_constraints(orc))
    row.status='inactive'
    lighter._rest.order_api.order_books.return_value=NS(order_books=[row])
    with pytest.raises(ValueError,match='inactive'):run(stock.load_stock_constraints(orc))
    lighter._rest.order_api.order_books.side_effect=asyncio.TimeoutError()
    with pytest.raises(asyncio.TimeoutError):run(stock.load_stock_constraints(orc))


def test_all_websocket_redirects_are_rejected():
    from core.adapters.exchanges.adapters.secure_websocket import connect
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    from websockets.datastructures import Headers
    for target in ('wss://attacker.invalid/stream','wss://mainnet.zklighter.elliot.ai/other'):
        exc=InvalidStatus(Response(302,'Found',Headers({'Location':target}),b''))
        assert connect.process_redirect(None,exc) is exc


@pytest.mark.parametrize('case',['missing','unknown','symlink'])
def test_local_env_refuses_invalid_files(tmp_path,monkeypatch,case):
    monkeypatch.setattr(stock,'ROOT',tmp_path)
    env=tmp_path/'.env.stock'
    env.write_text('STOCK_LIGHTER_PRIVATE_KEY=offline-sentinel\n' + ('UNKNOWN=value\n' if case=='unknown' else ''))
    if case=='symlink':
        env.rename(tmp_path/'target')
        env.symlink_to(tmp_path/'target')
    monkeypatch.setenv('LIGHTER_API_KEY_PRIVATE_KEY','inherited-must-not-be-used')
    with pytest.raises(ValueError):stock.load_stock_environment()


def test_local_env_clears_legacy_and_uses_only_explicit_stock_values(tmp_path,monkeypatch):
    monkeypatch.setattr(stock,'ROOT',tmp_path)
    keys=('STOCK_LIGHTER_PRIVATE_KEY','STOCK_LIGHTER_ACCOUNT_INDEX','STOCK_LIGHTER_API_KEY_INDEX',
          'STOCK_ARCUS_WALLET_ADDRESS','STOCK_ARCUS_API_KEY','STOCK_ARCUS_SIGNING_KEY','STOCK_ARCUS_ACCOUNT_INDEX')
    (tmp_path/'.env.stock').write_text('\n'.join(k+'=offline-sentinel' for k in keys))
    monkeypatch.setenv('LIGHTER_API_KEY_PRIVATE_KEY','legacy')
    monkeypatch.setenv('ARCUS_API_KEY','legacy')
    stock.load_stock_environment()
    assert 'LIGHTER_API_KEY_PRIVATE_KEY' not in stock.os.environ and 'ARCUS_API_KEY' not in stock.os.environ
    assert stock.os.environ['STOCK_LIGHTER_PRIVATE_KEY']=='offline-sentinel'
    for key in keys:monkeypatch.delenv(key)


def test_low_free_collateral_rejected_before_either_leg(orc):
    async def balances():return [NS(currency='USDC',total=D(10000),free=D('.5'),used=D(9999),timestamp=datetime.now())]
    orc.exchange_adapters['arcus'].get_balances=balances
    result=run(orc.executor.execute_arbitrage(request()))
    assert not result.success
    assert all(not a.writes for a in orc.exchange_adapters.values())
