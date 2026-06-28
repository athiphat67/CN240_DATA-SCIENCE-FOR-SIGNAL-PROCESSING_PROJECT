# config_loader.py
import yaml
import os
from dataclasses import dataclass

@dataclass
class BacktestConfig:
    gold_csv: str
    news_csv: str
    external_csv: str
    timeframe: str
    days: int
    react_max_iter: int
    provider: str
    model: str
    cache_dir: str
    output_dir: str

def load_config(yaml_path: str = "config.yaml") -> BacktestConfig:
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"ไม่พบไฟล์ Config ที่: {yaml_path}")
        
    with open(yaml_path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)
        
    return BacktestConfig(
        gold_csv=raw['data']['gold_csv'],
        news_csv=raw['data']['news_csv'],
        external_csv=raw['data']['external_csv'],
        timeframe=raw['backtest']['timeframe'],
        days=raw['backtest']['days'],
        react_max_iter=raw['backtest']['react_max_iter'],
        provider=raw['llm']['provider'],
        model=raw['llm']['model'],
        cache_dir=raw['paths']['cache_dir'],
        output_dir=raw['paths']['output_dir']
    )