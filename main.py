import ccxt
import time
import winsound  # 仅适用于 Windows
import traceback
import os
from datetime import datetime
# 增加数据评估相关库
import sqlite3
import pandas as pd
import talib
import logging

# 设置参数
symbol = 'ETH/USDT'
timeframe_15m = '15m'
timeframe_30m = '30m'
fast_period = 5
slow_period = 34
signal_period = 5
ema_period_20 = 20
ema_period_60 = 60
db_path = 'candles_history.db'
alert_trigger_at = 0   # 初始化告警触发时间
alert_period = 5 * 60  # 5分钟

# 初始化交易所
# apikey = "53f63eda-25f8-4822-9d6c-5765fc85174d"
# secretkey = "46FB391FE553BB5F67397F53CC6DFF7D"

# 设置日志打印级别，便于调试
# 设置日志级别（DEBUG 会显示所有信息 INFO  常规信息 WARNING 警告 ERROR 错误 CRITICAL 致命错误 ）
# 控制台处理器（显示 DEBUG 以上）
logger = logging.getLogger('main_logger')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
# 设置日志格式
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.setLevel(logging.DEBUG)

# 手动设置代理
proxies = {
    'http': 'http://127.0.0.1:7890',  # 替换为你的 HTTP 代理地址和端口
    'https': 'http://127.0.0.1:7890'  # 替换为你的 HTTPS 代理地址和端口
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


def play_alert_sound():
    # 播放提示音 (Windows)
    frequency = 2500  # 赫兹
    duration = 1000  # 毫秒
    winsound.Beep(frequency, duration)


def get_max_time(db_path, symbol, time_frame):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(ts) FROM ' + symbol.replace('/', '_') + '_' + time_frame)
        result = cursor.fetchone()[0]
        return result if result is not None else 0


def save_to_sqlite(candles, symbol, time_frame):
    # 连接到 SQLite 数据库（如果不存在则会创建）
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 创建表（如果不存在）
        cursor.execute('''
          CREATE TABLE IF NOT EXISTS ''' + symbol.replace('/', '_') + '_' + time_frame + ''' (
              ts INTEGER,
              open_price TEXT,
              high_price TEXT,
              low_price TEXT,
              close_price TEXT,
              volume TEXT,
              PRIMARY KEY(ts)
          )
        ''')
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        return False

    # 插入数据
    try:
        max_time_1 = get_max_time(db_path, symbol, time_frame)
        logger.debug(
            f"{symbol} {time_frame} 抓取前最新记录: {datetime.fromtimestamp(max_time_1 / 1000).strftime('%Y-%m-%d %H:%M:%S')}")
        cursor.executemany('''
            INSERT OR REPLACE INTO ''' + symbol.replace('/', '_') + '_' + time_frame + '''(ts, open_price, high_price, low_price, close_price, volume)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', candles)
        conn.commit()
    except Exception as e:
        print(f"查询出错: {e}")
        return False

    # 检查数据增量
    try:
        max_time_2 = get_max_time(db_path, symbol, time_frame)
        logger.debug(
            f"{symbol} {time_frame} 抓取后最新记录: {datetime.fromtimestamp(max_time_2 / 1000).strftime('%Y-%m-%d %H:%M:%S')}")
        if max_time_1 < max_time_2:  # 有增量数据，触发评估动作
            cursor.close()
            return True
        else:  # 无增量数据，do nothing  。  修改，无增量数据也需要 进行评估，原因是最新K线必定发生变化，可能影响指标计算。
            cursor.close()
            return None
    except Exception as e:
        print(f"查询出错: {e}")
        cursor.close()
        return False


def load_from_sqlite(symbol, time_frame):
    # 连接到 SQLite 数据库
    try:
        conn = sqlite3.connect(db_path)
        # 从数据库读取增量数据-目前需求-读取400条足够-区间太小会引入指标计算误差-也避免了处理在某些情况下可能存在的周期缺失问题。
        # 以后如果要处理长周期数据，再改造这里，增加使用sql检测数据连续性的语句。
        df = pd.read_sql('''
            SELECT 
                ts AS timestamp,open_price as open,high_price as high, low_price as low, close_price as close, volume
            FROM ''' + symbol.replace('/', '_') + '_' + time_frame + ''' 
            ORDER BY ts desc limit 400
        ''', conn)
        max_ts = df['timestamp'].max()
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        return False
    conn.close()
    # 确保时间序列按日期升序排列
    return df.sort_values('timestamp'),max_ts


# 需求： 出现macd两个及其以上红色空心柱子。
def recently_macd_red_get_shorter_range(macd_height_serize):
    if len(macd_height_serize) < 2:  # 如果序列长度小于2，则不能进行比较
        logger.debug(f"MACD红色空心柱子高度序列长度小于2，序列：{macd_height_serize.iloc[:].tolist()}")
        return 0
    if macd_height_serize.iloc[-1] >= 0:  # <0 才能出现红色柱子
        logger.debug(f"MACD红色空心柱子高度序列最后一根柱子高度{macd_height_serize.iloc[-1]} >= 0，序列最新部分：{macd_height_serize.iloc[ -2:].tolist()}")
        return 0
    else:
        if macd_height_serize.iloc[-1] < macd_height_serize.iloc[-2]:  # 递增才能出现空心柱子，递减跳出返回0
            logger.debug(f"MACD红色空心柱子高度序列最后两根柱子高度{macd_height_serize.iloc[-1]} < {macd_height_serize.iloc[-2]}")
            return 0
        else:
            for i in range(1, len(macd_height_serize), 1):
                if macd_height_serize.iloc[-i] > macd_height_serize.iloc[-i - 1]:
                    pass
                else:  # 返回红色空心柱子的根数
                    logger.debug(f"MACD红色空心柱子高度序列的最小父序列 {macd_height_serize.iloc[-i:].tolist()} 根数：{i - 1}")
                    return i - 1
            logger.debug(
                f"从第二根开始都是红色空心的{macd_height_serize.iloc[:].tolist()} 根数：{len(macd_height_serize)-1}")
            return len(macd_height_serize)-1


# 需求：两个及以上绿色柱子（全实心或者全空心或者一实心一空心）
def recently_macd_green_range(macd_height_serize):
    if len(macd_height_serize) < 2:  # 如果序列长度小于2，则不能进行比较
        logger.debug(f"MACD绿色柱子高度序列长度小于2，序列：{macd_height_serize.iloc[:].tolist()}")
        return 1 if macd_height_serize.iloc[-1] > 0 else 0
    if macd_height_serize.iloc[-1] < 0:  # <0 是红色柱子，不符合需求
        logger.debug(f"MACD柱子高度序列最后一根柱子高度{macd_height_serize.iloc[-1]} < 0，序列最新部分：{macd_height_serize.iloc[-2:].tolist()}")
        return 0
    elif macd_height_serize.iloc[-1] > 0 > macd_height_serize.iloc[-2]:  # >0 是绿色柱子
        logger.debug(f"MACD绿色柱子高度{macd_height_serize.iloc[-1]}，前一根红色柱子高度{macd_height_serize.iloc[-2]}")
        return 1
    else:
        for i in range(1, len(macd_height_serize) + 1, 1):
            if macd_height_serize.iloc[-i] > 0:
                pass
            else:  # 返回绿色柱子的根数
                logger.debug(f"MACD绿色柱子高度序列的最小父序列{macd_height_serize.iloc[-i:].tolist()} 根数：{i - 1}")
                return i - 1
        logger.debug(f"所有柱子都是绿的{macd_height_serize.iloc[:].tolist()} 根数：{len(macd_height_serize)}")
        return len(macd_height_serize)


# 需求：一红一绿（无所谓空心实心）-- 实现为先红后绿
def recently_macd_green_and_elder_red(macd_height_serize):
    if len(macd_height_serize) < 2:  # 如果序列长度小于2，则不能进行比较
        logger.debug(f"MACD红色和绿色柱子高度序列长度小于2，序列：{macd_height_serize.iloc[:].tolist()}")
        return False
    if macd_height_serize.iloc[-1] > 0 > macd_height_serize.iloc[-2]:  # >0 是绿色柱子
        logger.debug(f"MACD绿色柱子高度{macd_height_serize.iloc[-1]}，前一根红色柱子高度{macd_height_serize.iloc[-2]}")
        return True
    else:
        logger.debug(f"MACD高度序列最后两根柱子高度{macd_height_serize.iloc[-2]} {macd_height_serize.iloc[-1]}")
        return False


# 需求：macd出现了第一根红色实心柱子。且这根柱子对应的k线要阴线收盘。
def recently_macd_red_with_candles_red(macd_height_serize, prices_open_serize, prices_close_serize):
    if len(macd_height_serize) < 2 or len(prices_open_serize) < 1 or len(prices_close_serize) < 1:
        logger.debug(f"输入数据异常：macd序列，开盘价格序列，收盘价格序列 {macd_height_serize.iloc[:].tolist()} {prices_open_serize.iloc[:].tolist()} {prices_close_serize.iloc[:].tolist()} ")
        return False  # 数据不足，无法比较
    if (macd_height_serize.iloc[-1] < 0 and macd_height_serize.iloc[-1] < macd_height_serize.iloc[-2]) and \
            prices_open_serize.iloc[-1] > prices_close_serize.iloc[-1]:  # <0 并降序是红色实心柱子
        logger.debug(
            f"MACD序列部分最新数据： {macd_height_serize.iloc[-2:]} ，对应K线开盘价{prices_open_serize.iloc[-1]}，收盘价{prices_close_serize.iloc[-1]}")
        return True
    else:
        logger.debug(
            f"MACD序列部分最新数据： {macd_height_serize.iloc[-2:]} ，对应K线开盘价{prices_open_serize.iloc[-1]}，收盘价{prices_close_serize.iloc[-1]}")
        return False


def chk_current_ema60_greater_than_ema20(ema60, ema20):
    # 这里可以实现对当前EMA60和EMA20的比较逻辑
    # 返回True或False
    if ema60 > ema20:
        logger.debug(f"当前EMA60({ema60})大于EMA20({ema20})")
        return True
    else:
        logger.debug(f"当前EMA60({ema60})不大于EMA20({ema20})")
        return False


def transfrom_data_and_eval(symbol, time_frame):
    df,max_ts = load_from_sqlite(symbol, time_frame)
    df = df.sort_values('timestamp', ascending=True)  # 确保时间序列按日期升序排列

    # 转换数据类型
    prices = {
        'open': df['open'].values.astype(float),
        'high': df['high'].values.astype(float),
        'low': df['low'].values.astype(float),
        'close': df['close'].values.astype(float),
        'volume': df['volume'].values.astype(float)
    }
    # 计算指标
    df['EMA_20'] = talib.EMA(prices['close'], ema_period_20)
    df['EMA_60'] = talib.EMA(prices['close'], ema_period_60)
    df['MACD'], df['MACD_signal'], df['MACD_hist'] = talib.MACD(prices['close'], fastperiod=fast_period,
                                                                slowperiod=slow_period, signalperiod=signal_period)

    # 排除NaN
    df = df.dropna()


    # 不再必要的调试语句
    # logger.debug(f"最近25条K线收盘价格： {prices['close'][-25:].tolist()}")
    # logger.debug(f"最新5根： EMA_60： {df['EMA_60'].iloc[-5:].tolist()} EMA_20：{df['EMA_20'].iloc[-5:].tolist()}")
    # logger.debug(f"最新一条K线的信息： {prices['open'][-1]}  {prices['high'][-1]}  {prices['low'][-1]}  {prices['close'][-1]}")
    logger.debug(
        f"最新数据的上两条（用于验证与网页数据是否一致）： EMA_60： {df['EMA_60'].iloc[-3].tolist()} EMA_20：{df['EMA_20'].iloc[-2].tolist()}")
    logger.debug(
        f"最新数据的上两条（用于验证与网页数据是否一致）： MACD： {df['MACD'].iloc[-3].tolist()}  {df['MACD_signal'].iloc[-2].tolist()}  {df['MACD_hist'].iloc[-2].tolist()}")

    #  前提1、EMA20日线在60日均线下。出现macd两个及其以上红色空心柱子或者两个及以上绿色柱子（全实心或者全空心或者一实心一空心）或者一红一绿（无所谓空心实心）
    if chk_current_ema60_greater_than_ema20(df['EMA_60'].iloc[-1], df['EMA_20'].iloc[-1]) and (
            recently_macd_red_get_shorter_range(df['MACD_hist']) >= 2 or
            recently_macd_green_range(df['MACD_hist']) >= 2 or
            recently_macd_green_and_elder_red(df['MACD_hist'])
    ) and recently_macd_red_with_candles_red:
        logger.warning(f"{symbol} {time_frame} 前提1~3均满足，触发告警准备。")
        return True,max_ts
    else:
        return False,max_ts



# 主循环
condition_1_satisfied = False
while True:
    try:
        # 获取K线数据
        # candles_15m = exchange.fetch_ohlcv(symbol, timeframe_15m, limit=60)

        # print(f"15m K线数据:")
        # for candle in candles_15m:  # 输出太多了，看不过来，存到数据库里，并仅显示数据变化范围。
        #    timestamp, open_price, high_price, low_price, close_price, volume = candle
        #    print (type(candle))
        #    readable_time = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
        #    print(f"  时间: {readable_time}, 开盘价: {open_price}, 最高价: {high_price}, 最低价: {low_price}, 收盘价: {close_price}, 交易量: {volume}")

        # candles_30m = exchange.fetch_ohlcv(symbol, timeframe_30m, limit=60)
        # print(f"30m K线数据:")
        # for candle in candles_30m:
        #    timestamp, open_price, high_price, low_price, close_price, volume = candle
        #    readable_time = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
        #    print(f"  时间: {readable_time}, 开盘价: {open_price}, 最高价: {high_price}, 最低价: {low_price}, 收盘价: {close_price}, 交易量: {volume}")

        # 重构下上面的代码
        for i in (timeframe_15m, timeframe_30m):
            candles = exchange.fetch_ohlcv(symbol, i, limit=1440)
            logger.info(f"保存 {symbol} {i} K线数据:")
            ss = save_to_sqlite(candles, symbol, i)
            if ss in (True, None):  # 测试 None True  ss == True
                # 进行业务处理
                logger.info(f"{symbol} {i} K线数据保存成功，开始评估数据。")
                eval_result,eva_time = transfrom_data_and_eval(symbol, i)
                if eval_result and eva_time > alert_trigger_at:  # 评估结果满足条件，且距离上次告警时间超过5分钟
                    logger.warning(f"{symbol} {i} 条件满足，触发告警。")
                elif eval_result and eva_time <= alert_trigger_at:  # 评估结果满足条件，但此时已经触发过告警
                    logger.info(f"{symbol} {i} 条件满足，但当前已经触发过，跳过告警。")
                elif not eval_result:
                    logger.debug(f"{symbol} {i} 条件不满足，跳过告警。")
                else:
                    logger.error(f"{symbol} {i} 出现逻辑之外的异常，需排查代码，跳过后续处理。")
            elif ss == False:  # 数据库操作失败
                logger.info(f"{symbol} {i} 产生异常，跳过后续处理。")
            else:
                logger.error(f"{symbol} {i} 出现逻辑之外的异常，需排查代码，跳过后续处理。")

        # 检查前提条件 1
        # if not condition_1_satisfied:
        #    condition_1_satisfied = check_condition_1(candles_30m)
        #    if condition_1_satisfied:
        #        print("前提条件 1 已满足")

        # 检查前提条件 2
        # if condition_1_satisfied and check_condition_2(candles_15m):
        #    print("前提条件 2 已满足！")
        #    play_alert_sound()

        # 等待一段时间
        time.sleep(60)  # 每分钟检查一次

    except Exception as e:
        print(f"发生错误: {type(e).__name__}: {e}")
        traceback.print_exc()
        time.sleep(60)