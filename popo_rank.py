"""
POPO 排行榜爬蟲  ‑ 使用 Selenium Manager 自動下載 chromedriver
-----------------------------------------------------------------
• 改為 **完全依賴 Selenium 4.20+ 內建的 driver manager**：
  不再手動指定 chromedriver 路徑，也不需要 `chromium-driver` 套件。
• 仍自動偵測 Chromium binary 路徑，避免 NoSuchDriverException。
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Dict, List

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# -----------------------------------------------------------------------------
# 共用工具
# -----------------------------------------------------------------------------

CHROME_CANDIDATES: List[str] = [
    "/usr/bin/chromium",  # Debian 常見 wrapper
    "/usr/bin/chromium-browser",  # 舊命名
    "/usr/lib/chromium/chromium",  # 實際 ELF
]


def _find_chrome_binary() -> str:
    for p in CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    raise FileNotFoundError("找不到 Chromium，請確認 packages.txt 已安裝 chromium")


def _default_logger(msg: str) -> None:
    print(msg)


# -----------------------------------------------------------------------------
# Selenium Driver
# -----------------------------------------------------------------------------

def _create_driver() -> webdriver.Chrome:
    opts = Options()
    opts.binary_location = _find_chrome_binary()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")

    # 交給 Selenium Manager 自動下載並匹配版本
    return webdriver.Chrome(options=opts)


# -----------------------------------------------------------------------------
# 解析單本書詳情
# -----------------------------------------------------------------------------

def get_book_detail(driver: webdriver.Chrome, book_url: str) -> Dict[str, str]:
    driver.get(book_url)
    time.sleep(2)

    # 自動通過 18 禁頁面
    if "/limit18" in driver.current_url or "我已滿18歲" in driver.page_source:
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "a.R-yes"))
            ).click()
            time.sleep(2)
        except Exception as e:
            print(f"[警告] 18 禁驗證自動點擊失敗：{e}")

    soup = BeautifulSoup(driver.page_source, "html.parser")
    tables = soup.find_all("table", class_="book_data")

    detail: Dict[str, str] = {}
    for table in tables:
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th and td:
                detail[th.text.strip()] = td.text.strip()

    return {
        "免費章回": detail.get("免費章回", ""),
        "付費章回": detail.get("付費章回", ""),
        "總字數": detail.get("總字數", ""),
        "收藏數": detail.get("收藏數", ""),
        "訂購數": detail.get("訂購數", ""),
    }


# -----------------------------------------------------------------------------
# 切換榜單 / 週期輔助
# -----------------------------------------------------------------------------

def switch_board_and_category(driver: webdriver.Chrome, kind: str, sub: str) -> None:
    driver.get("https://www.popo.tw/rank/more")
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "rank-form1")))
    time.sleep(1)
    js = f"""
    document.getElementById('kind').value ='{kind}';
    document.getElementById('sub').value ='{sub}';
    document.getElementById('rank-form1').submit();
    """
    driver.execute_script(js)
    time.sleep(2)


def switch_rank(driver: webdriver.Chrome, period: str = "weekly") -> None:
    js = f"""
    document.getElementById('type').value='{period}';
    document.getElementById('rank-form1').submit();
    """
    driver.execute_script(js)
    time.sleep(2)


# -----------------------------------------------------------------------------
# 爬取單張榜單
# -----------------------------------------------------------------------------

def crawl_board(
    driver: webdriver.Chrome,
    kind: str,
    kind_name: str,
    sub: str,
    sub_name: str,
    period: str,
    period_name: str,
    logger: Callable[[str], None],
) -> pd.DataFrame:
    # 切榜 + 切週期
    switch_board_and_category(driver, kind, sub)
    switch_rank(driver, period)

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "table-rwd"))
    )
    soup = BeautifulSoup(driver.page_source, "html.parser")
    table = soup.find("table", class_="table-rwd")
    rows = table.find("tbody").find_all("tr")

    data: List[Dict[str, str]] = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) == 7:
            book_link = cols[2].find("a", class_="bname")["href"]
            book_url = "https://www.popo.tw" + book_link
            base_info = {
                "排行": cols[0].text.strip(),
                "類別": cols[1].text.strip(),
                "書名": cols[2].text.strip(),
                "書籍連結": book_url,
                "最新章回": cols[3].text.strip(),
                "作者": cols[4].text.strip(),
                "公開時間": cols[5].text.strip(),
                "書籍狀態": cols[6].text.strip(),
                "榜單": kind_name,
                "分類": sub_name,
                "週期": period_name,
            }
            detail_info = get_book_detail(driver, book_url)
            base_info.update(detail_info)
            data.append(base_info)
            logger(f"✔ 已完成：{base_info['書名']} ({kind_name}-{sub_name}-{period_name})")

    return pd.DataFrame(data)


# -----------------------------------------------------------------------------
# 對外主要入口 ── run_crawler()
# -----------------------------------------------------------------------------

def run_crawler(progress_callback: Optional[Callable[[str], None]] = None) -> str:
    """執行完整爬蟲，並將過程訊息透過 callback 傳遞。"""

    logger = progress_callback or _default_logger

    # ----------- 基本參數 -----------
    kinds = [("hits", "人氣榜"), ("bestsale", "訂購榜"), ("pearl", "珍珠榜")]
    categories = [("1", "愛情文藝"), ("2", "耽美"), ("10", "百合")]
    periods = [("weekly", "週榜"), ("monthly", "月榜")]

    dfs: Dict[str, pd.DataFrame] = {}

    for kind, kind_name in kinds:
        for sub, sub_name in categories:
            for period, period_name in periods:
                sheet_name = f"{kind_name}-{sub_name}-{period_name}"
                logger(f"▶ 開始爬取：{sheet_name}")

                driver = _create_driver()
                try:
                    df = crawl_board(
                        driver, kind, kind_name, sub, sub_name, period, period_name, logger
                    )
                    dfs[sheet_name] = df
                finally:
                    driver.quit()

    # ----------- 輸出 Excel -----------
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"popo_排行榜_{today}.xlsx"
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        for sheet, df in dfs.items():
            df.to_excel(writer, sheet_name=sheet[:31], index=False)

    logger(f"🎉 已完成並儲存：{filename}")
    return filename


# -----------------------------------------------------------------------------
# CLI 執行
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    run_crawler()
