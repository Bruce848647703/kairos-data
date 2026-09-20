"""数据处理管道：把若干 transform 步骤串起来，对数据集依次应用。

``Pipeline`` 让「去重 -> 对齐日历 -> 限量填充 -> 复权」这类多步清洗流程可声明、
可复用、可组合。每一步是一个接收数据并返回数据的可调用对象；``run`` 按加入顺序
把数据依次传入，返回最终结果。

设计意图：与逐步手工调用完全等价（见测试），但把流程固化成对象，便于在不同数据集
上重复执行、打印与审计。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence


@dataclass
class Step:
    """单个变换步骤：可调用对象 + 其位置参数与关键字参数。

    ``func`` 必须以数据（通常是 DataFrame）为第一个位置参数，返回处理后的数据。
    调用时执行 ``func(data, *args, **kwargs)``。
    """

    func: Callable[..., Any]
    name: Optional[str] = None
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)

    def __call__(self, data: Any) -> Any:
        return self.func(data, *self.args, **self.kwargs)

    def label(self) -> str:
        """步骤展示名（优先 name，其次函数名）。"""
        return self.name or getattr(self.func, "__name__", repr(self.func))


class Pipeline:
    """把 ``Step`` 串成管道，``run(data)`` 依次让数据流过每一步。

    支持链式调用（``add_step`` 返回 self），也支持在构造时传入步骤序列。序列元素
    可为可调用对象，或已封装好的 ``Step``。
    """

    def __init__(self, steps: Optional[Sequence[Any]] = None):
        self.steps: List[Step] = []
        for s in (steps or []):
            self.add_step(s)

    def add_step(self, func: Any, *args: Any, name: Optional[str] = None,
                 **kwargs: Any) -> "Pipeline":
        """追加一个步骤。

        - 传入 ``Step``：直接加入。
        - 传入可调用对象：以 ``*args``/``**kwargs`` 作为其额外参数封装为 ``Step``。

        返回 self 以支持链式调用。
        """
        if isinstance(func, Step):
            self.steps.append(func)
        elif callable(func):
            self.steps.append(Step(func, name=name, args=args, kwargs=kwargs))
        else:
            raise TypeError("add_step 需要可调用对象或 Step 实例")
        return self

    def run(self, data: Any) -> Any:
        """按顺序对 ``data`` 应用所有步骤，返回最终结果。"""
        for step in self.steps:
            data = step(data)
        return data

    # 语义别名
    transform = run

    def __len__(self) -> int:
        return len(self.steps)

    def __repr__(self) -> str:
        body = " -> ".join(s.label() for s in self.steps)
        return f"Pipeline([{body}])"
