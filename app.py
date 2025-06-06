import streamlit as st
from pathlib import Path

# 從 popo_rank 匯入剛改好的 run_crawler 並支援進度回報
from popo_rank import run_crawler

# 基本頁面設定
st.set_page_config(
    page_title="POPO 排行榜下載器",
    page_icon="📈",
    layout="centered",
)

st.title("POPO 排行榜一鍵下載")

st.markdown(
    "按下 **開始爬取** 會執行爬蟲並在完成後提供下載。\n\n"
    "> *首次啟動約 30–60 秒，請耐心等候。*"
)

# 預留一個區塊隨時更新文字進度
status = st.empty()

if st.button("開始爬取並生成 Excel"):
    with st.spinner("努力爬取中，請稍候……"):
        file_path = run_crawler(progress_callback=status.write)

    st.success("完成！")

    # ✅ 最保險的寫法：確定檔案存在，讀出 bytes 給 download_button
    with open(file_path, "rb") as f:
        st.download_button(
            label="下載 Excel",
            data=f.read(),                      # 讀成 bytes
            file_name=Path(file_path).name,     # 顯示檔名
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )