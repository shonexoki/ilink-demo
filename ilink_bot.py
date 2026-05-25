import asyncio
import json
import time
import uuid
import base64
import hashlib
import os
from io import BytesIO
from urllib.parse import quote
import httpx
from typing import Dict, List, Optional, Tuple
import qrcode
from PIL import Image
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend


class ILinkBot:
    BASE_URL = "https://ilinkai.weixin.qq.com"
    CDN_BASE = "https://novac2c.cdn.weixin.qq.com"
    SESSION_FILE = "ilink_bot_session.json"
    DOWNLOAD_DIR = "downloads"

    MEDIA_TYPE_IMAGE = 1
    MEDIA_TYPE_VIDEO = 2
    MEDIA_TYPE_FILE = 3

    ITEM_TYPE_TEXT = 1
    ITEM_TYPE_IMAGE = 2
    ITEM_TYPE_FILE = 4

    MESSAGE_TYPE_BOT = 2
    MESSAGE_STATE_FINISH = 2
    ENCRYPT_TYPE_AES_ECB = 1
    
    def __init__(self):
        self.token: Optional[str] = None
        self.account_id: Optional[str] = None
        self.cursor: str = ""
        self.client = httpx.AsyncClient(timeout=60.0)
        self.running = False
        os.makedirs(self.DOWNLOAD_DIR, exist_ok=True)
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

    def _decode_aes_key(self, key_str: str) -> bytes:
        """统一处理三种 AES Key 格式"""
        if not key_str:
            raise ValueError("AES Key 为空")
        
        # 1. 如果是32位hex字符串（最常见于image_item.aeskey）
        if len(key_str) == 32 and all(c in '0123456789abcdefABCDEF' for c in key_str):
            return bytes.fromhex(key_str)
        
        # 2. Base64 解码
        try:
            decoded = base64.b64decode(key_str)
            if len(decoded) == 16:
                return decoded
            # 如果是 base64(hex) 格式，再转一次
            if len(decoded) == 32 and all(c in b'0123456789abcdefABCDEF' for c in decoded):
                return bytes.fromhex(decoded.decode())
        except:
            pass
        
        raise ValueError(f"无法解析 AES Key: {key_str}")

    def _decrypt_aes_ecb(self, ciphertext: bytes, key: bytes) -> bytes:
        """AES-128-ECB 解密 + PKCS7 去填充"""
        if len(key) != 16:
            raise ValueError("AES Key 长度必须为16字节")
        
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(ciphertext) + decryptor.finalize()
        
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(padded_data) + unpadder.finalize()

    async def download_file(self, image_item: Dict, msg_id: str = "") -> Optional[str]:
        """下载并解密文件，返回本地保存路径"""
        try:
            aeskey_str = image_item.get("media", {}).get("aes_key")
            media = image_item.get("media") or {}
            
            if not aeskey_str:
                print("⚠️ 文件缺少 aeskey")
                return None
            
            aes_key = self._decode_aes_key(aeskey_str)
            download_url = media.get("full_url") or media.get("url")
            encrypted_param = media.get("encrypt_query_param")
            
            if not download_url:
                print("⚠️ 文件缺少下载链接")
                return None

            # 下载加密数据
            headers = {"User-Agent": "ilink-bot-client"}
            if encrypted_param:
                download_url = f"https://novac2c.cdn.weixin.qq.com/c2c/download?encrypted_query_param={encrypted_param}"
            
            resp = await self.client.get(download_url, headers=headers)
            resp.raise_for_status()
            
            # 解密
            plain_data = self._decrypt_aes_ecb(resp.content, aes_key)
            
            # 保存文件
            original_filename = image_item.get("file_name")
            suffix = ".jpg"
            if original_filename:
                print(f"原始文件名: {original_filename}")
                suffix = os.path.splitext(original_filename)[1] if original_filename else ""
            filename = f"file_{int(time.time())}_{msg_id[-8:]}{suffix}"
            filepath = os.path.join(self.DOWNLOAD_DIR, filename)
            
            with open(filepath, "wb") as f:
                f.write(plain_data)
            
            print(f"✅ 文件已保存: {filepath} ({len(plain_data)/1024:.1f} KB)")
            return filepath
            
        except Exception as e:
            print(f"❌ 下载/解密文件失败: {e}")
            return None

    # ====================== 新增：AES 加密 ======================
    def _encrypt_aes_ecb(self, data: bytes, key: bytes) -> bytes:
        """AES-128-ECB 加密 + PKCS7 填充"""
        if len(key) != 16:
            raise ValueError("AES Key 必须为16字节")
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        encryptor = cipher.encryptor()
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data) + padder.finalize()
        return encryptor.update(padded_data) + encryptor.finalize()

    def _generate_aes_key(self) -> Tuple[bytes, str]:
        """生成随机 AES Key，返回原始字节和 hex 字符串。"""
        key_bytes = os.urandom(16)
        return key_bytes, key_bytes.hex()

    def _encode_aes_key_for_message(self, aes_key_hex: str) -> str:
        """按当前后端兼容格式编码消息体中的 AES Key。"""
        if not aes_key_hex:
            raise ValueError("AES Key 不能为空")
        return base64.b64encode(aes_key_hex.encode("utf-8")).decode("utf-8")

    def _build_image_thumbnail(self, file_path: str) -> bytes:
        """生成 JPEG 缩略图字节。"""
        with Image.open(file_path) as img:
            img.thumbnail((320, 320), Image.Resampling.LANCZOS)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85, optimize=True)
            return buffer.getvalue()

    # ====================== 上传媒体 ======================
    async def upload_media(self, file_path: str, media_type: int = 1, to_user_id: str = "") -> Dict:
        """加密并上传媒体，返回发送消息所需的媒体描述。"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)
        if media_type not in (self.MEDIA_TYPE_IMAGE, self.MEDIA_TYPE_VIDEO, self.MEDIA_TYPE_FILE):
            raise ValueError(f"不支持的 media_type: {media_type}")
        if not to_user_id:
            raise ValueError("to_user_id 不能为空")

        with open(file_path, "rb") as f:
            raw_data = f.read()

        file_name = os.path.basename(file_path)
        raw_size = len(raw_data)
        raw_md5 = hashlib.md5(raw_data).hexdigest()
        
        filekey = os.urandom(16).hex()

        aes_key_bytes, aes_key_hex = self._generate_aes_key()
        enc_data = self._encrypt_aes_ecb(raw_data, aes_key_bytes)
        enc_size = len(enc_data)

        payload = {
            "filekey": filekey,
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": raw_size,
            "rawfilemd5": raw_md5,
            "filesize": enc_size,
            "aeskey": aes_key_hex,
            "no_need_thumb": True,
        }

        resp = await self._post("/ilink/bot/getuploadurl", payload)
        
        upload_param = resp.get("upload_param")
        upload_full_url = resp.get("upload_full_url")

        if not upload_param and not upload_full_url:
            raise Exception(f"getuploadurl 未返回 upload_param 或 upload_full_url: {resp}")

        # 上传主文件
        main_download_param = await self._cdn_upload(
            filekey=filekey,
            encrypted_data=enc_data,
            upload_param=upload_param,
            upload_full_url=upload_full_url,
            label="主文件"
        )

        # 构造 media_item
        media_item = {
            "media": {
                "encrypt_query_param": main_download_param,
                "aes_key": aes_key_hex,
            }
        }

        if media_type == self.MEDIA_TYPE_IMAGE:
            media_item.update({"mid_size": enc_size, "hd_size": enc_size})
        else:
            media_item["file_name"] = file_name
            media_item["len"] = raw_size

        return media_item

    async def _cdn_upload(self, filekey: str, encrypted_data: bytes, 
                        upload_param: str = None, 
                        upload_full_url: str = None,
                        label: str = "CDN_Upload") -> str:
        """上传加密后的媒体内容到 CDN，返回后续下载所需的加密参数。"""
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                if upload_full_url and str(upload_full_url).strip():
                    cdn_url = str(upload_full_url).strip()
                elif upload_param:
                    safe_param = quote(upload_param)
                    safe_filekey = quote(filekey)
                    cdn_url = (
                        f"{self.CDN_BASE}/c2c/upload"
                        f"?encrypted_query_param={safe_param}"
                        f"&filekey={safe_filekey}"
                    )
                else:
                    raise Exception("缺少 upload_param 或 upload_full_url")

                print(f"📤 {label} 第{attempt}次 | 大小: {len(encrypted_data)/1024:.1f}KB")

                resp = await self.client.post(
                    cdn_url,
                    content=encrypted_data,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "User-Agent": "ilink-bot-client"
                    }
                )

                if resp.status_code >= 400:
                    error_msg = resp.headers.get("x-error-message") or resp.text
                    raise Exception(f"CDN 返回 {resp.status_code}: {error_msg}")

                download_param = (
                    resp.headers.get("x-encrypted-param") or
                    resp.headers.get("encrypted-param") or
                    resp.headers.get("x-download-param")
                )

                if not download_param:
                    raise Exception("CDN 未返回 x-encrypted-param")

                print(f"✅ {label} 上传成功")
                return download_param

            except Exception as e:
                print(f"⚠️ {label} 第{attempt}次失败: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(1.5)
                else:
                    raise

    def _build_message_payload(self, to_user_id: str, item_list: list, context_token: str = "") -> Dict:
        """构造 sendMessage 请求体。"""
        if not to_user_id:
            raise ValueError("to_user_id 不能为空")
        if not item_list:
            raise ValueError("item_list 不能为空")

        msg = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": uuid.uuid4().hex,
            "message_type": self.MESSAGE_TYPE_BOT,
            "message_state": self.MESSAGE_STATE_FINISH,
            "item_list": item_list,
        }
        
        if context_token:
            msg["context_token"] = context_token

        return {"msg": msg}

    async def _send_items(self, to_user_id: str, item_list: List[Dict], context_token: str = ""):
        """按当前后端兼容方式逐条发送 MessageItem。"""
        for item in item_list:
            payload = self._build_message_payload(to_user_id, [item], context_token)
            await self._post("/ilink/bot/sendmessage", payload)

    def _text_item(self, text: str) -> Dict:
        return {"type": self.ITEM_TYPE_TEXT, "text_item": {"text": text}}

    def _prepare_media_for_send(self, media_item: Dict):
        media = media_item.get("media")
        if not media:
            raise ValueError("media_item 缺少 media 字段")

        aes_key_hex = media.get("aes_key", "")
        media["aes_key"] = self._encode_aes_key_for_message(aes_key_hex)
        media["encrypt_type"] = self.ENCRYPT_TYPE_AES_ECB

    # ====================== 发送图片 ======================
    async def send_image(self, to_user_id: str, image_path: str, caption: str = "", context_token: str = ""):
        """发送本地图片"""
        image_item = await self.upload_media(image_path, media_type=self.MEDIA_TYPE_IMAGE, to_user_id=to_user_id)
        self._prepare_media_for_send(image_item)

        items = []
        if caption:
            items.append(self._text_item(caption))
        
        items.append({"type": self.ITEM_TYPE_IMAGE, "image_item": image_item})
        await self._send_items(to_user_id, items, context_token)
            
        print(f"📸 消息（文字/图片）已发送 → {to_user_id}")

    # ====================== 发送文件 ======================
    async def send_file(self, to_user_id: str, file_path: str, caption: str = "", context_token: str = ""):
        """发送任意文件"""
        uploaded = await self.upload_media(file_path, media_type=self.MEDIA_TYPE_FILE, to_user_id=to_user_id)
        self._prepare_media_for_send(uploaded)

        file_item = {
            "media": uploaded["media"],
            "file_name": uploaded["file_name"],
            "len": str(uploaded["len"]),
        }

        items = []
        if caption:
            items.append(self._text_item(caption))
            
        items.append({"type": self.ITEM_TYPE_FILE, "file_item": file_item})
        await self._send_items(to_user_id, items, context_token)

        print(f"📎 文件已发送 → {to_user_id} ({uploaded['file_name']})")

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

        if result.get("ret") != 0 and result.get("ret") is not None:
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

    # ====================== handle_message（增强） ======================
    async def handle_message(self, msg: Dict):
        msg_id = str(msg.get("message_id", ""))
        from_id = msg.get("from_user_id")
        context_token = msg.get("context_token")
        
        text = ""
        image_path = None
        file_path = None
        
        for item in msg.get("item_list", []):
            item_type = item.get("type")
            
            if item_type == 1:   # 文本
                text = item.get("text_item", {}).get("text", "")
            
            elif item_type == 2: # 图片
                print(f"收到图片消息")
                image_path = await self.download_file(item.get("image_item", {}), msg_id)

            elif item_type == 4: # 文件 
                file_path = await self.download_file(item.get("file_item", {}), msg_id)
                print(f"收到文件消息，已保存到: {file_path}")

        if text:
            print(f"收到文本: {text}")
            await self.send_text(from_id, f"已收到：{text}", context_token)
        
        if image_path:
            # await self.send_text(from_id, f"已收到图片:{image_path}", context_token)
            # 示例：echo 发送回去
            await self.send_image(from_id, image_path, "这是你发给我的图片", context_token)

        if file_path:            
            # 示例：echo 发送回去
            await self.send_file(from_id, file_path, "这是你发给我的文件", context_token)

    async def send_text(self, to_user_id: str, text: str, context_token: str):
        await self._send_items(to_user_id, [self._text_item(text)], context_token)
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
