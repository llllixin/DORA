"""API 级 E2E：文档第 36 章 4 个核心验收用例（C5 门禁）。

前置：后端在运行（默认 http://localhost:8000/api；可用 DORA_API_BASE 覆盖）。
运行：cd backend && python3 -m tests.e2e_api_check
说明：脚本自重置（先 sample 出厂，再按用例注入/还原），可重复执行。
"""
import io
import json
import os
import sys
import urllib.request

BASE = os.environ.get("DORA_API_BASE", "http://localhost:8000/api")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path: str):
    with opener.open(BASE + path, timeout=10) as r:
        return json.load(r)


def post(path: str, payload=None):
    req = urllib.request.Request(BASE + path, method="POST",
                                 data=json.dumps(payload or {}).encode(),
                                 headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=15) as r:
        return json.load(r)


def _multipart(filename: str, content: bytes, fields: dict | None = None):
    boundary = "----dora-e2e"
    head = ""
    for k, v in (fields or {}).items():
        head += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
    head += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n")
    body = head.encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def post_file(path: str, filename: str, content: bytes):
    """用系统 curl 上传文件（避免自拼 multipart 兼容问题）。"""
    import pathlib
    import subprocess
    import tempfile
    tmp = tempfile.NamedTemporaryFile("wb", suffix=".csv", delete=False)
    try:
        tmp.write(content)
        tmp.close()
        out = subprocess.run(
            ["curl", "--noproxy", "*", "-s", "-F", f"file=@{tmp.name}", BASE + path],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            raise RuntimeError(out.stderr or "curl failed")
        return json.loads(out.stdout or "{}")
    finally:
        if not tmp.closed:
            tmp.close()
        pathlib.Path(tmp.name).unlink(missing_ok=True)


def east_breach_csv() -> bytes:
    buf = io.StringIO()
    buf.write("metric_key,label,dimension,value,unit\r\n")
    for label, value in [("08/30", "4401"), ("08/31", "4352"), ("09/01", "4318"), ("09/02", "4295"), ("09/03", "3600")]:
        buf.write(f"east_orders,{label},华东,{value},\r\n")
    return buf.getvalue().encode("utf-8")


def main() -> int:
    post("/datasets/sample")  # 出厂重置

    # Case 1：问题 → Evidence → Action（真实档案）
    probs = get("/insights?type=problem")
    assert any(i["id"] == "p1" for i in probs), "p1 problem missing"
    ev = get("/evidence/p1")
    assert ev["rawRows"] and ev["hits"], "p1 evidence empty"
    p1_case = get("/action/cases/p1")
    assert p1_case["case"]["id"] == "p1" and p1_case["case"]["steps"], "p1 seed action case missing"

    # Case 2：机会 → 验证可复制 → Action（真实档案）
    opps = get("/insights?type=opportunity")
    assert any(i["id"] == "o1" for i in opps), "o1 opportunity missing"
    o1_case = get("/action/cases/o1")
    assert o1_case["case"]["id"] == "o1" and o1_case["case"]["steps"], "o1 seed action case missing"

    # Case 3：变化 → Watch
    chgs = get("/insights?type=change")
    assert any(i["id"] == "c1" for i in chgs), "c1 change missing"
    c1d = get("/insights/c1")
    assert c1d.get("route") == "watch", "c1 should route to watch"

    # Case 4：Watch → 跌破阈值 → 自动升级 Problem
    up = post_file("/datasets", "east_breach.csv", east_breach_csv())
    assert up.get("ok"), "breach upload failed"
    probs2 = get("/insights?type=problem")
    assert any(i["id"] == "e2" for i in probs2), "e2 auto-upgrade problem missing"
    chgs2 = get("/insights?type=change")
    assert not any(i["id"] == "c1" for i in chgs2), "c1 should be replaced after breach"
    assert get("/insights/e2").get("route") == "action", "e2 should route to action"

    post("/datasets/sample")  # 还原出厂
    probs3 = get("/insights?type=problem")
    assert not any(i["id"] == "e2" for i in probs3) and any(i["id"] == "p1" for i in probs3), "restore failed"

    print("e2e_api_check OK (4 core cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
