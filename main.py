import tkinter as tk
import os
from tkinter import ttk, messagebox
import threading
import time
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import ccxt
import winsound  # 仅适用于 Windows
import traceback
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
import talib
import mplfinance as mpf
import logging.handlers

# 全局变量及参数设置
running = False
thread = None
alert_thread = None
stop_event = threading.Event()  # 用于控制线程停止
alert_stop_event = threading.Event()  # 用于控制告警线程停止
symbol = 'ETH/USDT'
timeframe_15m = '15m'
timeframe_30m = '30m'
fast_period = 5
slow_period = 34
signal_period = 5
ema_period_20 = 20
ema_period_60 = 60
db_path = 'candles_history.db'
alert_trigger_at = 0  # 初始化告警触发时间
alert_period = 5 * 60  # 5分钟
debug_alert = True  # 是否开启调试告警 ，正式环境必须关闭 为 False

# 设置日志打印级别，便于调试
# 设置日志级别（DEBUG 会显示所有信息 INFO  常规信息 WARNING 警告 ERROR 错误 CRITICAL 致命错误 ）
# 控制台处理器（显示 DEBUG 以上）
logger = logging.getLogger('main_logger')
logger.setLevel(logging.DEBUG)

log_file = 'eth_monitor.log'
file_formatter = logging.Formatter('【%(asctime)s】 - %(levelname)s - %(message)s',
                                   datefmt='%Y-%m-%d %H:%M:%S')
file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10 * 10 * 1024, backupCount=2,
                                                    encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# 手动设置代理
# proxies = {
#     'http': 'http://127.0.0.1:7897',
#     'https': 'http://127.0.0.1:7897'
# }

# 打印代理信息
# logger.info(f"手动设置的代理: {proxies}")

exchange = None

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


