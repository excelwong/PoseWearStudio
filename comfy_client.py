# -*- coding: utf-8 -*-
"""ComfyUI HTTP API 客户端：上传 / 排队 / 轮询 / 取图。"""
import json
import os
import time
import uuid

import requests


class ComfyError(RuntimeError):
    pass


class OOMError(ComfyError):
    pass


class ComfyClient:
    def __init__(self, url="http://127.0.0.1:8188", timeout=20):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())
        self.session = requests.Session()
        self.session.trust_env = False  # 绕过系统代理，直连 localhost

    def _get(self, path, **kw):
        r = self.session.get(self.url + path, timeout=kw.pop("timeout", self.timeout), **kw)
        r.raise_for_status()
        return r

    def status(self):
        return self._get("/system_stats", timeout=6).json()

    def queue_status(self):
        try:
            return self._get("/queue", timeout=5).json()
        except Exception:
            return {}

    def upload(self, local_path, name=None):
        """上传任意本地图片，返回 ComfyUI input 目录下可用的文件名。"""
        if not os.path.isfile(local_path):
            raise ComfyError("图片不存在: " + local_path)
        if name is None:
            ext = os.path.splitext(local_path)[1].lower() or ".png"
            if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                ext = ".png"
            name = "pws_" + uuid.uuid4().hex[:12] + ext
        with open(local_path, "rb") as f:
            r = self.session.post(
                self.url + "/upload/image",
                files={"image": (name, f, "image/png")},
                data={"overwrite": "true", "type": "input"},
                timeout=120,
            )
        r.raise_for_status()
        info = r.json()
        return info.get("name", name)

    def queue(self, prompt):
        r = self.session.post(
            self.url + "/prompt",
            data=json.dumps({"prompt": prompt, "client_id": self.client_id}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=60,
        )
        if r.status_code >= 400:
            detail = r.text[:2000]
            try:
                j = r.json()
                detail = json.dumps(j, ensure_ascii=False)[:2000]
            except Exception:
                pass
            raise ComfyError("工作流提交失败 (HTTP %s): %s" % (r.status_code, detail))
        data = r.json()
        if data.get("node_errors"):
            raise ComfyError("节点校验失败: " + json.dumps(data["node_errors"], ensure_ascii=False)[:2000])
        return data["prompt_id"]

    def wait(self, prompt_id, timeout=1200, poll=0.8, on_tick=None, cancel=None):
        """轮询 /history 直到完成，返回该条 history。"""
        start = time.time()
        while True:
            if cancel is not None and cancel():
                raise ComfyError("已取消")
            if time.time() - start > timeout:
                raise ComfyError("生成超时（%s 秒）" % timeout)
            try:
                h = self._get("/history/" + prompt_id, timeout=8).json()
                if prompt_id in h:
                    entry = h[prompt_id]
                    st = entry.get("status", {})
                    if st.get("completed") or st.get("status_str") == "error" or entry.get("outputs"):
                        self._check_error(entry)
                        return entry
            except ComfyError:
                raise
            except Exception:
                pass
            if on_tick:
                try:
                    on_tick(time.time() - start, self.queue_status())
                except Exception:
                    pass
            time.sleep(poll)

    @staticmethod
    def _check_error(entry):
        st = entry.get("status", {})
        if st.get("status_str") == "error" or st.get("completed") is False and st.get("messages"):
            msgs = st.get("messages", [])
            text = json.dumps(msgs, ensure_ascii=False)
            if "out of memory" in text.lower() or "cuda oom" in text.lower() or "Allocation on device" in text:
                raise OOMError("显存不足: " + text[:900])
            raise ComfyError("生成失败: " + text[:1500])
        # 节点级异常也可能不带 status_str=error
        for m in st.get("messages", []):
            if isinstance(m, (list, tuple)) and len(m) > 1 and m[0] == "execution_error":
                d = m[1] or {}
                text = str(d.get("exception_message", "")) + " " + str(d.get("traceback", ""))[:500]
                if "out of memory" in text.lower():
                    raise OOMError("显存不足: " + text[:900])
                raise ComfyError("节点执行失败: " + text[:900])

    @staticmethod
    def images(entry, output_node_id="32"):
        outs = (entry.get("outputs") or {}).get(output_node_id, {})
        return outs.get("images", []) or []

    def fetch(self, image_info):
        params = {
            "filename": image_info.get("filename", ""),
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        }
        return self._get("/view", params=params, timeout=120).content

    def interrupt(self):
        try:
            self.session.post(self.url + "/interrupt", timeout=5)
        except Exception:
            pass
