"""
weather_tool.py — MCP Server Tool Concept
Fetches weather forecast data from Taiwan's Central Weather Administration (CWA) API.
This module acts as the "tool" layer in the MCP (Model Context Protocol) pattern.
"""

import os
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ── City name normalisation ──────────────────────────────────────────────────
# CWA API uses the official Traditional Chinese form「臺」instead of「台」.
# This map lets users type either form (or abbreviations) and still get results.
_CITY_ALIASES: dict[str, str] = {
    "台北市": "臺北市",  "台北": "臺北市",  "臺北": "臺北市",
    "台中市": "臺中市",  "台中": "臺中市",  "臺中": "臺中市",
    "台南市": "臺南市",  "台南": "臺南市",  "臺南": "臺南市",
    "台東縣": "臺東縣",  "台東": "臺東縣",  "臺東": "臺東縣",
    "新北":   "新北市",
    "桃園":   "桃園市",
    "高雄":   "高雄市",
    "基隆":   "基隆市",
    "新竹市": "新竹市",  "新竹縣": "新竹縣",  "新竹": "新竹市",
    "苗栗":   "苗栗縣",
    "彰化":   "彰化縣",
    "南投":   "南投縣",
    "雲林":   "雲林縣",
    "嘉義市": "嘉義市",  "嘉義縣": "嘉義縣",  "嘉義": "嘉義市",
    "屏東":   "屏東縣",
    "宜蘭":   "宜蘭縣",
    "花蓮":   "花蓮縣",
    "澎湖":   "澎湖縣",
    "金門":   "金門縣",
    "連江":   "連江縣",
}


def get_weather(location_name: str) -> str:
    """
    Retrieve the weather forecast for a given location in Taiwan.

    This function queries the CWA Open Data API (F-C0032-001) which provides
    36-hour forecasts covering weather phenomenon, precipitation probability,
    and temperature range for all counties/cities in Taiwan.

    Args:
        location_name: Name of the county/city in Traditional Chinese,
                       e.g. "桃園市", "台北市" or "臺北市", "高雄市"

    Returns:
        A human-readable string summarising the weather conditions,
        or an error message string if data cannot be retrieved.
    """
    # Normalise city name to match CWA's official naming (臺 not 台)
    location_name = _CITY_ALIASES.get(location_name.strip(), location_name.strip())

    api_key = os.getenv("CWA_API_KEY")
    if not api_key:
        return "❌ 錯誤：找不到 CWA_API_KEY，請確認 .env 檔案已正確設定。"

    url = (
        "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
        f"?Authorization={api_key}&locationName={location_name}"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return f"❌ 錯誤：查詢 {location_name} 天氣時連線逾時，請稍後再試。"
    except requests.exceptions.HTTPError as e:
        return f"❌ 錯誤：API 回傳異常狀態碼 {e.response.status_code}，請檢查 CWA_API_KEY 是否有效。"
    except requests.exceptions.RequestException as e:
        return f"❌ 錯誤：無法連線至 CWA API — {e}"
    except ValueError:
        return "❌ 錯誤：無法解析 CWA API 的回傳資料（非 JSON 格式）。"

    # Navigate the CWA API response structure
    try:
        records = data["records"]
        locations = records.get("location", [])
    except (KeyError, TypeError):
        return f"❌ 錯誤：API 回應格式不符預期，請確認地點名稱「{location_name}」是否正確。"

    if not locations:
        return (
            f"❌ 找不到「{location_name}」的天氣資料。\n"
            "請使用完整縣市名稱，例如：臺北市、新北市、桃園市、臺中市、臺南市、高雄市。"
        )

    location = locations[0]
    weather_elements = {
        elem["elementName"]: elem["time"]
        for elem in location.get("weatherElement", [])
    }

    # Extract the first time period (nearest 12 hours) for each element
    def _first_value(element_name: str) -> str:
        times = weather_elements.get(element_name, [])
        if not times:
            return "N/A"
        return times[0].get("parameter", {}).get("parameterName", "N/A")

    wx = _first_value("Wx")       # Weather phenomenon (天氣現象)
    pop = _first_value("PoP")     # Probability of precipitation (降雨機率)
    min_t = _first_value("MinT")  # Minimum temperature (最低溫)
    max_t = _first_value("MaxT")  # Maximum temperature (最高溫)

    # Grab the time window for context
    first_period = weather_elements.get("Wx", [{}])[0]
    start_time = first_period.get("startTime", "N/A")
    end_time = first_period.get("endTime", "N/A")

    result = (
        f"📍 地點：{location_name}\n"
        f"🕐 預報時段：{start_time} ～ {end_time}\n"
        f"🌤  天氣現象：{wx}\n"
        f"🌧  降雨機率：{pop}%\n"
        f"🌡  溫度範圍：{min_t}°C ～ {max_t}°C"
    )
    return result


# ── Quick smoke-test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    for city in ["台北市", "桃園市", "高雄市"]:
        print(f"[weather_tool] {city}:")
        print(get_weather(city))
        print()