def alert_sound_loop():
    global alert_stop_event
    sound_file = 'alert.wav'
    try:
        winsound.PlaySound(sound_file, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
        pause_button.config(state=tk.NORMAL)
        start_time = time.time()  # 记录开始时间
        while not alert_stop_event.is_set() and time.time() - start_time < 5 * 60:  # 5分钟
            time.sleep(0.1)  # 检查停止事件
        winsound.PlaySound(None, winsound.SND_PURGE)  # 停止播放
        root.after(0, pause_button.config, {"state": tk.DISABLED})  # 禁用按钮
    except Exception as e:
        traceback.print_exc()
    finally:
        # 清理线程资源
        alert_stop_event.clear()
        global alert_thread
        alert_thread = None


def get_max_time(symbol, time_frame):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(ts) FROM ' + symbol.replace('/', '_') + '_' + time_frame)
        result = cursor.fetchone()[0]
        return result if result is not None else 0


def save_to_sqlite(candles, symbol, time_frame):
    try:
        with sqlite3.connect(db_path) as conn:
            # 创建表（如果不存在）
            cursor = conn.cursor()
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
        logger.error(f"Database connection error: {e}")
        return False

    # 插入数据
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            max_time_1 = get_max_time(symbol, time_frame)
            logger.debug(
                f"{symbol} {time_frame} 抓取前最新记录: {datetime.fromtimestamp(max_time_1 / 1000).strftime('%Y-%m-%d %H:%M:%S')}")
            cursor.executemany('''
                INSERT OR REPLACE INTO ''' + symbol.replace('/', '_') + '_' + time_frame + '''(ts, open_price, high_price, low_price, close_price, volume)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', candles)
            conn.commit()
    except Exception as e:
        logger.error(f"查询出错: {e}")
        return False

    # 检查数据增量
    try:
        with sqlite3.connect(db_path) as conn:
            max_time_2 = get_max_time(symbol, time_frame)
            logger.debug(
                f"{symbol} {time_frame} 抓取后最新记录: {datetime.fromtimestamp(max_time_2 / 1000).strftime('%Y-%m-%d %H:%M:%S')}")
            if max_time_1 < max_time_2:  # 有增量数据，触发评估动作
                return True
            else:  # 无增量数据，do nothing  。  修改，无增量数据也需要 进行评估，原因是最新K线必定发生变化，可能影响指标计算。
                return None
    except Exception as e:
        logger.error(f"查询出错: {e}")
        return False


def load_from_sqlite(symbol, time_frame, limit=400):
    # 从数据库读取增量数据-目前需求-读取400条足够-区间太小会引入指标计算误差-也避免了处理在某些情况下可能存在的周期缺失问题。
    # 以后如果要处理长周期数据，再改造这里，增加使用sql检测数据连续性的语句。  增加  offset 1 ，在任何时刻都跳过最近的一条数据，因为该数据还未完全定型。
    try:
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql('''
                SELECT
                    ts AS timestamp,open_price as open,high_price as high, low_price as low, close_price as close, volume
                FROM ''' + symbol.replace('/', '_') + '_' + time_frame + '''
                ORDER BY ts desc limit ''' + str(limit) + ' offset 1', conn)
            max_ts = df['timestamp'].max()
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        return False, None
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df.sort_values('timestamp')
    df = df.set_index('timestamp')
    return df, max_ts


# 需求： 出现macd两个及其以上红色空心柱子。（新需求，不包含自身，在完全完成的K线中进行评估）
def recently_macd_red_get_shorter_range(macd_height_serize):
    if len(macd_height_serize) < 4:  # 如果序列长度小于4，则不能进行比较
        logger.debug(f"MACD序列长度小于4，无法进行比较：{macd_height_serize.iloc[:].tolist()}")
        return 0
    if macd_height_serize.iloc[-2] >= 0:  # <0 才能出现红色柱子，大于0，绿色直接退出
        logger.debug(
            f"MACD已完成序列的最新值的高度{macd_height_serize.iloc[-2]} >= 0，不满足先决条件。序列最新部分：{macd_height_serize.iloc[-2:].tolist()}")
        return 0
    else:
        if macd_height_serize.iloc[-2] < macd_height_serize.iloc[-3]:  # 值递增才能出现空心柱子，递减跳出返回0
            logger.debug(
                f"MACD序列最后两根柱子高度{macd_height_serize.iloc[-2]} < {macd_height_serize.iloc[-3]} ，出现红色实心柱")
            return 0
        else:
            for i in range(2, len(macd_height_serize), 1):
                if macd_height_serize.iloc[-i] > macd_height_serize.iloc[-i - 1]:
                    pass
                else:  # 返回红色空心柱子的根数
                    logger.debug(
                        f"MACD红色空心柱子高度序列的最小父序列 {macd_height_serize.iloc[-i - 1:-2].tolist()} 根数：{i - 2}")
                    return i - 2
            logger.debug(
                f"从第二根开始都是红色空心的{macd_height_serize.iloc[:-2].tolist()} 根数：{len(macd_height_serize) - 2}")
            return len(macd_height_serize) - 2


# 需求：两个及以上绿色柱子（全实心或者全空心或者一实心一空心）。（新需求，不包含自身，在完全完成的K线中进行评估）
def recently_macd_green_range(macd_height_serize):
    if len(macd_height_serize) < 3:  # 如果序列长度小于3，则不能进行比较
        logger.debug(f"MACD序列长度小于3，无法进行比较：{macd_height_serize.iloc[:].tolist()}")
        return 1 if macd_height_serize.iloc[-1] > 0 else 0
    if macd_height_serize.iloc[-2] < 0:  # <0 是红色柱子，不符合需求
        logger.debug(
            f"MACD柱子高度序列最后第二根柱子高度{macd_height_serize.iloc[-2]} < 0，不符合需求。序列最新部分：{macd_height_serize.iloc[-3:].tolist()}。出现红柱")
        return 0
    elif macd_height_serize.iloc[-2] > 0 > macd_height_serize.iloc[-3]:  # >0 是绿色柱子
        logger.debug(f"MACD绿色柱子高度{macd_height_serize.iloc[-2]}，前一根红色柱子高度{macd_height_serize.iloc[-3]}")
        return 1
    else:
        for i in range(2, len(macd_height_serize) + 1, 1):
            if macd_height_serize.iloc[-i] > 0:
                pass
            else:  # 返回绿色柱子的根数
                logger.debug(f"MACD绿色柱子高度序列的最小父序列{macd_height_serize.iloc[-i:-2].tolist()} 根数：{i - 2}")
                return i - 2
        logger.debug(f"所有柱子都是绿的{macd_height_serize.iloc[:-1].tolist()} 根数：{len(macd_height_serize) - 1}")
        return len(macd_height_serize) - 1


# 需求：一红一绿（无所谓空心实心）-- 实现为先红后绿。（新需求，不包含自身，在完全完成的K线中进行评估）
def recently_macd_green_and_elder_red(macd_height_serize):
    if len(macd_height_serize) < 3:  # 如果序列长度小于3，则不能进行比较
        logger.debug(f"MACD红色和绿色柱子高度序列长度小于3，无法进行比较。序列：{macd_height_serize.iloc[:].tolist()}")
        return False
    if macd_height_serize.iloc[-2] > 0 > macd_height_serize.iloc[-3]:  # >0 是绿色柱子
        logger.debug(f"MACD绿色柱子高度{macd_height_serize.iloc[-2]}，前一根红色柱子高度{macd_height_serize.iloc[-3]}")
        return True
    else:
        logger.debug(
            f"MACD高度序列最后两根柱子高度{macd_height_serize.iloc[-3]} {macd_height_serize.iloc[-2]} ，未出现先红后绿")
        return False


# 需求：macd出现了第一根红色实心柱子。且这根柱子对应的k线要阴线收盘。
def recently_macd_red_with_candles_red(macd_height_serize, prices_open_serize, prices_close_serize):
    if len(macd_height_serize) < 2 or len(prices_open_serize) < 1 or len(prices_close_serize) < 1:
        logger.debug(
            f"输入数据异常：macd序列，开盘价格序列，收盘价格序列 {macd_height_serize.iloc[:].tolist()} {prices_open_serize.iloc[:].tolist()} {prices_close_serize.iloc[:].tolist()} ")
        return False  # 数据不足，无法比较
    if (macd_height_serize.iloc[-1] < 0 and macd_height_serize.iloc[-1] < macd_height_serize.iloc[-2]) and \
            prices_open_serize.iloc[-1] > prices_close_serize.iloc[-1]:  # <0 并降序是红色实心柱子
        logger.debug(
            f"MACD序列部分最新数据： {macd_height_serize.iloc[-2:].tolist()} ，对应K线开盘价{prices_open_serize.iloc[-1]}，收盘价{prices_close_serize.iloc[-1]}")
        return True
    else:
        logger.debug(
            f"MACD序列部分最新数据： {macd_height_serize.iloc[-2:].tolist()} ，对应K线开盘价{prices_open_serize.iloc[-1]}，收盘价{prices_close_serize.iloc[-1]}，未满足条件。")
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
    df, max_ts = load_from_sqlite(symbol, time_frame)
    if df is False:
        return False, max_ts
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
    logger.debug(
        f"最新数据的上两条（用于验证与网页数据是否一致）： EMA_60： {df['EMA_60'].iloc[-3].tolist()} EMA_20：{df['EMA_20'].iloc[-2].tolist()}")
    logger.debug(
        f"最新数据的上两条（用于验证与网页数据是否一致）： MACD： {df['MACD'].iloc[-3].tolist()}  {df['MACD_signal'].iloc[-2].tolist()}  {df['MACD_hist'].iloc[-2].tolist()}")

    #  前提1、EMA20日线在60日均线下。出现macd两个及其以上红色空心柱子或者两个及以上绿色柱子（全实心或者全空心或者一实心一空心）或者一红一绿（无所谓空心实心）
    if chk_current_ema60_greater_than_ema20(df['EMA_60'].iloc[-1], df['EMA_20'].iloc[-1]) and (
            recently_macd_red_get_shorter_range(df['MACD_hist']) >= 2 or
            recently_macd_green_range(df['MACD_hist']) >= 2 or
            recently_macd_green_and_elder_red(df['MACD_hist'])
    ) and recently_macd_red_with_candles_red(df['MACD_hist'], df['open'], df['close']):
        logger.warning(f"{symbol} {time_frame} 前提1~3均满足，触发告警准备。")
        return True, max_ts
    else:
        return False, max_ts


def main_loop():
    global running, alert_trigger_at, alert_thread, exchange
    if running and not stop_event.is_set():
        try:
            for i in (timeframe_15m, timeframe_30m):
                candles = exchange.fetch_ohlcv(symbol, i, limit=1440)
                logger.info(f"保存 {symbol} {i} K线数据:")
                ss = save_to_sqlite(candles, symbol, i)
                if ss in (True, None):
                    logger.info(f"{symbol} {i} K线数据保存成功，开始评估数据。")
                    eval_result, eva_time = transfrom_data_and_eval(symbol, i)
                    if (eval_result and eva_time > alert_trigger_at):
                        if alert_thread and alert_thread.is_alive():
                            logger.info(f"告警线程已在运行中，跳过重复触发。")
                        else:
                            logger.info(f"{symbol} {i} 条件满足，触发告警。")
                            alert_trigger_at = eva_time
                            alert_stop_event.clear()
                            alert_thread = threading.Thread(target=alert_sound_loop, daemon=True)
                            alert_thread.start()
                    elif eval_result and eva_time <= alert_trigger_at:
                        logger.info(f"{symbol} {i} 条件满足，但当前已经触发过，跳过告警。")
                    elif not eval_result:
                        logger.debug(f"{symbol} {i} 条件不满足，跳过告警。")
                    else:
                        logger.error(f"{symbol} {i} 出现逻辑之外的异常，需排查代码，跳过后续处理。")
                elif ss == False:
                    logger.info(f"{symbol} {i} 产生异常，跳过后续处理。")
                else:
                    logger.error(f"{symbol} {i} 出现逻辑之外的异常，需排查代码，跳过后续处理。")

            # update_plot()  # 更新图表

        except Exception as e:
            logger.error(f"发生错误: {type(e).__name__}: {e}")
            traceback.print_exc()

        # main_loop 不再使用 time.sleep 阻塞主线程，而是通过 root.after 每 60 秒触发一次数据查询和评估。
        # 点击停止程序时，可以立即停止 main_loop 的循环调用，从而避免界面卡死。
        root.after(60000, lambda: main_loop())  # 60秒后再次调用 main_loop


def start_stop_program():
    # 日期校验：超过 2025-06-04 不允许启动
    now = datetime.now()
    target_date = datetime(2025, 7, 9, 0, 0, 0)
    if now > target_date:
        messagebox.showerror("启动失败", "当前试用版本截止日期2025年7月9日，试用已过期")
        logger.info("启动失败：当前试用版本截止日期2025年7月9日，试用已过期")
        return
    global running, thread, exchange
    if running:
        # 如果程序正在运行，则停止程序
        running = False
        stop_event.set()  # 设置停止事件
        pause_alert()
        status_label.config(text="程序已停止")
        start_stop_button.config(text="启动程序")  # 更改按钮文本

    else:
        # 如果程序未运行，则启动程序
        running = True
        stop_event.clear()  # 清除停止事件

        # 获取代理端口
        proxy_port = proxy_entry.get()

        # 构造完整的代理 URL
        http_proxy = f'http://127.0.0.1:{proxy_port}'
        https_proxy = f'http://127.0.0.1:{proxy_port}'

        # 构造代理字典
        proxies = {
            'http': http_proxy,
            'https': https_proxy
        }

        # 打印代理信息
        logger.info(f"手动设置的代理: {proxies}")

        # 初始化 exchange 对象
        global exchange
        exchange = ccxt.okx({
            'proxies': proxies,
        })

        thread = threading.Thread(target=lambda: main_loop())
        thread.start()
        status_label.config(text="程序运行中...")
        start_stop_button.config(text="停止程序")  # 更改按钮文本


def pause_alert():
    global alert_thread, alert_stop_event
    if alert_thread and alert_thread.is_alive():
        alert_stop_event.set()  # 设置告警停止事件
        winsound.PlaySound(None, winsound.SND_PURGE)
        pause_button.config(state=tk.DISABLED)
        logger.info("告警已暂停。")
    else:
        logger.info("没有正在运行的告警线程，无法暂停。")


def update_plot():
    try:
        # 获取最近4小时的数据 (假设 timeframe_15m 是 15 分钟)
        df, _ = load_from_sqlite(symbol, timeframe_15m, limit=4 * 16)  # 4 小时 = 16 个 15 分钟周期
        if df is False:
            logger.error("无法从数据库加载数据，跳过图表更新。")
            return

        # 确保数据按时间戳排序
        df = df.sort_index()

        # 转换数据类型
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')  # 将无法转换为数字的值替换为 NaN
        df = df.dropna()  # 删除包含 NaN 的行

        # 确保时间戳是datetime类型, 并转换为北京时间
        if df.index.dtype == 'int64':
            df.index = pd.to_datetime(df.index, unit='ms').tz_localize('UTC').tz_convert('Asia/Shanghai')
        else:
            df.index = df.index.tz_localize('UTC').tz_convert('Asia/Shanghai')

        # 获取当前时间
        now = pd.Timestamp.now(tz='Asia/Shanghai')

        # 设定要显示的时间范围（例如，最近4小时）
        four_hours_ago = now - pd.Timedelta(hours=4)

        # 筛选时间范围内的数据
        df = df[df.index >= four_hours_ago]

        # 定义 K 线颜色
        mc = mpf.make_marketcolors(up='green', down='red', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc)

        # 清空之前的图表
        ax.clear()

        # 绘制 K 线图
        mpf.plot(df, type='candle', ax=ax, volume=False, style=s)

        # 自动调整 x 轴刻度以适应数据
        ax.tick_params(axis='x', rotation=45)
        fig.canvas.draw()

        # 将 Matplotlib 图表嵌入到 Tkinter 窗口
        canvas.figure = fig
        canvas.draw()

    except Exception as e:
        logger.error(f"更新图表时发生错误: {type(e).__name__}: {e}")
        traceback.print_exc()


# 创建主窗口
root = tk.Tk()
root.title("ETH/USDT 交易监控程序")

proxy_entry = tk.Entry(root, width=6)
proxy_entry.pack(padx=5, pady=5, anchor='w')

# 创建按钮
start_stop_button = ttk.Button(root, text="启动程序", command=lambda: start_stop_program())
pause_button = ttk.Button(root, text="暂停本次告警", command=pause_alert, state=tk.DISABLED)  # 初始状态禁用

# 状态标签
status_label = tk.Label(root, text="程序未运行")

# 创建 Text 组件用于显示日志
log_text = tk.Text(root, height=10)


class TextHandler(logging.Handler):
    def __init__(self, text, max_lines=1000):
        super().__init__()
        self.text = text
        self.max_lines = max_lines

    def emit(self, record):
        msg = self.format(record)
        self.text.insert(tk.END, msg + '\n')
        self.text.see(tk.END)  # 自动滚动到底部
        self.trim_log()  # 限制日志行数

    def trim_log(self):
        line_count = int(self.text.index('end - 1 line').split('.')[0])
        if line_count > self.max_lines:
            self.text.delete('1.0', f'{line_count - self.max_lines}.0')


# 创建 TextHandler 并添加到 logger
console_formatter = logging.Formatter('【%(asctime)s】 - %(levelname)s - %(message)s',
                                      datefmt='%Y-%m-%d %H:%M:%S')
text_handler = TextHandler(log_text, max_lines=1000)
text_handler.setLevel(logging.INFO)  # 设置为 INFO 级别
text_handler.setFormatter(console_formatter)
logger.addHandler(text_handler)

# 创建图表
fig, ax = plt.subplots(figsize=(10, 4))
canvas = FigureCanvasTkAgg(fig, master=root)
canvas_widget = canvas.get_tk_widget()


# 定义关闭窗口时的处理函数
def on_closing():
    global running, thread, alert_thread
    running = False
    stop_event.set()  # 设置停止事件
    alert_stop_event.set()  # 设置告警停止事件
    pause_alert()  # 确保停止告警声音
    if thread and thread.is_alive():
        thread.join()  # 等待主循环线程结束
    root.quit()
    os._exit(0)

# 布局
start_stop_button.pack(pady=5)
pause_button.pack(pady=5)
status_label.pack(pady=5)
log_text.pack(pady=5, fill=tk.X)
# canvas_widget.pack(pady=10)

root.protocol("WM_DELETE_WINDOW", lambda: on_closing())

# 启动主循环
root.mainloop()