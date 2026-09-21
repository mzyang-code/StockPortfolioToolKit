# 月度口径对真实面板的回归：1998-01 至 2024-11 的 323 期月频预测面板
#
# tests/cache/ 不随仓库分发（.gitignore 的 cache/ 规则），面板缺失时整个模块跳过。
# 归档产物 outputs/summary_metrics.csv 是这份数据此前验证过的指标表，产出时的写法是
# 「频率缺省按日频 + 手写 analyzer.periods_per_year: 12」。configs/ 已改成声明
# input.frequency="monthly"、不再写 periods_per_year，本模块以归档表为金标准核对两者一致。
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockportfoliotoolkit.analyzer import Analyzer
from stockportfoliotoolkit.config_schema import PipelineConfig
from stockportfoliotoolkit.engine import PortfolioEngine
from stockportfoliotoolkit.frequency import DAILY, MONTHLY
from stockportfoliotoolkit.input import InputProcessor

CACHE = Path(__file__).parent / "cache" / "spt_demo"
CONFIGS = CACHE / "configs"
PANEL = CACHE / "panel.parquet"
GOLDEN = CACHE / "outputs" / "summary_metrics.csv"

pytestmark = pytest.mark.skipif(
    not (PANEL.exists() and GOLDEN.exists()),
    reason=f"需要 {CACHE} 下的月频面板与归档指标表（不随仓库分发）",
)

EXPECTED_PERIODS = 323
EXPECTED_FIRST = pd.Timestamp("1998-01-31")
EXPECTED_LAST = pd.Timestamp("2024-11-30")


def _config() -> PipelineConfig:
    return PipelineConfig.from_dir(CONFIGS)


# 面板 91 万行 × 3 路信号，读盘是这组用例的主要开销：整个模块只读一次
@pytest.fixture(scope="module")
def monthly_bundle():
    cfg = _config()
    assert cfg.input.frequency == MONTHLY, "configs/input.json 应声明月度口径"
    assert cfg.analyzer.periods_per_year is None, "年化因子应由频率推导，不再手写"
    return InputProcessor(cfg.input).run()


# 归档结果产出时的口径：频率缺省按日频，年化因子靠 analyzer.periods_per_year=12 手写补上
@pytest.fixture(scope="module")
def legacy_bundle(monthly_bundle):
    return replace(monthly_bundle, frequency=DAILY)


@pytest.fixture(scope="module")
def golden() -> pd.DataFrame:
    # bucket 的取值是 "0".."9" 与 "H-L"，不声明 dtype 会被 read_csv 解析成整数
    return pd.read_csv(GOLDEN, dtype={"signal_model": str, "bucket": str, "weight": str})


# 分桶与加权是这组用例里第二贵的一步，每个频率各跑一次
@pytest.fixture(scope="module")
def monthly_result(monthly_bundle):
    return PortfolioEngine(_config().engine).run(monthly_bundle)


@pytest.fixture(scope="module")
def legacy_result(legacy_bundle):
    return PortfolioEngine(_config().engine).run(legacy_bundle)


def _analyze(result, periods_per_year=None):
    cfg = _config()
    cfg.analyzer.periods_per_year = periods_per_year
    return Analyzer(cfg.analyzer).run(result)


@pytest.fixture(scope="module")
def monthly_analysis(monthly_result):
    return _analyze(monthly_result)


@pytest.fixture(scope="module")
def legacy_analysis(legacy_result):
    return _analyze(legacy_result, periods_per_year=12.0)


@pytest.fixture(scope="module")
def unannualized_analysis(legacy_result):
    return _analyze(legacy_result)


def test_panel_is_monthly(monthly_bundle):
    """一行一个资产一个自然月，日历因此每月一期"""
    calendar = pd.DatetimeIndex(monthly_bundle.calendar)
    assert len(calendar) == EXPECTED_PERIODS
    assert calendar[0] == EXPECTED_FIRST and calendar[-1] == EXPECTED_LAST
    assert monthly_bundle.meta["calendar"]["frequency"] == MONTHLY
    assert monthly_bundle.meta["calendar"]["applied_stride"] == 1
    # 每个自然月恰好一个调仓日：月末压缩没有丢期，也没有把两期并成一期
    months = calendar.year * 12 + calendar.month
    assert len(set(months)) == EXPECTED_PERIODS


def test_monthly_alignment_leaves_the_returns_untouched(monthly_result, legacy_result):
    """这份面板一行就是一个月，按自然月对齐与按日期精确对齐必然得出同一张收益表"""
    pd.testing.assert_frame_equal(monthly_result.returns, legacy_result.returns)


def test_declared_monthly_reproduces_the_archived_metrics(monthly_analysis, golden):
    """声明频率替代手写 periods_per_year：指标表与归档结果逐值相同"""
    assert monthly_analysis.meta["periods_per_year"] == pytest.approx(12.0)
    assert monthly_analysis.meta["frequency"] == MONTHLY
    pd.testing.assert_frame_equal(
        monthly_analysis.summary, golden, check_dtype=False, rtol=1e-9, atol=1e-12
    )


def test_explicit_periods_per_year_still_reproduces_it(legacy_analysis, golden):
    """已归档的写法（频率缺省 + periods_per_year=12）结果不变，向后兼容"""
    pd.testing.assert_frame_equal(
        legacy_analysis.summary, golden, check_dtype=False, rtol=1e-9, atol=1e-12
    )


def test_daily_default_would_annualize_by_252(unannualized_analysis, golden):
    """不声明频率又漏写 periods_per_year 时，年化按 252/1 推导——
    这正是 input.frequency="monthly" 要消除的静默失真，此处把倍数钉住。"""
    assert unannualized_analysis.meta["periods_per_year"] == pytest.approx(252.0)

    got = unannualized_analysis.summary.set_index(["signal_model", "bucket", "weight"])
    want = golden.set_index(["signal_model", "bucket", "weight"])
    ratio = (got["ann_ret"] / want["ann_ret"]).dropna()
    assert np.allclose(ratio, 252.0 / 12.0)
    # 累乘出来的指标不受年化因子影响，仍与归档一致
    pd.testing.assert_series_equal(
        got["total_equity"], want["total_equity"], check_dtype=False, rtol=1e-9
    )


def test_headline_numbers(monthly_analysis, monthly_result):
    """多空腿的年化收益与期数，核对到具体数值"""
    assert monthly_result.meta["frequency"] == MONTHLY
    assert monthly_result.meta["periods"] == EXPECTED_PERIODS

    hl = monthly_analysis.summary.query("bucket == 'H-L' and weight == 'EW'").set_index("signal_model")
    assert hl.loc["ACM", "ann_ret"] == pytest.approx(0.3910, abs=5e-5)
    assert hl.loc["RAG", "ann_ret"] == pytest.approx(0.1030, abs=5e-5)
    assert hl.loc["TGNN", "ann_ret"] == pytest.approx(0.3179, abs=5e-5)
    assert (hl["n_periods"] == EXPECTED_PERIODS).all()
