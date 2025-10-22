# -*- coding: utf-8 -*-

import os
import re
from typing import Dict, List, Iterable, Tuple

TEXT_EXTS = {
    ".py",".js",".ts",".tsx",".jsx",".java",".go",".rs",".rb",".php",".cs",".c",".cpp",
    ".h",".hpp",".m",".mm",".kt",".swift",".scala",".lua",".pl",".r",".md",".txt",".yml",
    ".yaml",".json",".toml",".ini",".gradle",".cfg",".sh",".bat",".ps1",".make",".mk",".dockerfile"
}

def is_text_file(path: str) -> bool:
    # 依据扩展名快速判断文本文件
    _, ext = os.path.splitext(path.lower())
    if ext in TEXT_EXTS:
        return True
    if os.path.basename(path.lower()) in {"dockerfile", "makefile"}:
        return True
    return False

def iter_text_files(root: str) -> Iterable[str]:
    # 遍历仓库文本文件
    skip_dirs = {".git", "node_modules", "dist", "build", "out", ".next", ".venv", "venv", "__pycache__"}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            p = os.path.join(base, f)
            if is_text_file(p):
                yield p

def tokenize_keywords(text: str) -> List[str]:
    # 关键词抽取
    tokens = []
    # 提取英文与数字词
    tokens += re.findall(r"[a-zA-Z0-9_]{3,}", text)
    # 提取中文短语, 限制长度避免噪声
    tokens += [m for m in re.findall(r"[\u4e00-\u9fa5]{2,8}", text)]
    # 去重并保持原有顺序
    seen = set()
    ordered = []
    for t in tokens:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            ordered.append(t)
    return ordered

def best_k(score_map: Dict[str, int], k: int) -> List[str]:
    # 返回得分最高的前K个文件路径
    return [p for p, _ in sorted(score_map.items(), key=lambda x: x[1], reverse=True)[:k]]
