import os
import yaml
import logging
from pathlib import Path

def load_config(path: str) -> dict:
    """YAML設定ファイルを読み込む"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def ensure_dir(path: str) -> Path:
    """ディレクトリが存在しない場合は作成し、Pathオブジェクトを返す"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

def setup_logger(name: str = __name__) -> logging.Logger:
    """ロガーをセットアップする"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
        
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger

def normalize_rel_path(path: str) -> str:
    """OSによるパス区切り文字の違いを吸収し、'/'に統一する"""
    return str(Path(path).as_posix())
