"""
套利监控系统 V2 - 入口文件

使用方法：
    python3 run_arbitrage_monitor_v2.py

可选参数：
    --debug         启用基础Debug模式
    --debug-detail  启用详细Debug模式
    --symbols       指定监控的交易对（用逗号分隔）
"""

from pathlib import Path
import asyncio
import argparse


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="套利监控系统 V2")
    
    parser.add_argument(
        '--config',
        type=str,
        default='config/arbitrage/monitor_v2.yaml',
        help='配置文件路径'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='启用基础Debug模式'
    )
    
    parser.add_argument(
        '--debug-detail',
        action='store_true',
        help='启用详细Debug模式'
    )
    
    parser.add_argument(
        '--symbols',
        type=str,
        help='监控的交易对（用逗号分隔，如：BTC,ETH,SOL）'
    )
    
    parser.add_argument(
        '--no-ui',
        action='store_true',
        help='禁用UI（仅后台运行）'
    )
    
    parser.add_argument('--public-only', action='store_true',
                        help='严格公共行情模式（仅股票白名单，无账户/交易配置）')
    return parser.parse_args()


async def main():
    """主函数"""
    # 解析参数
    args = parse_args()
    
    if args.public_only:
        if args.symbols or args.no_ui:
            raise ValueError('公共模式交易对和显示方式由显式配置固定')
        # All module-level loggers use paths relative to this independent project.
        import os
        os.chdir(Path(__file__).resolve().parent)
    else:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / '.env')

    from core.services.arbitrage_monitor_v2 import ArbitrageOrchestrator, DebugConfig

    # 创建Debug配置
    if args.debug_detail:
        debug_symbols = set(args.symbols.split(',')) if args.symbols else set()
        debug_config = DebugConfig.create_detailed(debug_symbols)
        print("🐛 详细Debug模式已启用")
    elif args.debug:
        debug_config = DebugConfig.create_basic()
        print("🐛 基础Debug模式已启用")
    else:
        debug_config = DebugConfig.create_production()
    
    # 创建调度器
    config_path = Path(args.config)
    if not config_path.exists():
        if args.public_only:
            raise ValueError(f'公共模式必须提供有效配置: {config_path}')
        print(f"⚠️  配置文件不存在: {config_path}")
        print("使用默认配置")
        config_path = None
    
    orchestrator = ArbitrageOrchestrator(config_path, debug_config, public_only=args.public_only)
    
    try:
        # 启动系统
        print("=" * 60)
        print("🚀 套利监控系统 V2 启动中...")
        print("=" * 60)
        
        await orchestrator.start()
        
        print("\n✅ 系统运行中，按 Ctrl+C 停止\n")
        
        # 持续运行
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n收到停止信号 (Ctrl+C)...")
    except Exception as e:
        print(f"\n❌ 系统错误: {e}")
        import traceback
        traceback.print_exc()
        if args.public_only:
            raise
    finally:
        # 停止系统
        await orchestrator.stop()
        print("\n👋 再见！")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

