# -*- coding: utf-8 -*-

import os
import re
import gc
import json
import shlex
import subprocess

from typing import List, Dict, Callable, Tuple
from utils import iter_text_files, tokenize_keywords, best_k

# 中英常用术语同义词表
SYNONYMS = {
    "频道": ["channel"],
    "消息": ["message"],
    "建立": ["create", "init", "new"],
    "创建": ["create", "init", "new"],
    "发送": ["send", "post", "publish"],
    "倒序": ["desc", "order by desc", "sort desc"],
    "按时间": ["time", "timestamp", "createdat", "updatedat", "created_at", "updated_at"],
    "列表": ["list", "get", "fetch", "findall", "find_all"],
    "查询": ["get", "find", "query"],
    "删除": ["delete", "remove", "destroy"],
    "更新": ["update", "edit", "modify"]
}

# 常见函数定义
FUNC_PATTERNS = [
    r"\bdef\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    r"\bfunction\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    r"\b([a-zA-Z_][a-zA-Z0-9_:<>]*)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\([\s\S]*?\)\s*=>",
]

# 常量配置
MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_HITS_PER_FEATURE = 8
# 方案2: 收紧聚合窗口, 避免跨函数合并
CONTEXT_WINDOW = 3

def _normalize_text(s: str) -> str:
    # 统一规范化
    t = s.replace("_", " ")
    t = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", t)
    t = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t

def _expand_keywords(raw_keywords: List[str]) -> List[str]:
    # 关键词, 并对中文长词做2~4字短语切分
    def is_cjk(ch: str) -> bool:
        return '\u4e00' <= ch <= '\u9fff'

    pieces: List[str] = []
    for kw in raw_keywords:
        k = kw.strip()
        if not k:
            continue
        pieces.append(k)
        if any(is_cjk(c) for c in k):
            chars = [c for c in k if is_cjk(c)]
            n = len(chars)
            for size in (2, 3, 4):
                for i in range(0, max(0, n - size + 1)):
                    sub = "".join(chars[i:i+size])
                    if sub and sub not in pieces:
                        pieces.append(sub)

    expanded: List[str] = []
    for p in pieces:
        expanded.append(p)
        pl = p.lower()
        for key, syns in SYNONYMS.items():
            kl = key.lower()
            if kl in pl or pl in kl:
                expanded.extend(syns)

    out, seen = [], set()
    for w in expanded:
        wl = w.lower()
        if wl and wl not in seen:
            seen.add(wl)
            out.append(wl)
    return out

def _detect_functions(lines: List[str]) -> List[Tuple[int, int, str]]:
    # 返回函数区间与名称,用于将命中跨度映射到具体函数
    marks = []
    for i, line in enumerate(lines):
        for pat in FUNC_PATTERNS:
            m = re.search(pat, line)
            if m:
                name = m.group(m.lastindex or 1)
                marks.append((i, name))
                break
    spans = []
    for idx, (start, name) in enumerate(marks):
        end = marks[idx + 1][0] - 1 if idx + 1 < len(marks) else len(lines) - 1
        spans.append((start, end, name))
    return spans

def _match_keyword_spans_norm(lines: List[str], keywords: List[str]) -> List[Tuple[int, int]]:
    # 使用规范化文本进行行命中,按窗口聚合为跨度
    hits = []
    for i, line in enumerate(lines):
        norm = _normalize_text(line)
        for kw in keywords:
            if kw in norm:
                hits.append(i)
                break
    if not hits:
        return []
    spans = []
    start = hits[0]
    prev = hits[0]
    for h in hits[1:]:
        if h - prev <= CONTEXT_WINDOW:
            prev = h
        else:
            spans.append((start, prev))
            start = h
            prev = h
    spans.append((start, prev))
    return spans

def _execution_plan_hint(cache: Dict[str, List[str]]) -> str:
    # 给出可执行计划提示来源文件名
    names = ["package.json", "requirements.txt", "Makefile", "README.md", "docker-compose.yml"]
    for n in names:
        for p in cache.keys():
            if p.endswith(n):
                return os.path.basename(p)
    return ""

