"""本地数据集存储（DataStore）。

把一个 DataFrame 以「名字 -> 文件」的形式落盘到本地目录，支持：
- **CSV（默认）**：零额外依赖，跨平台可读，是本库的默认存储格式。
- **Parquet（可选）**：依赖 pyarrow；当 ``format="parquet"`` 但 pyarrow 缺失时，
  自动回退为 CSV 并发出 ``RuntimeWarning``，保证在任何环境都可用。

目录结构：``root/<name>.<ext>``，一个数据集一个文件。测试建议使用 pytest 的
``tmp_path`` 作为 root，避免污染工作目录。
"""
from __future__ import annotations

import importlib.util
import os
import warnings
from typing import List, Optional

import pandas as pd

SUPPORTED_FORMATS = ("csv", "parquet")


def _pyarrow_available() -> bool:
    """检测 pyarrow 是否可导入（不真正加载重依赖）。"""
    return importlib.util.find_spec("pyarrow") is not None


class DataStore:
    """本地目录数据集存储。

    参数
    ----
    root:   存储根目录，构造时自动创建。
    format: 落盘格式，"csv"（默认）或 "parquet"。选 parquet 但缺 pyarrow 时回退 CSV。
    """

    def __init__(self, root: str, format: str = "csv"):
        fmt = str(format).lower().strip()
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(f"不支持的格式 '{format}'，可选: {SUPPORTED_FORMATS}")
        if fmt == "parquet" and not _pyarrow_available():
            warnings.warn(
                "未检测到 pyarrow，Parquet 不可用；DataStore 已回退为 CSV 格式。"
                "如需 Parquet 请执行 `pip install pyarrow`。",
                RuntimeWarning,
                stacklevel=2,
            )
            fmt = "csv"
        self.root = str(root)
        self.format = fmt
        os.makedirs(self.root, exist_ok=True)

    # ---- 内部工具 ----
    @property
    def _ext(self) -> str:
        return "parquet" if self.format == "parquet" else "csv"

    def _path(self, name: str, ext: Optional[str] = None) -> str:
        return os.path.join(self.root, f"{name}.{ext or self._ext}")

    def _existing_path(self, name: str) -> Optional[str]:
        """返回已存在的数据集文件路径（优先 parquet，其次 csv），不存在则 None。"""
        for ext in ("parquet", "csv"):
            p = self._path(name, ext)
            if os.path.exists(p):
                return p
        return None

    # ---- 公共 API ----
    def save(self, name: str, df: pd.DataFrame) -> str:
        """把 DataFrame 存为数据集 ``name``，返回落盘文件路径。

        以当前 ``format`` 写出；若同名数据集存在另一种格式的旧文件，会先删除，
        避免 load 时读到过期数据。
        """
        if not isinstance(df, pd.DataFrame):
            raise TypeError("save 只接受 pandas.DataFrame")
        other_ext = "csv" if self.format == "parquet" else "parquet"
        stale = self._path(name, other_ext)
        if os.path.exists(stale):
            os.remove(stale)
        path = self._path(name)
        if self.format == "parquet":
            df.to_parquet(path)
        else:
            df.to_csv(path)
        return path

    def load(self, name: str, parse_dates: bool = True) -> pd.DataFrame:
        """读取数据集 ``name``；不存在时抛 ``FileNotFoundError``。

        CSV 会把第 0 列作为索引，并在 ``parse_dates=True`` 时解析为时间索引。
        """
        path = self._existing_path(name)
        if path is None:
            raise FileNotFoundError(f"数据集 '{name}' 不存在于 {self.root}")
        if path.endswith(".parquet"):
            return pd.read_parquet(path)
        # float_precision="round_trip" 保证 float64 经 CSV 往返后逐位一致。
        return pd.read_csv(path, index_col=0, parse_dates=parse_dates,
                           float_precision="round_trip")

    def exists(self, name: str) -> bool:
        """数据集是否存在。"""
        return self._existing_path(name) is not None

    def list(self) -> List[str]:
        """列出当前目录下所有数据集名（去重、升序）。"""
        if not os.path.isdir(self.root):
            return []
        names = set()
        for fn in os.listdir(self.root):
            for ext in SUPPORTED_FORMATS:
                if fn.endswith("." + ext):
                    names.add(fn[: -(len(ext) + 1)])
                    break
        return sorted(names)

    def delete(self, name: str) -> bool:
        """删除数据集（任意格式）；删除成功返回 True，不存在返回 False。"""
        path = self._existing_path(name)
        if path is None:
            return False
        os.remove(path)
        return True

    def __repr__(self) -> str:
        return f"DataStore(root={self.root!r}, format={self.format!r})"
