# -*- coding: utf-8 -*-
import zipfile, os, sys

ZIP = os.path.abspath("test_repo.zip")
print("ZIP 路径:", ZIP)
assert os.path.exists(ZIP), "test_repo.zip 不存在"

with zipfile.ZipFile(ZIP, "r") as zf:
    names = zf.namelist()
    print("ZIP 内文件列表(前20):")
    for n in names[:20]:
        print(" -", n)
    # 读取 main.py 头几行，验证内容
    cand = [n for n in names if n.endswith("main.py")]
    assert cand, "ZIP 中未找到 main.py"
    with zf.open(cand[0], "r") as f:
        head = f.read(300).decode("utf-8", "ignore")
        print("\nmain.py 开头内容:\n", head)