def analyze_repository(problem: str, root: str, on_progress: Callable[[str], None]) -> List[Dict]:
    # 1)从需求文本拆分特征
    feats = [s.strip(" 。；;,.") for s in re.split(r"[。；;\n]+", problem) if s.strip()] or [problem.strip()]

    # 2)建立文件清单
    files = []
    for path in iter_text_files(root):
        try:
            if os.path.getsize(path) <= MAX_FILE_SIZE:
                files.append(path)
        except Exception:
            continue
    on_progress("索引完成")

    # 3)读取文件到缓存
    cache: Dict[str, List[str]] = {}
    for p in files:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                cache[p] = f.read().splitlines()
        except Exception:
            cache[p] = []
    on_progress("读取完成")

    results: List[Dict] = []

    for feat in feats:
        # 4) 关键词提取与同义词
        raw_keywords = tokenize_keywords(feat)
        keywords = _expand_keywords(raw_keywords)

        # 5) 粗筛:文件打分+轻量加权
        score_map: Dict[str, int] = {}
        for fp, lines in cache.items():
            score = 0
            line_hits = []
            fname = os.path.basename(fp).lower()
            fpath = fp.lower()

            for idx, line in enumerate(lines):
                norm = _normalize_text(line)
                matched = False
                for kw in keywords:
                    if kw in norm:
                        score += 1
                        matched = True
                if matched:
                    line_hits.append(idx)
                if re.search(r"\b(def|function)\b", norm):
                    for kw in keywords:
                        if kw in norm:
                            score += 1

            # 文件名与路径命中加权
            nf = _normalize_text(fname)
            np = _normalize_text(fpath)
            for kw in keywords:
                if kw in nf:
                    score += 2
                if kw in np:
                    score += 1

            if score > 0:
                score_map[fp] = score

        # 6) 精筛:取高分文件,计算命中跨度并与函数边界求交,按函数切分输出
        impls = []
        for fp in best_k(score_map, MAX_HITS_PER_FEATURE):
            lines = cache.get(fp, [])
            if not lines:
                continue
            func_spans = _detect_functions(lines)
            match_spans = _match_keyword_spans_norm(lines, keywords)
            for s, e in match_spans[:6]:
                attached = False
                for fs, fe, name in func_spans:
                    is_ = max(s, fs)
                    ie_ = min(e, fe)
                    if is_ <= ie_:
                        impls.append({
                            "file": os.path.relpath(fp, root).replace("\\", "/"),
                            "function": name or "",
                            "lines": f"{is_ + 1}-{ie_ + 1}"
                        })
                        attached = True
                if not attached:
                    impls.append({
                        "file": os.path.relpath(fp, root).replace("\\", "/"),
                        "function": "",
                        "lines": f"{s + 1}-{e + 1}"
                    })

        results.append({
            "feature_description": feat,
            "implementation_location": impls
        })

        # 回收内存
        gc.collect()

    plan = _execution_plan_hint(cache) or ""
    cache.clear()
    gc.collect()
    return results, plan

def try_functional_verification(repo_dir: str, problem: str) -> Dict:
    # 返回结构初始化
    result = {
        "generated_test_code": "",
        "execution_result": {
            "tests_passed": False,
            "log": ""
        }
    }

    # 日志截断上限与超时秒数
    LOG_LIMIT = 4000
    TIMEOUT_SEC = 10

    try:
        # 路径探测
        pkg_json_path = os.path.join(repo_dir, "package.json")
        py_hints = [
            os.path.join(repo_dir, "pytest.ini"),
            os.path.join(repo_dir, "pyproject.toml"),
            os.path.join(repo_dir, "requirements.txt"),
            os.path.join(repo_dir, "setup.cfg")
        ]
        has_py_hint = any(os.path.exists(p) for p in py_hints) or os.path.isdir(os.path.join(repo_dir, "tests"))

        # 一: Node项目尝试执行npm test
        if os.path.exists(pkg_json_path):
            # 生成最小Node测试样例
            node_smoke = (
                "const assert = require('assert');\n"
                "describe('smoke', ()=>{ it('ok', ()=>{ assert.equal(1,1); }); });\n"
            )
            result["generated_test_code"] = node_smoke

            # 检查package.json是否存在test脚本
            has_test_script = False
            try:
                with open(pkg_json_path, "r", encoding="utf-8", errors="ignore") as f:
                    pkg = json.load(f)
                scripts = pkg.get("scripts") or {}
                if isinstance(scripts, dict) and "test" in scripts and isinstance(scripts["test"], str) and scripts["test"].strip():
                    has_test_script = True
            except Exception as e:
                result["execution_result"]["log"] = f"读取 package.json失败: {e}"

            # 存在test脚本时执行npm test
            if has_test_script:
                try:
                    # npm_test, 设置超时与日志截断
                    proc = subprocess.run(
                        shlex.split("npm test --silent"),
                        cwd=repo_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        timeout=TIMEOUT_SEC,
                        text=True
                    )
                    out = proc.stdout or ""
                    result["execution_result"]["tests_passed"] = (proc.returncode == 0)
                    result["execution_result"]["log"] = out[:LOG_LIMIT]
                except Exception as e:
                    # npm或执行失败, 返回样例与可执行提示
                    base_log = result["execution_result"]["log"]
                    append = f"不执行npm test: {e}. 保存为test/smoke.test.js运行npm test。"
                    result["execution_result"]["log"] = (base_log + ("\n" if base_log else "") + append)[:LOG_LIMIT]
            else:
                # 无test脚本,给出提示
                base_log = result["execution_result"]["log"]
                append = "检测到package.json但是未定义scripts.test,提供最小测试样例,保存为test/smoke.test.js 添加scripts.test"
                result["execution_result"]["log"] = (base_log + ("\n" if base_log else "") + append)[:LOG_LIMIT]

            return result

        # 二: Python尝试执行pytest
        if has_py_hint:
            # 生成最小Python测试样例
            py_smoke = "def test_smoke():\n    assert 1 == 1\n"
            result["generated_test_code"] = py_smoke

            try:
                proc = subprocess.run(
                    shlex.split("pytest -q"),
                    cwd=repo_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=TIMEOUT_SEC,
                    text=True
                )
                out = proc.stdout or ""
                result["execution_result"]["tests_passed"] = (proc.returncode == 0)
                result["execution_result"]["log"] = out[:LOG_LIMIT]
            except Exception as e:
                # 无pytest或执行失败, 返回样例
                result["execution_result"]["log"] = f"未执行pytest: {e}. 保存为tests/test_smoke.py 本地或CI中运行pytest"

            return result

        # 没识别为常见测试结构, 返回样例与指引
        result["execution_result"]["log"] = "未检测到常见测试配置,已提供最小测试样例;Node项目添加scripts.test,Python项目请添加tests目录与pytest"
        return result

    except Exception as e:
        # 异常处理
        result["execution_result"]["log"] = f"动态验证过程出错: {e}"
        return result

    finally:
        # 回收
        gc.collect()
