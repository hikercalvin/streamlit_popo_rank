"""
POPO 排行榜爬蟲  ‑ 免 webdriver‑manager 版
------------------------------------------------
• 改用 **系統內建的 chromium‑driver**，完全不依賴 webdriver‑manager，
  避免 import/版本不相容問題。
• 仍保留 `progress_callback` 供 Streamlit 即時回報。
• 其餘核心邏輯（切榜、解析、存檔）維持不變。
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
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Debian 11 (bullseye) 安裝 chromium-driver 後的預設路徑
CHROMEDRIVER_PATH = "/usr/lib/chromium/chromedriver"
CHROMIUM_BINARY = "/usr/bin/chromium"

# -----------------------------------------------------------------------------
# 共用工具
# -----------------------------------------------------------------------------

def _default_logger(msg: str) -> None:
    print(msg)


def _create_driver() -> webdriver.Chrome:
    """建立 headless Chromium，雲端/本地皆可用。"""
    opts = Options()
    opts.binary_location = CHROMIUM_BINARY  # ★ 指定雲端 chromium
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    return webdriver.Chrome(
        service=Service(CHROMEDRIVER_PATH),
        options=opts,
    )

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
            base_info.update(get_book_detail(driver, book_url))
            data.append(base_info)
            logger(f"✔ 已完成：{base_info['書名']} ({kind_name}-{sub_name}-{period_name})")

    return pd.DataFrame(data)

# -----------------------------------------------------------------------------
# 對外主要入口
# -----------------------------------------------------------------------------

def run_crawler(progress_callback: Optional[Callable[[str], None]] = None) -> str:
    logger = progress_callback or _default_logger

    kinds = [("hits", "人氣榜"), ("bestsale", "訂購榜"), ("pearl", "珍珠榜")]
    categories = [("1", "愛情文藝"), ("2", "耽美"), ("10", "百合")]
    periods = [("weekly", "週榜"), ("monthly", "月榜")]

    dfs: Dict[str, pd.DataFrame] = {}

    for kind, kind_name in kinds:
        for sub, sub_name in categories:
            for period, period_name in periods:
                sheet = f"{kind_name}-{sub_name}-{period_name}"
                logger(f"▶ 開始爬取：{sheet}")

                driver = _create_driver()
                try:
                    df = crawl_board(driver, kind, kind_name, sub, sub_name, period, period_name, logger)
                    dfs[sheet] = df
                finally:
                    driver.quit()

    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"popo_排行榜_{today}.xlsx"
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        for sheet, df in dfs.items():
            df.to_excel(writer, sheet_name=sheet[:31], index=False)

    logger(f"🎉 已完成並儲存：{filename}")
    return filename

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    run_crawler()
