import pandas as pd
from typing import Union

# กำหนด Timezone หลักของโปรเจกต์ไว้ที่เดียว
THAI_TZ = "Asia/Bangkok"

def get_thai_time() -> pd.Timestamp:
    """ดึงเวลาปัจจุบันใน Timezone ประเทศไทย"""
    return pd.Timestamp.now(tz=THAI_TZ)

def convert_index_to_thai_tz(datetime_index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """แปลง Timezone ของ Pandas DatetimeIndex ให้เป็นเวลาไทย"""
    if datetime_index.tz is None:
        # ถ้าไม่มี Timezone ติดมา ให้มองเป็น UTC ก่อน แล้วแปลงเป็นไทย
        return datetime_index.tz_localize("UTC").tz_convert(THAI_TZ)
    return datetime_index.tz_convert(THAI_TZ)

def to_thai_time(dt_val: Union[str, int, float]) -> pd.Timestamp:
    """แปลงค่าเวลาทุกรูปแบบ (String, Unix Timestamp) ให้เป็นเวลาไทย"""
    if pd.isna(dt_val) or not dt_val:
        raise ValueError("Empty datetime value")
    
    # ถ้าเป็นตัวเลข (เช่น providerPublishTime ของ yfinance)
    if isinstance(dt_val, (int, float)):
        dt = pd.to_datetime(dt_val, unit='s', utc=True)
    # ถ้าเป็นข้อความ (เช่น pubDate หรือมีตัว Z ต่อท้าย) Pandas จะจัดการให้เอง
    else:
        dt = pd.to_datetime(dt_val, utc=True)
        
    return dt.tz_convert(THAI_TZ)