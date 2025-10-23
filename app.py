# -*- coding: utf-8 -*-

import io
import os
import gc
import json
import shutil
import zipfile
import tempfile
from flask import Flask, request, jsonify
from tqdm import tqdm
from analyzer import analyze_repository, try_functional_verification

app = Flask(__name__)

# 安全限制
MAX_ZIP_SIZE = 200 * 1024 * 1024

@app.route("/analyze", methods=["POST"])
def analyze():
    # 参数校验
    if "problem_description" not in request.form or "code_zip" not in request.files:
        return jsonify({"error": "缺少字段: problem_description或code_zip"}), 400

    problem_description = request.form.get("problem_description", "").strip()
    if not problem_description:
        return jsonify({"error": "problem_description不能为空"}), 400

    file_storage = request.files["code_zip"]
    filename = file_storage.filename or "repo.zip"

    # 限制与读取上传体, 保证内存安全
    raw = file_storage.read()
    if len(raw) > MAX_ZIP_SIZE:
        return jsonify({"error": "ZIP文件过大"}), 413

    zip_bytes = io.BytesIO(raw)
    del raw

    # 验证ZIP完整性
    try:
        with zipfile.ZipFile(zip_bytes) as zf:
            bad = zf.testzip()
            if bad:
                return jsonify({"error": "ZIP文件损坏"}), 400
    except Exception:
        return jsonify({"error": "ZIP文件解析失败"}), 400

    # 创建临时工作目录
    tmp_root = tempfile.mkdtemp(prefix="agent_")
    extract_dir = os.path.join(tmp_root, "repo")
    os.makedirs(extract_dir, exist_ok=True)

    # 控制台进度条
    steps = [
        "解压代码仓库",
        "建立文件索引",
        "特征提取与匹配",
        "定位实现与行号",
        "生成JSON报告",
    ]
    run_verification = request.args.get("run_tests", "false").lower() == "true"
    if run_verification:
        steps.append("动态验证")

    report = {}
    try:
        # 解压
        with tqdm(total=len(steps), desc="进度", unit="步") as bar:
            with zipfile.ZipFile(zip_bytes) as zf:
                zf.extractall(extract_dir)
            bar.update(1)

            # 分析
            feature_analysis, plan = analyze_repository(problem_description, extract_dir,
                                                        on_progress=lambda _: bar.update(1))
            report["feature_analysis"] = feature_analysis
            report["execution_plan_suggestion"] = plan

            # 若启用, 进行可选动态验证
            if run_verification:
                verification = try_functional_verification(extract_dir, problem_description)
                report["functional_verification"] = verification
                bar.update(1)

        # 最终JSON
        return jsonify(report), 200

    finally:
        # 回收内存
        try:
            shutil.rmtree(tmp_root, ignore_errors=True)
        finally:
            gc.collect()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8010)
