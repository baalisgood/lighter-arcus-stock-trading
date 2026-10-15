"""Regression coverage for stock configuration, actual payloads and grid transitions."""
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import shutil
import pytest
import yaml
import run_stock
import stock_runtime as stock
from stock_profile import validate_stock_profile, SLIPPAGE
from test_stock_live import orc, edge, request, run, S


@pytest.mark.parametrize('name',['stock_monitor','stock_segmented','stock_execution','stock_pairs','multi_leg_pairs'])
@pytest.mark.parametrize('bad',['missing','malformed','empty','symlink'])
def test_all_profiles_fail_before_check_or_live_adapter_construction(tmp_path,monkeypatch,name,bad):
    shutil.copytree(stock.ROOT/'config',tmp_path/'config')
    path=tmp_path/f'config/arbitrage/{name}.yaml'
    if bad=='missing':path.unlink()
    elif bad=='malformed':path.write_text('[')
    elif bad=='empty':path.write_text('{}')
    else:
        path.rename(path.with_suffix('.target'))
        path.symlink_to(path.with_suffix('.target'))
    monkeypatch.setattr(run_stock,'ROOT',tmp_path)
    monkeypatch.setattr(stock,'ROOT',tmp_path)
    construct=Mock(side_effect=AssertionError('must not construct adapter'))
    monkeypatch.setattr(stock,'create_stock_adapters',construct)
    with pytest.raises(ValueError):run_stock.check_profile()
    with pytest.raises(ValueError):stock.StockOrchestrator()
    construct.assert_not_called()


@pytest.mark.parametrize('name,path',[
    ('stock_execution',('arbitrage_execution','order_execution','max_slippage')),
    ('stock_execution',('arbitrage_execution','exchange_order_modes','arcus')),
    ('stock_segmented',('default_config','grid_config','initial_spread_threshold')),
    ('stock_segmented',('decision','exchange_fee_config','lighter')),
    ('stock_pairs',('symbols',)),('stock_monitor',('health_check','data_timeout'))])
def test_required_fields_never_fall_back(tmp_path,monkeypatch,name,path):
    shutil.copytree(stock.ROOT/'config',tmp_path/'config')
    file=tmp_path/f'config/arbitrage/{name}.yaml'
    doc=yaml.safe_load(file.read_text());node=doc
    for key in path[:-1]:node=node[key]
    del node[path[-1]];file.write_text(yaml.safe_dump(doc))
    monkeypatch.setattr(stock,'ROOT',tmp_path)
    construct=Mock()
    monkeypatch.setattr(stock,'create_stock_adapters',construct)
    with pytest.raises(ValueError):stock.StockOrchestrator()
    construct.assert_not_called()


def test_strict_generic_loaders_raise_on_bad_stock_files(tmp_path):
    from core.services.arbitrage_monitor_v2.config.unified_config_manager import UnifiedConfigManager
    from core.services.arbitrage_monitor_v2.config.multi_exchange_config import MultiExchangeArbitrageConfigManager
    shutil.copytree(stock.ROOT/'config',tmp_path/'config')
    for name,cls in [('stock_execution',UnifiedConfigManager),('stock_pairs',MultiExchangeArbitrageConfigManager)]:
        path=tmp_path/f'config/arbitrage/{name}.yaml';path.write_text('[')
        with pytest.raises(ValueError):cls(path,strict=True)


@pytest.mark.parametrize('quantity,price',[('4.94','110'),('10','100')])
def test_real_lighter_large_reduce_only_conversion_keeps_precision(quantity,price):
    from core.adapters.exchanges.adapters.lighter_rest import LighterRest
    rest=object.__new__(LighterRest);rest.config={'stock_profile':True}
    info={'market_index':164,'price_decimals':2,'price_multiplier':D(100),'size_decimals':2}
    with pytest.raises(ValueError,match='nominal'):rest._convert_market_order_params(info,D(quantity),D(price),'sell')
    result=rest._convert_market_order_params(info,D(quantity),D(price),'sell',reduce_only=True,client_order_id=1)
    assert result['reduce_only'] and result['base_amount']==int(D(quantity)*100)
    with pytest.raises(ValueError,match='precision'):
        rest._convert_market_order_params(info,D('1.001'),D(price),'sell',reduce_only=True)


