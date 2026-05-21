# Backend API Protocol

This plugin communicates with the backend gateway via HTTP JSON APIs. Developers integrating with their own backend need to implement the following interfaces.

All endpoints use `POST` with JSON request and response bodies.

## Common Request Headers

| Header | Description |
| --- | --- |
| `Content-Type` | `application/json` |
| `AuthorizationType` | Fixed value: `ilink_bot_token` |
| `Authorization` | `Bearer <token>` (obtained after login) |
| `X-WECHAT-UIN` | Base64-encoded random `uint32` |

## Endpoint List

| Endpoint | Path | Description |
| --- | --- | --- |
| `getUpdates` | `getupdates` | Long-poll for new messages |
| `sendMessage` | `sendmessage` | Send a message (text/image/video/file) |
| `getUploadUrl` | `getuploadurl` | Get a CDN upload pre-signed URL |
| `getConfig` | `getconfig` | Get account config (typing ticket, etc.) |
| `sendTyping` | `sendtyping` | Send or cancel the typing status indicator |

## Endpoints

### `getUpdates`

Long-polling endpoint. The server responds when new messages arrive or when the request times out.

#### Request Body

```json
{
  "get_updates_buf": ""
}
```

| Field | Type | Description |
| --- | --- | --- |
| `get_updates_buf` | `string` | Sync cursor from the previous response. Use an empty string for the first request. |

#### Response Body

```json
{
  "ret": 0,
  "msgs": [],
  "get_updates_buf": "<new cursor>",
  "longpolling_timeout_ms": 35000
}
```

