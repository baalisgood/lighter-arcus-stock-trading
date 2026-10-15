"""Offline stock symbol conversion contracts; no credentials or network."""
import pytest

@pytest.mark.parametrize('stock', ['MU', 'SNDK', 'NVDA', 'AMD', 'INTC'])
def test_stock_symbol_mapping_roundtrip(stock):
    from core.services.arbitrage_monitor.utils.symbol_converter import SimpleSymbolConverter
    converter = SimpleSymbolConverter()
    standard = stock + '-USDC-PERP'
    for venue, native in [('lighter', stock), ('arcus', stock + '-USD')]:
        assert converter.convert_to_exchange(standard, venue) == native
        assert converter.convert_from_exchange(native, venue) == standard