@pytest.mark.parametrize('quantity,price',[('4.94','110'),('10','100')])
def test_real_arcus_large_reduce_only_payload_keeps_precision(quantity,price):
    from core.adapters.exchanges.adapters.arcus import ArcusAdapter
    from core.adapters.exchanges.interface import ExchangeConfig
    from core.adapters.exchanges.models import ExchangeType,OrderSide,OrderType
    a=ArcusAdapter(ExchangeConfig('arcus','Arcus',ExchangeType.PERPETUAL,'','',extra_params={'stock_profile':True}))
    a._do_authenticate=AsyncMock();a._sign=lambda payload:'offline-signature'
    a._set_markets([{'marketDisplayName':'MU-USD','marketId':164,'status':'ONLINE','stepSize':'.01','tickSize':'.01',
                    'minOrderSize':'.01','maxOrderSize':'1000','minOrderNotional':'10','markPrice':price}])
    a.get_orderbook=AsyncMock(return_value=NS(best_bid=NS(price=D(price)),best_ask=NS(price=D(price))))
    a._request=AsyncMock(return_value=(200,{'orderId':'offline'}))
    a._await_order=AsyncMock(return_value=NS(id='offline'))
    async def scenario():
        with pytest.raises(ValueError,match='nominal'):
            await a.create_order(S,OrderSide.SELL,OrderType.MARKET,D(quantity))
        a._request.assert_not_awaited()
        await a.create_order(S,OrderSide.SELL,OrderType.MARKET,D(quantity),params={'reduce_only':True})
        body=a._request.call_args.kwargs['body']
        assert body['reduceOnly'] and D(body['quantity'])==D(quantity)
        assert D(body['price'])==(D(price)*(1-SLIPPAGE)//D('.01'))*D('.01')
        with pytest.raises(ValueError,match='tick/step'):
            await a.create_order(S,OrderSide.SELL,OrderType.MARKET,D('1.001'),params={'reduce_only':True})
    run(scenario())


def test_config_sizing_and_actual_lighter_protection_share_one_slippage(orc):
    from core.adapters.exchanges.adapters.lighter_rest import LighterRest
    from core.adapters.exchanges.adapters.lighter import LighterAdapter
    docs=validate_stock_profile(stock.ROOT)
    assert D(str(docs['stock_execution']['arbitrage_execution']['order_execution']['max_slippage']))==SLIPPAGE
    assert D(str(docs['stock_segmented']['default_config']['grid_config']['slippage_tolerance']))==SLIPPAGE
    config=NS(extra_params={'stock_profile':True},testnet=False,api_key_private_key='offline',account_index=1,api_key_index=1)
    assert D(LighterAdapter._convert_config_to_dict(None,config)['slippage'])==SLIPPAGE
    rest=object.__new__(LighterRest);rest.config={'stock_profile':True};rest.base_slippage=SLIPPAGE
    px=run(rest._calculate_slippage_protection_price(S,'buy',D(101),slippage_multiplier=D(100)))
    assert px==D(101)*(1+SLIPPAGE)
    qty=orc.stock_order_quantity(S)
    info={'market_index':164,'price_decimals':2,'price_multiplier':D(100),'size_decimals':2}
    payload=rest._convert_market_order_params(info,qty,px,'buy',client_order_id=1)
    signed_price=D(payload['avg_execution_price'])/100
    assert signed_price<=orc.stock_protected_price(S,D(101)) and signed_price*qty<=500


def close_edge(relative):
    return replace(edge(reverse=True),spread_pct=-float(relative))


def test_real_decision_t3_to_t2_then_t1_to_flat(orc):
    e=orc.decision_engine;cfg=orc.config_manager.get_config(S)
    async def scenario():
        signal=replace(edge(),spread_pct=.366) # net .225, T3
        ok,first=await e.should_open(S,signal,skip_persistence=True)
        assert ok and first>0
        await e.record_open(S,first,signal,filled_quantity=D(1))
        assert cfg.quantity_config.base_quantity==D(1)
        e.report_open_shortfall(S,first,D(1))
        assert e.pending_open_shortfall[S]==0
        ok,next_qty=await e.should_open(S,replace(signal,price_buy=D("100.01")),skip_persistence=True)
        assert ok and next_qty==D(2)
        # The first confirmed partial fill, rather than the desired order, anchors this cycle.
        for _ in range(2):await e.record_open(S,D(1),signal,filled_quantity=D(1))
        assert e.get_current_segments(S)==3
        assert e._calculate_target_position(S,3,cfg)==D(3)
        assert e._get_close_persistence_threshold(D(3),cfg)==pytest.approx(.15)
        ok,qty,_,_=await e.should_close(S,close_edge('.125'),skip_persistence=True)
        assert ok and qty==D(1)
        await e.record_close(S,qty,close_edge('.125'),'T3->T2')
        assert e.get_current_segments(S)==2
        ok,qty,_,_=await e.should_close(S,close_edge('.05'),skip_persistence=True)
        assert ok and qty==D(1)
        await e.record_close(S,qty,close_edge('.05'),'T2->T1')
        ok,qty,_,_=await e.should_close(S,close_edge('0'),skip_persistence=True)
        assert ok and qty==D(1)
        await e.record_close(S,qty,close_edge('0'),'T1->flat')
        assert cfg.quantity_config.base_quantity==0 and e.get_current_segments(S)==0
    run(scenario())


def test_thin_depth_changes_execution_size_without_moving_grid_anchor(orc):
    e=orc.decision_engine;cfg=orc.config_manager.get_config(S)
    async def scenario():
        await e.record_open(S,D(1),edge(),filled_quantity=D('.5'))
        orc.data_processor.orderbooks['arcus'][S].asks[0].size=D('.1')
        orc.data_processor.orderbooks['lighter'][S].bids[0].size=D('.1')
        assert e._calculate_target_position(S,3,cfg)==D('1.5')
        ok,qty,_,_=await e.should_close(S,close_edge('0'),skip_persistence=True)
        assert ok and qty==D('.1')
        await e.record_close(S,qty,close_edge('0'),'partial close')
        assert cfg.quantity_config.base_quantity==D('.5')
    run(scenario())


def test_aggregate_recovery_record_anchors_one_synthetic_grid(orc):
    e=orc.decision_engine;cfg=orc.config_manager.get_config(S)
    run(e.record_open(S,D(10),edge(),filled_quantity=D(10)))
    assert cfg.quantity_config.base_quantity==10 and e.get_current_segments(S)==1
    assert e._calculate_target_position_by_spread(S,.05,cfg)==10


def test_small_reduce_only_tail_bypasses_open_notional_minimum(orc):
    e=orc.decision_engine
    async def scenario():
        await e.record_open(S,D('.01'),edge(),filled_quantity=D('.01'))
        orc.executor.market_constraints['MU']['min_notional_by_exchange']={'lighter':D(10),'arcus':D(10)}
        ok,qty,_,_=await e.should_close(S,close_edge('0'),skip_persistence=True)
        assert ok and qty==D('.01')
        req=request('.01');req.is_open=False
        orc.executor._validate_pair_quantity(req)
        req.is_open=True
        with pytest.raises(ValueError):orc.executor._validate_pair_quantity(req)
    run(scenario())
