import ccxt
import time
import winsound  # 仅适用于 Windows
import traceback
import threading
from datetime import datetime

# 设置参数
symbol = 'ETH/USDT'
timeframe_15m = '15m'
timeframe_30m = '30m'
fast_period = 5
slow_period = 34
signal_period = 5
ema_period_20 = 20
ema_period_60 = 60

# 初始化交易所
# apikey = "53f63eda-25f8-4822-9d6c-5765fc85174d"
# secretkey = "46FB391FE553BB5F67397F53CC6DFF7D"

# 手动设置代理
proxies = {
    'http': 'http://127.0.0.1:7897',  # 替换为你的 HTTP 代理地址和端口
    'https': 'http://127.0.0.1:7897'  # 替换为你的 HTTPS 代理地址和端口
}

# 打印代理信息
print(f"手动设置的代理: {proxies}")

exchange = ccxt.okx({
#    'apiKey': apikey,
#    'secret': secretkey,
    'proxies': proxies,
})

def calculate_ema(data, period):
    ema = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        ema.append((data[i] * 2 + ema[-1] * (period - 1)) / (period + 1))
    return ema

def calculate_macd(data, fast_period, slow_period, signal_period):
    ema_fast = calculate_ema(data, fast_period)
    ema_slow = calculate_ema(data, slow_period)
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_fast))]
    signal_line = calculate_ema(macd_line, signal_period)
    histogram = [macd_line[i] - signal_line[i] for i in range(len(signal_line))]
    return macd_line, signal_line, histogram

def check_condition_1(candles_30m):
    # 获取收盘价
    close_prices = [candle[4] for candle in candles_30m]

    # 计算 EMA
    ema_20 = calculate_ema(close_prices, ema_period_20)
    ema_60 = calculate_ema(close_prices, ema_period_60)

    # 检查 EMA20 是否在 EMA60 下方
    if ema_20[-1] > ema_60[-1]:
        return False

    # 计算 MACD
    macd_line, signal_line, histogram = calculate_macd(close_prices, fast_period, slow_period, signal_period)

    # 检查 MACD 柱子
    last_histogram_values = histogram[-2:]  # 获取最后两个柱子的值
    if (last_histogram_values[0] > 0 and last_histogram_values[1] > 0) or \
       (last_histogram_values[0] < 0 and last_histogram_values[1] < 0) or \
       (last_histogram_values[0] > 0 and last_histogram_values[1] < 0):
        return True
    else:
        return False

def check_condition_2(candles_15m):
    # 获取收盘价和开盘价
    close_prices = [candle[4] for candle in candles_15m]
    open_prices = [candle[1] for candle in candles_15m]

    # 计算 MACD
    macd_line, signal_line, histogram = calculate_macd(close_prices, fast_period, slow_period, signal_period)

    # 检查 MACD 柱子是否为红色实心
    if histogram[-1] < 0 and close_prices[-1] < open_prices[-1]:
        return True
    else:
        return False

def play_alert_sound(duration=300):
    # 播放提示音 (Windows)
    sound_file = 'alert.wav'  # 替换为你的MP3文件名
    try:
        # 异步循环播放声音
        winsound.PlaySound(sound_file, winsound.SND_FILENAME | winsound.SND_LOOP | winsound.SND_ASYNC)
        time.sleep(duration)  # 播放指定时长
        winsound.PlaySound(None, winsound.SND_PURGE)  # 停止播放
    except Exception as e:
        print(f"播放声音文件时发生错误: {e}")
        traceback.print_exc()  # 打印错误堆栈信息

# 主循环
condition_1_satisfied = False
while True:
    try:
        threading.Thread(target=play_alert_sound).start()
        # 获取K线数据
        candles_15m = exchange.fetch_ohlcv(symbol, timeframe_15m, limit=60)
        print(f"15m K线数据:")
        for candle in candles_15m:
            timestamp, open_price, high_price, low_price, close_price, volume = candle
            readable_time = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
            print(f"  时间: {readable_time}, 开盘价: {open_price}, 最高价: {high_price}, 最低价: {low_price}, 收盘价: {close_price}, 交易量: {volume}")

        candles_30m = exchange.fetch_ohlcv(symbol, timeframe_30m, limit=60)
        print(f"30m K线数据:")
        for candle in candles_30m:
            timestamp, open_price, high_price, low_price, close_price, volume = candle
            readable_time = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
            print(f"  时间: {readable_time}, 开盘价: {open_price}, 最高价: {high_price}, 最低价: {low_price}, 收盘价: {close_price}, 交易量: {volume}")

        # 检查前提条件 1
        if not condition_1_satisfied:
            condition_1_satisfied = check_condition_1(candles_30m)
            if condition_1_satisfied:
                print("前提条件 1 已满足")

        # 检查前提条件 2
        if condition_1_satisfied and check_condition_2(candles_15m):
            print("前提条件 2 已满足！")
            threading.Thread(target=play_alert_sound).start()

        # 等待一段时间
        time.sleep(60)  # 每分钟检查一次

    except Exception as e:
        print(f"发生错误: {type(e).__name__}: {e}")
        traceback.print_exc()
        time.sleep(60)