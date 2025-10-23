# -*- coding: utf-8 -*-
import requests, json

def run(desc):
    url = "http://127.0.0.1:8010/analyze"
    with open("test_repo.zip", "rb") as f:
        files = {
            "problem_description": (None, desc),
            "code_zip": f
        }
        r = requests.post(url, files=files, timeout=120)
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    run("实现建立频道功能，并在频道中发送消息功能")
