"""IPO Radar 仪表盘 - Streamlit应用入口。"""

import streamlit as st


def main():
    st.set_page_config(page_title="IPO Radar", page_icon="📡", layout="wide")
    st.title("IPO Radar - IPO决策信息系统")

    tabs = st.tabs(["新股监控", "基本面筛选", "形态识别", "禁售期", "情绪分析", "业绩追踪", "综合评分"])

    with tabs[0]:
        st.header("新股监控")
        st.info("即将上市和近期上市的IPO列表")

    with tabs[1]:
        st.header("基本面筛选")
        st.info("基于财务指标筛选IPO标的")

    with tabs[2]:
        st.header("形态识别")
        st.info("IPO股票价格和成交量形态")

    with tabs[3]:
        st.header("禁售期跟踪")
        st.info("内部人士和机构禁售期到期日")

    with tabs[4]:
        st.header("情绪分析")
        st.info("市场对IPO的情绪倾向")

    with tabs[5]:
        st.header("业绩追踪")
        st.info("IPO公司上市后财务表现")

    with tabs[6]:
        st.header("综合评分")
        st.info("多维度综合评估IPO投资价值")


if __name__ == "__main__":
    main()
