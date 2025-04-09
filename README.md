# RTSP监控系统Web界面项目总结

## 项目概述
这是一个基于Python的RTSP流监控系统，通过Web界面让用户可以轻松添加、管理和监控多个RTSP流。系统核心功能包括：录制RTSP视频流、提取音频、使用Whisper进行语音识别、利用DeepSeek API分析内容检测不当言论，并实时展示结果。项目将原有的命令行工具转换为功能完善的Web应用程序，使非技术用户也能方便操作。

## 项目目录结构

### 根目录
- `app.py` - Flask Web应用主程序
- `rtsp_recorder.py` - RTSP录制和分析核心模块
- `rtsp_config.json` - 配置文件(UTF-8编码)
- `requirements.txt` - Python依赖项列表
- `rtsp_recorder.log` - 核心功能日志
- `rtsp_web.log` - Web界面日志

### templates目录
- `index.html` - 主页面模板

### static目录
- `css/` - CSS样式文件目录
- `js/` - JavaScript脚本目录

### captured_videos目录
每个stream_id都有以下子目录结构：
- `videos/` - 录制的视频片段
- `audio/` - 提取的音频文件
- `transcripts/` - 语音识别结果
- `analysis/` - 内容分析结果

### inappropriate_contents目录
- `inappropriate_content_YYYYMM.txt` - 按月归档的不当言论


## 技术栈

### 后端：
- Flask - Web框架
- Flask-SocketIO - WebSocket通信支持
- Threading - 多线程处理
- FFmpeg - 视频处理和音频提取
- Whisper - OpenAI开源语音识别模型
- DeepSeek API - 文本内容分析

### 前端：
- Bootstrap - 响应式UI框架
- JavaScript/jQuery - 客户端交互
- WebSocket - 实时状态更新
- HTML5/CSS3 - 页面结构和样式

## 功能详解

### 1. RTSP流管理
- 添加RTSP流：用户可通过Web界面输入教室ID、教师姓名和RTSP地址添加新流
- 连接测试：自动测试RTSP连接可用性
- 监控控制：支持单独启动/停止每个流或批量操作所有流
- 状态显示：实时显示每个流的运行状态(运行中/已停止/错误)

### 2. 视频处理流程
- 分段录制：每5分钟(可配置)保存一个视频片段
- 音频提取：从视频中提取音频用于语音识别
- 语音识别：使用Whisper模型将语音转为文本
- 内容分析：使用DeepSeek API分析文本内容，检测不当言论
- 结果归档：检测到的不当言论集中管理并按月归档

### 3. 实时界面
- 左侧面板：添加流表单和不当言论实时显示
- 右侧面板：流列表管理和批量操作按钮
- WebSocket通信：流状态变更和不当言论检测实时更新
- 响应式设计：适配不同屏幕尺寸的设备

## 关键技术实现

### 多线程处理
系统使用Python的threading模块实现多线程并发处理多个RTSP流，每个流有独立的录制线程和处理线程池。使用线程锁(RLock)确保关键数据的线程安全性。

```python
# 创建并启动录制线程
thread = threading.Thread(
    target=self._recording_thread,
    args=(stream_id,),
    name=f"recorder-{stream_id}",
    daemon=True
)
thread.start()
```

### 视频处理
使用FFmpeg命令行工具进行视频录制和音频提取，通过Python的subprocess模块调用：

```python
# 录制RTSP流片段
cmd = [
    "ffmpeg",
    "-i", rtsp_url,
    "-t", str(Config.SEGMENT_DURATION),
    "-c", "copy",
    "-y",
    output_file
]
```

### WebSocket实时通信
使用Flask-SocketIO实现服务器与客户端的实时双向通信，当流状态变更或检测到新的不当言论时推送更新：

```python
# 推送流状态变更
socketio.emit('stream_status_change', {
    'stream_id': stream_id,
    'status': 'running'
})
```

### API集成
系统集成了DeepSeek API进行文本内容分析，并处理可能的网络超时问题：

```python
# 调用DeepSeek API
response = requests.post(
    Config.DEEPSEEK_API_URL,
    headers=headers,
    json=payload,
    timeout=30  # 可增加为60-90秒以减少超时问题
)
```

## 配置与性能优化

### 关键配置参数
- SEGMENT_DURATION: 视频分段时长(秒)
- MAX_WORKERS_PER_STREAM: 每个流的工作线程数
- WHISPER_MODEL: Whisper模型大小(tiny/base/small/medium/large)
- RETRY_DELAY: 录制失败重试间隔时间

## 部署要求

### 系统要求
- Python 3.8+
- FFmpeg安装并添加到系统PATH
- 稳定的网络连接(尤其是调用DeepSeek API时)
- 足够的存储空间用于视频文件

### 依赖安装
```bash
# 推荐使用--trusted-host解决SSL证书问题
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# 安装simple-websocket提高WebSocket性能
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org simple-websocket
```

## 运行与维护

### 启动系统
默认情况下，Web界面将在 http://localhost:5000 可访问。

### 常见问题与解决方案
1. WebSocket警告：安装simple-websocket包可解决
2. DeepSeek API超时：增加timeout参数并实现重试逻辑
3. 配置文件编码问题：确保使用UTF-8编码保存配置文件
4. FFmpeg未找到：检查FFmpeg是否正确安装并添加到PATH
