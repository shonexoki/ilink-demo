import asyncio
import json
import time
import uuid
import base64
import httpx
from typing import Dict, Optional
import qrcode
from PIL import Image
import os


class ILinkBot:
    BASE_URL = "https://ilinkai.weixin.qq.com"
    SESSION_FILE = "ilink_bot_session.json"   # 会话保存文件
    
    def __init__(self):
        self.token: Optional[str] = None
        self.account_id: Optional[str] = None
        self.cursor: str = ""
        self.client = httpx.AsyncClient(timeout=40.0)
        self.running = False
        self.load_session()

    def load_session(self):
        """从本地加载会话"""
        if os.path.exists(self.SESSION_FILE):
            try:
                with open(self.SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.token = data.get("token")
                    self.account_id = data.get("account_id")
                    self.cursor = data.get("cursor", "")
                print(f"✅ 已加载本地会话 (Bot: {self.account_id})")
            except Exception as e:
                print("加载会话失败:", e)

    def save_session(self):
        """保存会话到本地"""
        try:
            data = {
                "token": self.token,
                "account_id": self.account_id,
                "cursor": self.cursor,
                "save_time": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(self.SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("💾 会话已保存")
        except Exception as e:
            print("保存会话失败:", e)

    def _get_headers(self) -> Dict:
        random_uin = str(uuid.uuid4().int % (1 << 32))
        uin_b64 = base64.b64encode(random_uin.encode()).decode().rstrip('=')
        
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.token}",
            "X-WECHAT-UIN": uin_b64,
            "iLink-App-ClientVersion": "1",
            "User-Agent": "ilink-bot-client"
        }

    async def login(self, force_login=False):
        """登录（优先使用本地Token）"""
        if not force_login and self.token:
            print("尝试使用已保存的 Token...")
            try:
                # 简单验证 Token 是否有效
                await self._post("/ilink/bot/getupdates", {"get_updates_buf": self.cursor})
                print("✅ Token 有效，直接启动")
                return
            except Exception as e:
                if "-14" in str(e) or "过期" in str(e):
                    print("⚠️ Token 已过期，需要重新登录")
                    self.token = None
                else:
                    print("Token 验证失败，将重新登录")

        # 执行扫码登录
        print("开始扫码登录...")
        resp = await self.client.get(f"{self.BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3")
        data = resp.json()
        qrcode_token = data["qrcode"]
        qr_url = data.get("qrcode_img_content") or data.get("qrcode_url")

        print("请使用微信扫描下方二维码：")
        qr = qrcode.QRCode()
        qr.add_data(qr_url)
        qr.make()
        qr.print_ascii()

        try:
            img = qrcode.make(qr_url)
            img.show()
        except:
            pass

        print("等待扫码确认...")
        while True:
            status_resp = await self.client.get(
                f"{self.BASE_URL}/ilink/bot/get_qrcode_status?qrcode={qrcode_token}",
                headers={"iLink-App-ClientVersion": "1"}
            )
            status_data = status_resp.json()
            
            if status_data.get("status") == "confirmed":
                self.token = status_data["bot_token"]
                self.account_id = status_data.get("ilink_bot_id")
                self.cursor = ""  # 重置 cursor
                print(f"✅ 登录成功！Bot ID: {self.account_id}")
                self.save_session()
                break
            elif status_data.get("status") in ["expired", "canceled", "error"]:
                raise Exception("二维码已过期或被取消，请重新运行")
            
            await asyncio.sleep(2)

    async def _post(self, endpoint: str, json_data: Dict):
        payload = {**json_data, "base_info": {"channel_version": "1.0.0"}}
        
        resp = await self.client.post(
            f"{self.BASE_URL}{endpoint}",
            json=payload,
            headers=self._get_headers()
        )
        
        try:
            result = resp.json()
            print(f"API Response: {result}")
        except:
            result = {"ret": -1, "errmsg": "json parse error"}

        # getupdates 特殊处理
        if endpoint == "/ilink/bot/getupdates":
            if "msgs" in result or result.get("ret") == 0:
                return result
            return {"ret": 0, "msgs": [], "get_updates_buf": self.cursor}

        if result.get("ret") != 0:
            errcode = result.get("errcode") or result.get("ret")
            if errcode in (-14, 14):
                raise Exception("会话已过期，需要重新登录")
            raise Exception(f"API Error: {result}")
        
        return result

    async def poll_messages(self):
        try:
            data = await self._post("/ilink/bot/getupdates", {
                "get_updates_buf": self.cursor
            })
            print(f"轮询结果: {data}")
            if "get_updates_buf" in data:
                self.cursor = data["get_updates_buf"]
            
            for msg in data.get("msgs", []):
                if msg.get("message_type") == 1:   # 用户消息
                    await self.handle_message(msg)
                    
        except Exception as e:
            err_str = str(e).lower()
            if "过期" in err_str or "-14" in err_str:
                print("❌ Token 已过期，正在重新登录...")
                self.token = None
                await self.login()
            else:
                print(f"轮询异常（可忽略）: {err_str}")
                await asyncio.sleep(1)

    async def handle_message(self, msg: Dict):
        text = ""
        for item in msg.get("item_list", []):
            if item.get("type") == 1 and item.get("text_item"):
                text = item["text_item"]["text"]
                
                ref = item.get("ref_msg")
                if ref and isinstance(ref, dict):
                    title = ref.get("title", "")
                    if title:
                        text = f"[引用:{title}]\n{text}"
                break
        
        from_id = msg.get("from_user_id")
        context_token = msg.get("context_token")
        
        print(f"\n收到来自 {from_id} 的消息: {text}")
        
        # Echo 回复
        await self.send_text(from_id, f"已收到：{text}", context_token)

    async def send_text(self, to_user_id: str, text: str, context_token: str):
        client_id = f"pybot-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"
        
        await self._post("/ilink/bot/sendmessage", {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}]
            }
        })
        print(f"已回复 → {to_user_id}")

    async def run(self):
        if not self.token:
            await self.login()
        
        self.running = True
        print("🚀 Bot 已启动，开始接收消息...（按 Ctrl+C 停止）")
        
        while self.running:
            await self.poll_messages()
            await asyncio.sleep(0.1)   # 防止 CPU 过高


# ====================== 启动 ======================
async def main():
    bot = ILinkBot()
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n\nBot 已停止")
        bot.save_session()
    except Exception as e:
        print("运行异常:", e)
        bot.save_session()
    finally:
        await bot.client.aclose()

if __name__ == "__main__":
    asyncio.run(main())