import streamlit as st
import yfinance as yf
import requests
import sqlite3
import bcrypt
import logging
import time

# 初始化 SQLite 資料庫
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()

# 建立 users 資料表（如果不存在）
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        security_question TEXT NOT NULL,
        security_answer TEXT NOT NULL
    )
""")

# 建立 user_stocks 資料表（每位用戶的股票關注）
cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_stocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        stock_code TEXT NOT NULL,
        target_price REAL NOT NULL,
        FOREIGN KEY(username) REFERENCES users(username)
    )
""")
conn.commit()

# 初始化 session_state
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "stocks" not in st.session_state:
    st.session_state.stocks = []

if "page" not in st.session_state:
    st.session_state.page = "login"

if "monitoring" not in st.session_state:
    st.session_state.monitoring = False  # 監控狀態

if "sent_notifications" not in st.session_state:
    st.session_state.sent_notifications = set()  # 用來紀錄已發送通知的股票代號


# LINE Notify 的 Access Token（多個 Token）
LINE_NOTIFY_TOKENS = [
    'B0xvaogQPZwDrtouPPvsERhADsAV6HfU9hZDsGy6ypw',  # 你的 Token
    'Z9rF1jjSo39BcuJ1ucJkfmULWTSih6nZRWMs2jDjcpe',  # 爸爸的 Token
]


# 密碼加密函數
def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


# 驗證密碼
def check_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())


# 登入驗證
def login_user(username, password):
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password(password, user[0]):
        return True
    return False


# 取得用戶股票清單
def load_user_stocks(username):
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT stock_code, target_price FROM user_stocks WHERE username = ?", (username,))
    stocks = [{"code": row[0], "price": row[1]} for row in cursor.fetchall()]
    conn.close()
    return stocks


# 儲存股票
def save_user_stocks(username, stocks):
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_stocks WHERE username = ?", (username,))
    for stock in stocks:
        cursor.execute("INSERT INTO user_stocks (username, stock_code, target_price) VALUES (?, ?, ?)",
                       (username, stock["code"], stock["price"]))
    conn.commit()
    conn.close()


# 發送 LINE 通知
def send_line_notify(message):
    url = 'https://notify-api.line.me/api/notify'
    for token in LINE_NOTIFY_TOKENS:
        headers = {'Authorization': f'Bearer {token}'}
        payload = {'message': message}
        try:
            requests.post(url, headers=headers, data=payload)
            logging.info("LINE 通知發送成功！")
        except requests.exceptions.RequestException as e:
            logging.error(f"發送 LINE 通知失敗: {e}")


# 取得股價
def get_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period='1d', interval='1m')
        if data.empty:
            return None
        return data['Close'].iloc[-1]
    except Exception as e:
        logging.error(f"{ticker} 獲取股價失敗: {e}")
        return None


# 檢查股價並發送通知
def check_stock_prices():
    for stock in st.session_state.stocks:
        ticker, target_price = stock['code'], stock['price']

        # 檢查是否已通知
        if ticker in st.session_state.sent_notifications:
            continue

        current_price = get_stock_price(ticker)
        if current_price is None:
            st.error(f"{ticker} 無法獲取股價")
            continue

        st.write(f"{ticker} 當前股價: {current_price} 元")

        if current_price >= target_price:
            send_line_notify(f"📢 {ticker} 股價達標！目前價格：{current_price} 元")
            st.success(f"已通知 {ticker} 達標！")
            st.session_state.sent_notifications.add(ticker)


# **登入頁面**
def login_page():
    st.title("🔐 登入股票監控系統")

    username = st.text_input("帳號")
    password = st.text_input("密碼", type="password")

    col1, col2 = st.columns(2)
    if col1.button("🔐 登入"):
        if login_user(username, password):
            st.session_state.logged_in = True
            st.session_state.username = username
            st.session_state.page = "monitoring"
            st.experimental_rerun()  # 重新整理頁面
        else:
            st.error("帳號或密碼錯誤")

    if col2.button("📝 註冊新帳號"):
        st.session_state.page = "register"
        st.experimental_rerun()


# **股票監控系統**
def stock_monitoring():
    st.title("📈 股票監控系統")
    st.write(f"👋 歡迎，{st.session_state.username}")

    # **載入股票**
    if not st.session_state.stocks:
        st.session_state.stocks = load_user_stocks(st.session_state.username)

    # **股票輸入與刪除功能**
    stocks_to_remove = []
    for i, stock in enumerate(st.session_state.stocks):
        col1, col2, col3 = st.columns([3, 2, 1])
        stock["code"] = col1.text_input(f"股票代號 {i + 1}", stock["code"], key=f"code_{i}")
        stock["price"] = col2.number_input(f"目標股價 {i + 1}", min_value=0.0, value=stock["price"], format="%.2f",
                                           key=f"price_{i}")

        if col3.button("❌ 刪除", key=f"delete_{i}"):
            stocks_to_remove.append(i)

    for i in sorted(stocks_to_remove, reverse=True):
        del st.session_state.stocks[i]

    # **新增股票按鈕**
    if st.button("➕ 新增股票"):
        st.session_state.stocks.append({"code": "", "price": 0.0})

    # **儲存股票**
    if st.button("💾 儲存股票"):
        save_user_stocks(st.session_state.username, st.session_state.stocks)
        st.success("股票已儲存！")

    # **監控區域**
    monitoring_placeholder = st.empty()
    stop_monitoring_button = st.empty()  # 保留「停止監控」按鈕
    logout_button = st.sidebar.button("🚪 登出")  # **讓登出鍵一直可見**

    if st.button("🔍 開始監控"):
        st.session_state.monitoring = True

    if st.session_state.monitoring:
        with monitoring_placeholder.container():
            st.write("🔍 正在監控所有股票的股價...")

        while st.session_state.monitoring:
            check_stock_prices()
            time.sleep(60)  # **改成 60 秒，避免 UI 長時間卡住**
            monitoring_placeholder.write("🔍 持續監控中...")

            # **提供停止監控的按鈕**
            if stop_monitoring_button.button("⏹ 停止監控"):
                st.session_state.monitoring = False
                st.experimental_rerun()

    # **登出按鈕（側邊欄）**
    if logout_button:
        st.session_state.logged_in = False
        st.session_state.page = "login"
        st.session_state.stocks = []
        st.experimental_rerun()

# **主程式**
def main():
    if st.session_state.page == "login":
        login_page()
    elif st.session_state.page == "monitoring" and st.session_state.logged_in:
        stock_monitoring()
    elif st.session_state.page == "register":
        register_page()
    else:
        st.session_state.page = "login"

if __name__ == "__main__":
    main()