| Field | Type | Description |
| --- | --- | --- |
| `ret` | `number` | Return code. `0` means success. |
| `errcode` | `number?` | Error code, for example `-14` for session timeout. |
| `errmsg` | `string?` | Error description. |
| `msgs` | `WeixinMessage[]` | Message list. See [Message Structure](#message-structure). |
| `get_updates_buf` | `string` | New sync cursor to pass in the next request. |
| `longpolling_timeout_ms` | `number?` | Server-suggested long-poll timeout for the next request, in milliseconds. |

### `sendMessage`

Send a message to a user.

#### Request Body

```json
{
  "msg": {
    "to_user_id": "<target user ID>",
    "context_token": "<conversation context token>",
    "item_list": [
      {
        "type": 1,
        "text_item": {
          "text": "Hello"
        }
      }
    ]
  }
}
```

### `getUploadUrl`

Get CDN upload pre-signed parameters. Call this endpoint before uploading a file to obtain `upload_param` and `thumb_upload_param`.

#### Request Body

```json
{
  "filekey": "<file identifier>",
  "media_type": 1,
  "to_user_id": "<target user ID>",
  "rawsize": 12345,
  "rawfilemd5": "<plaintext MD5>",
  "filesize": 12352,
  "thumb_rawsize": 1024,
  "thumb_rawfilemd5": "<thumbnail plaintext MD5>",
  "thumb_filesize": 1040
}
```

| Field | Type | Description |
| --- | --- | --- |
| `media_type` | `number` | `1` = IMAGE, `2` = VIDEO, `3` = FILE |
| `rawsize` | `number` | Original file plaintext size. |
| `rawfilemd5` | `string` | Original file plaintext MD5. |
| `filesize` | `number` | Ciphertext size after AES-128-ECB encryption. |
| `thumb_rawsize` | `number?` | Thumbnail plaintext size. Required for IMAGE and VIDEO. |
| `thumb_rawfilemd5` | `string?` | Thumbnail plaintext MD5. Required for IMAGE and VIDEO. |
| `thumb_filesize` | `number?` | Thumbnail ciphertext size. Required for IMAGE and VIDEO. |

#### Response Body

```json
{
  "upload_param": "<original image upload encrypted parameters>",
  "thumb_upload_param": "<thumbnail upload encrypted parameters>"
}
```

### `getConfig`

Get account configuration, including the typing ticket.

#### Request Body

```json
{
  "ilink_user_id": "<user ID>",
  "context_token": "<optional, conversation context token>"
}
```

#### Response Body

```json
{
  "ret": 0,
  "typing_ticket": "<base64-encoded typing ticket>"
}
```

### `sendTyping`

Send or cancel the typing status indicator.

#### Request Body

```json
{
  "ilink_user_id": "<user ID>",
  "typing_ticket": "<obtained from getConfig>",
  "status": 1
}
```

| Field | Type | Description |
| --- | --- | --- |
| `status` | `number` | `1` = typing, `2` = cancel typing |

## Message Structure

### `WeixinMessage`

| Field | Type | Description |
| --- | --- | --- |
| `seq` | `number?` | Message sequence number. |
| `message_id` | `number?` | Unique message ID. |
| `from_user_id` | `string?` | Sender ID. |
| `to_user_id` | `string?` | Receiver ID. |
| `create_time_ms` | `number?` | Creation timestamp, in milliseconds. |
| `session_id` | `string?` | Session ID. |
| `message_type` | `number?` | `1` = USER, `2` = BOT |
| `message_state` | `number?` | `0` = NEW, `1` = GENERATING, `2` = FINISH |
| `item_list` | `MessageItem[]?` | Message content list. |
| `context_token` | `string?` | Conversation context token. This must be passed back when replying. |

### `MessageItem`

| Field | Type | Description |
| --- | --- | --- |
| `type` | `number` | `1` = TEXT, `2` = IMAGE, `3` = VOICE, `4` = FILE, `5` = VIDEO |
| `text_item` | `{ text: string }?` | Text content. |
| `image_item` | `ImageItem?` | Image, with CDN reference and AES key. |
| `voice_item` | `VoiceItem?` | Voice, SILK encoded. |
| `file_item` | `FileItem?` | File attachment. |
| `video_item` | `VideoItem?` | Video. |
| `ref_msg` | `RefMessage?` | Referenced message. |

## CDN Media Reference (`CDNMedia`)

All media types (image/voice/file/video) are transferred via CDN using AES-128-ECB encryption.

| Field | Type | Description |
| --- | --- | --- |
| `encrypt_query_param` | `string?` | Encrypted parameters for CDN download/upload. |
| `aes_key` | `string?` | Base64-encoded AES-128 key. |

## CDN Upload Flow

1. Calculate the file's plaintext size, MD5, and ciphertext size after AES-128-ECB encryption.
2. If a thumbnail is needed (image/video), calculate the thumbnail's plaintext and ciphertext parameters as well.
3. Call `getUploadUrl` to get `upload_param` and, when applicable, `thumb_upload_param`.
4. Encrypt the file content with AES-128-ECB and upload it to the CDN URL using `PUT`.
5. Encrypt and upload the thumbnail in the same way.
6. Use the returned `encrypt_query_param` to construct a `CDNMedia` reference, include it in the `MessageItem`, and send the message.

---

# 后端 API 协议

该插件通过 HTTP JSON API 与后端网关通信。开发者如果需要接入自己的后端，需要实现以下接口。

所有接口都使用 `POST` 方法，请求体和响应体均为 JSON。

## 通用请求头

| 请求头 | 说明 |
| --- | --- |
| `Content-Type` | `application/json` |
| `AuthorizationType` | 固定值：`ilink_bot_token` |
| `Authorization` | `Bearer <token>`，登录后获取 |
| `X-WECHAT-UIN` | Base64 编码的随机 `uint32` |

## 接口列表

| 接口 | 路径 | 说明 |
| --- | --- | --- |
| `getUpdates` | `getupdates` | 通过长轮询获取新消息 |
| `sendMessage` | `sendmessage` | 发送消息，支持文本、图片、视频和文件 |
| `getUploadUrl` | `getuploadurl` | 获取 CDN 上传预签名 URL |
| `getConfig` | `getconfig` | 获取账号配置，例如正在输入状态票据 |
| `sendTyping` | `sendtyping` | 发送或取消正在输入状态 |

## 接口说明

### `getUpdates`

长轮询接口。当有新消息到达或请求超时时，服务端返回响应。

#### 请求体

```json
{
  "get_updates_buf": ""
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `get_updates_buf` | `string` | 上一次响应返回的同步游标。首次请求传空字符串。 |

#### 响应体

```json
{
  "ret": 0,
  "msgs": [],
  "get_updates_buf": "<new cursor>",
  "longpolling_timeout_ms": 35000
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ret` | `number` | 返回码。`0` 表示成功。 |
| `errcode` | `number?` | 错误码，例如 `-14` 表示会话超时。 |
| `errmsg` | `string?` | 错误描述。 |
| `msgs` | `WeixinMessage[]` | 消息列表。见 [消息结构](#消息结构)。 |
| `get_updates_buf` | `string` | 新的同步游标，下次请求时传入。 |
| `longpolling_timeout_ms` | `number?` | 服务端建议的下一次长轮询超时时间，单位为毫秒。 |

### `sendMessage`

向用户发送消息。

#### 请求体

```json
{
  "msg": {
    "to_user_id": "<target user ID>",
    "context_token": "<conversation context token>",
    "item_list": [
      {
        "type": 1,
        "text_item": {
          "text": "Hello"
        }
      }
    ]
  }
}
```

### `getUploadUrl`

获取 CDN 上传预签名参数。上传文件前需要先调用该接口，获取 `upload_param` 和 `thumb_upload_param`。

#### 请求体

```json
{
  "filekey": "<file identifier>",
  "media_type": 1,
  "to_user_id": "<target user ID>",
  "rawsize": 12345,
  "rawfilemd5": "<plaintext MD5>",
  "filesize": 12352,
  "thumb_rawsize": 1024,
  "thumb_rawfilemd5": "<thumbnail plaintext MD5>",
  "thumb_filesize": 1040
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `media_type` | `number` | `1` = 图片，`2` = 视频，`3` = 文件 |
| `rawsize` | `number` | 原始文件明文大小。 |
| `rawfilemd5` | `string` | 原始文件明文 MD5。 |
| `filesize` | `number` | AES-128-ECB 加密后的密文大小。 |
| `thumb_rawsize` | `number?` | 缩略图明文大小。图片和视频必填。 |
| `thumb_rawfilemd5` | `string?` | 缩略图明文 MD5。图片和视频必填。 |
| `thumb_filesize` | `number?` | 缩略图密文大小。图片和视频必填。 |

#### 响应体

```json
{
  "upload_param": "<original image upload encrypted parameters>",
  "thumb_upload_param": "<thumbnail upload encrypted parameters>"
}
```

### `getConfig`

获取账号配置，包括正在输入状态票据。

#### 请求体

```json
{
  "ilink_user_id": "<user ID>",
  "context_token": "<optional, conversation context token>"
}
```

#### 响应体

```json
{
  "ret": 0,
  "typing_ticket": "<base64-encoded typing ticket>"
}
```

### `sendTyping`

发送或取消正在输入状态。

#### 请求体

```json
{
  "ilink_user_id": "<user ID>",
  "typing_ticket": "<obtained from getConfig>",
  "status": 1
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | `number` | `1` = 正在输入，`2` = 取消正在输入 |

## 消息结构

### `WeixinMessage`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `seq` | `number?` | 消息序列号。 |
| `message_id` | `number?` | 唯一消息 ID。 |
| `from_user_id` | `string?` | 发送方 ID。 |
| `to_user_id` | `string?` | 接收方 ID。 |
| `create_time_ms` | `number?` | 创建时间戳，单位为毫秒。 |
| `session_id` | `string?` | 会话 ID。 |
| `message_type` | `number?` | `1` = 用户，`2` = 机器人 |
| `message_state` | `number?` | `0` = 新消息，`1` = 生成中，`2` = 完成 |
| `item_list` | `MessageItem[]?` | 消息内容列表。 |
| `context_token` | `string?` | 会话上下文令牌。回复时必须原样传回。 |

### `MessageItem`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `type` | `number` | `1` = 文本，`2` = 图片，`3` = 语音，`4` = 文件，`5` = 视频 |
| `text_item` | `{ text: string }?` | 文本内容。 |
| `image_item` | `ImageItem?` | 图片，包含 CDN 引用和 AES 密钥。 |
| `voice_item` | `VoiceItem?` | 语音，SILK 编码。 |
| `file_item` | `FileItem?` | 文件附件。 |
| `video_item` | `VideoItem?` | 视频。 |
| `ref_msg` | `RefMessage?` | 引用消息。 |

## CDN 媒体引用（`CDNMedia`）

所有媒体类型（图片、语音、文件、视频）都通过 CDN 传输，并使用 AES-128-ECB 加密。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `encrypt_query_param` | `string?` | CDN 下载或上传使用的加密参数。 |
| `aes_key` | `string?` | Base64 编码的 AES-128 密钥。 |

## CDN 上传流程

1. 计算文件明文大小、MD5，以及 AES-128-ECB 加密后的密文大小。
2. 如果需要缩略图（图片或视频），也要计算缩略图的明文和密文参数。
3. 调用 `getUploadUrl` 获取 `upload_param`，如适用也获取 `thumb_upload_param`。
4. 使用 AES-128-ECB 加密文件内容，并通过 `PUT` 上传到 CDN URL。
5. 使用相同方式加密并上传缩略图。
6. 使用返回的 `encrypt_query_param` 构造 `CDNMedia` 引用，将其放入 `MessageItem` 后发送消息。
