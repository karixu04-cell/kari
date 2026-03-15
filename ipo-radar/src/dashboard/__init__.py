"""仪表盘模块 - Dashboard: Streamlit-based interactive dashboard."""


class Dashboard:
    """Streamlit dashboard for the IPO Radar system."""

    def __init__(self, title: str = "IPO Radar Dashboard"):
        self.title = title

    def run(self):
        """Launch the Streamlit dashboard."""
        raise NotImplementedError
