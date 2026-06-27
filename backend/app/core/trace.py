"""
実行トレース（ステータス・処理時間の記録）
=========================================

【为什么 / なぜ】

平台が「複数エージェントをオーケストレーションする」以上、
「どのエージェントが・成功したか・何msかかったか」を **必ず可視化** したい。
これが無いと、遅い/失敗したのが誰なのか分からず運用できない。

ここでは1リクエストの実行を ExecutionTrace にまとめ、
各ステップ(StepTrace)に status / elapsed_ms / error を残す。
APIレスポンスにそのまま載せて、観測可能性(observability)のデモにする。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class StepStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class StepTrace:
    step: str                      # "route" / "agent:knowledge" / "connector:calendar" など
    status: StepStatus = StepStatus.RUNNING
    elapsed_ms: float = 0.0
    detail: str = ""               # 人间可读的简短说明
    error: str | None = None


@dataclass
class ExecutionTrace:
    """1回の /chat 実行のトレース全体。"""
    route_mode: str = ""           # "rule" or "llm"
    chosen_agent: str = ""
    steps: list[StepTrace] = field(default_factory=list)
    total_ms: float = 0.0

    def start_step(self, step: str) -> "_StepTimer":
        """`async with trace.start_step("agent:x") as st:` で計測する。"""
        return _StepTimer(self, step)

    def to_dict(self) -> dict:
        return {
            "route_mode": self.route_mode,
            "chosen_agent": self.chosen_agent,
            "total_ms": round(self.total_ms, 1),
            "steps": [
                {
                    "step": s.step,
                    "status": s.status.value,
                    "elapsed_ms": round(s.elapsed_ms, 1),
                    "detail": s.detail,
                    "error": s.error,
                }
                for s in self.steps
            ],
        }


class _StepTimer:
    """ステップの開始/終了で時間を測り、例外を status に反映するヘルパ。"""

    def __init__(self, trace: ExecutionTrace, step: str) -> None:
        self.trace = trace
        self.st = StepTrace(step=step)
        self._t0 = 0.0

    async def __aenter__(self) -> StepTrace:
        self.trace.steps.append(self.st)
        self._t0 = time.perf_counter()
        return self.st

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.st.elapsed_ms = (time.perf_counter() - self._t0) * 1000
        if exc_type is not None:
            # TimeoutError は専用ステータスに、それ以外は ERROR に
            import asyncio
            self.st.status = (
                StepStatus.TIMEOUT if exc_type is asyncio.TimeoutError else StepStatus.ERROR
            )
            self.st.error = f"{exc_type.__name__}: {exc}"
        elif self.st.status == StepStatus.RUNNING:
            self.st.status = StepStatus.SUCCESS
        # False を返す＝例外を握り潰さず上に伝える（orchestrator 側で処理する）
        return False
