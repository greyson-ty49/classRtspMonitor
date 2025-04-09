#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RTSP流录制与分析模块 - Web接口版
-------------------------------
这是原始脚本的修改版，主要变更：
1. 移除了交互式菜单功能
2. 将类和核心功能保留为可导入的模块
3. 添加了线程安全机制以支持Web接口的并发访问
4. 优化了日志记录以适应Web应用环境
"""

import os
import time
import datetime
import subprocess
import logging
import sys
import signal
import json
import requests
import whisper
import threading
import re
from concurrent.futures import ThreadPoolExecutor

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("rtsp_recorder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# 配置参数
class Config:
    # 基本配置
    SEGMENT_DURATION = 300  # 5分钟
    MAX_RETRIES = 3
    RETRY_DELAY = 5
    DEEPSEEK_API_KEY = "sk-271d1b380e2d4aa1b0e1fd7b0412eca6"
    DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
    WHISPER_MODEL = "small"
    MAX_WORKERS_PER_STREAM = 2  # 每个流的工作线程数
    LANGUAGE = "zh"  # 中文
    
    # 根目录
    BASE_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captured_videos")
    
    # 不当言论文件目录
    INAPPROPRIATE_CONTENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inappropriate_contents")
    
    # 配置文件路径
    CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rtsp_config.json")
    
    # RTSP流配置
    RTSP_STREAMS = {}
    
    # 流ID和数字编号的映射
    STREAM_NUMBERS = {}
    
    # 配置锁，防止并发访问和修改
    _config_lock = threading.RLock()
    
    @classmethod
    def add_stream(cls, classroom_id, teacher_name, rtsp_url):
        """添加一个RTSP流配置"""
        with cls._config_lock:
            # 生成流ID
            stream_id = f"{classroom_id}_{teacher_name}"
            
            # 生成流目录
            stream_dir = os.path.join(cls.BASE_OUTPUT_DIR, stream_id)
            
            # 配置流信息
            cls.RTSP_STREAMS[stream_id] = {
                "classroom_id": classroom_id,
                "teacher_name": teacher_name,
                "rtsp_url": rtsp_url,
                "output_dir": stream_dir,
                "status": "stopped",  # stopped, running, error
                "last_error": None,
                "videos_dir": os.path.join(stream_dir, "videos"),
                "audio_dir": os.path.join(stream_dir, "audio"),
                "transcript_dir": os.path.join(stream_dir, "transcripts"),
                "analysis_dir": os.path.join(stream_dir, "analysis")
            }
            
            # 创建必要的目录
            for dir_key in ["videos_dir", "audio_dir", "transcript_dir", "analysis_dir"]:
                os.makedirs(cls.RTSP_STREAMS[stream_id][dir_key], exist_ok=True)
            
            # 分配编号（如果尚未分配）
            cls._update_stream_numbers()
            
            # 保存配置到文件
            cls.save_config()
            
            logger.info(f"添加RTSP流: {stream_id}, URL: {rtsp_url}")
            return stream_id
    
    @classmethod
    def remove_stream(cls, stream_id):
        """移除一个RTSP流配置"""
        with cls._config_lock:
            if stream_id in cls.RTSP_STREAMS:
                del cls.RTSP_STREAMS[stream_id]
                logger.info(f"移除RTSP流: {stream_id}")
                
                # 更新编号
                cls._update_stream_numbers()
                
                # 保存配置到文件
                cls.save_config()
                
                return True
            return False
    
    @classmethod
    def get_stream_by_number(cls, number):
        """根据编号获取流ID"""
        with cls._config_lock:
            for stream_id, num in cls.STREAM_NUMBERS.items():
                if num == int(number):
                    return stream_id
            return None
    
    @classmethod
    def _update_stream_numbers(cls):
        """更新流编号映射"""
        cls.STREAM_NUMBERS = {}
        for i, stream_id in enumerate(cls.RTSP_STREAMS.keys(), 1):
            cls.STREAM_NUMBERS[stream_id] = i
    
    @classmethod
    def save_config(cls):
        """将当前配置保存到JSON文件"""
        with cls._config_lock:
            # 准备保存的配置数据 - 只保存需要持久化的数据
            config_data = {
                "rtsp_streams": {}
            }
            
            # 构建可序列化的流配置
            for stream_id, stream_config in cls.RTSP_STREAMS.items():
                config_data["rtsp_streams"][stream_id] = {
                    "classroom_id": stream_config["classroom_id"],
                    "teacher_name": stream_config["teacher_name"],
                    "rtsp_url": stream_config["rtsp_url"],
                    "status": stream_config["status"],
                    "last_error": stream_config["last_error"]
                }
            
            try:
                with open(cls.CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=4)
                
                logger.info(f"配置已保存到: {cls.CONFIG_FILE}")
            except Exception as e:
                logger.error(f"保存配置文件时出错: {str(e)}")
    
    @classmethod
    def load_config(cls):
        """从JSON文件加载配置"""
        with cls._config_lock:
            if not os.path.exists(cls.CONFIG_FILE):
                logger.info(f"配置文件不存在: {cls.CONFIG_FILE}，使用默认配置")
                return
            
            try:
                with open(cls.CONFIG_FILE, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                
                # 加载RTSP流配置
                if "rtsp_streams" in config_data:
                    # 先清空现有配置
                    cls.RTSP_STREAMS = {}
                    
                    # 加载保存的流配置并重新创建完整配置
                    for stream_id, stream_data in config_data["rtsp_streams"].items():
                        classroom_id = stream_data["classroom_id"]
                        teacher_name = stream_data["teacher_name"]
                        rtsp_url = stream_data["rtsp_url"]
                        
                        # 生成流目录
                        stream_dir = os.path.join(cls.BASE_OUTPUT_DIR, stream_id)
                        
                        # 恢复完整配置
                        cls.RTSP_STREAMS[stream_id] = {
                            "classroom_id": classroom_id,
                            "teacher_name": teacher_name,
                            "rtsp_url": rtsp_url,
                            "output_dir": stream_dir,
                            "status": "stopped",  # 总是从停止状态开始
                            "last_error": None,
                            "videos_dir": os.path.join(stream_dir, "videos"),
                            "audio_dir": os.path.join(stream_dir, "audio"),
                            "transcript_dir": os.path.join(stream_dir, "transcripts"),
                            "analysis_dir": os.path.join(stream_dir, "analysis")
                        }
                        
                        # 确保目录存在
                        for dir_key in ["videos_dir", "audio_dir", "transcript_dir", "analysis_dir"]:
                            os.makedirs(cls.RTSP_STREAMS[stream_id][dir_key], exist_ok=True)
                    
                    # 更新流编号
                    cls._update_stream_numbers()
                    
                    logger.info(f"从配置文件加载了 {len(cls.RTSP_STREAMS)} 个RTSP流")
            
            except Exception as e:
                logger.error(f"加载配置文件时出错: {str(e)}")
                logger.info("使用默认空配置")

# 不当言论管理类
class InappropriateContentManager:
    """集中管理不当言论并按月归档"""
    def __init__(self, base_dir=Config.INAPPROPRIATE_CONTENT_DIR):
        self.base_dir = base_dir
        self.current_file = None
        self.current_month = None
        self.lock = threading.Lock()
        
        # 确保目录存在
        os.makedirs(self.base_dir, exist_ok=True)
        
        # 初始化当前月份文件
        self._ensure_current_file()
    
    def _ensure_current_file(self):
        """确保当前月份的文件存在"""
        current_month = datetime.datetime.now().strftime("%Y%m")
        
        if self.current_month != current_month:
            self.current_month = current_month
            self.current_file = os.path.join(
                self.base_dir, 
                f"inappropriate_content_{current_month}.txt"
            )
            
            # 如果文件不存在，创建并写入标题行
            if not os.path.exists(self.current_file):
                with open(self.current_file, "w", encoding="utf-8") as f:
                    f.write("# 不当言论记录 - {}\n".format(
                        datetime.datetime.now().strftime("%Y年%m月")
                    ))
                    f.write("# 格式：[日期时间] [教室] [教师] [类型] [内容]\n\n")
                logger.info(f"创建新的不当言论记录文件: {self.current_file}")
    
    def add_record(self, classroom_id, teacher_name, content_type, original_text, analysis_result):
        """添加一条不当言论记录"""
        with self.lock:
            # 确保使用当前月份的文件
            self._ensure_current_file()
            
            # 构造记录
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record = f"[{timestamp}] [{classroom_id}] [{teacher_name}] [{content_type}]\n"
            record += f"原文：{original_text[:200]}...\n"  # 截取前200个字符
            record += f"分析：{analysis_result}\n"
            record += "-" * 80 + "\n\n"
            
            # 写入文件
            with open(self.current_file, "a", encoding="utf-8") as f:
                f.write(record)
            
            logger.info(f"已记录不当言论：{classroom_id} - {teacher_name} - {content_type}")
            
            return True
    
    def get_latest_records(self, limit=100):
        """获取最新的不当言论记录"""
        with self.lock:
            self._ensure_current_file()
            
            if not os.path.exists(self.current_file):
                return "暂无不当言论记录"
            
            with open(self.current_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            return content

# RTSP流管理类
class RTSPStreamManager:
    """管理多个RTSP流的录制和处理"""
    def __init__(self):
        # 线程池 - 用于处理视频文件
        self.video_processors = {}
        
        # 录制线程
        self.recording_threads = {}
        
        # 线程停止标志
        self.stop_flags = {}
        
        # 不当言论管理器
        self.inappropriate_manager = InappropriateContentManager()
        
        # 管理器锁
        self.manager_lock = threading.RLock()
    
    def test_rtsp_connection(self, rtsp_url):
        """测试RTSP连接是否可用"""
        logger.info(f"测试RTSP连接: {rtsp_url}")
        
        # 直接使用更简单的测试命令 - 只检查连接，不保存文件
        cmd = [
            "ffmpeg",
            "-i", rtsp_url,
            "-t", "2",  # 只测试2秒
            "-f", "null",  # 输出到null，不保存文件
            "-"  # 标准输出
        ]
        
        try:
            logger.info("正在测试RTSP连接，请稍候...")
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,  # 增加超时时间
                check=False
            )
            
            stderr = result.stderr.decode("utf-8", errors="replace")
            
            # 检查是否检测到流
            if "Stream mapping:" in stderr or "Duration:" in stderr:
                logger.info(f"RTSP连接测试成功: {rtsp_url}")
                return True, "连接成功"
            else:
                logger.warning(f"RTSP连接测试失败: {rtsp_url} - {stderr}")
                return False, f"连接失败: {stderr[:100]}..."
        
        except Exception as e:
            logger.error(f"RTSP连接测试异常: {rtsp_url} - {str(e)}")
            return False, f"连接异常: {str(e)}"
    
    def start_stream(self, stream_id):
        """启动指定的RTSP流监控"""
        with self.manager_lock:
            if stream_id not in Config.RTSP_STREAMS:
                return False, f"未找到指定的流配置: {stream_id}"
            
            stream_config = Config.RTSP_STREAMS[stream_id]
            
            # 如果已经在运行，直接返回成功
            if stream_id in self.recording_threads and self.recording_threads[stream_id].is_alive():
                if stream_config["status"] == "running":
                    return True, "监控已经在运行中"
            
            # 创建视频处理线程池
            self.video_processors[stream_id] = ThreadPoolExecutor(
                max_workers=Config.MAX_WORKERS_PER_STREAM, 
                thread_name_prefix=f"processor-{stream_id}"
            )
            
            # 设置停止标志
            self.stop_flags[stream_id] = False
            
            # 创建并启动录制线程
            thread = threading.Thread(
                target=self._recording_thread,
                args=(stream_id,),
                name=f"recorder-{stream_id}",
                daemon=True
            )
            thread.start()
            
            self.recording_threads[stream_id] = thread
            stream_config["status"] = "running"
            
            # 保存状态变更
            Config.save_config()
            
            logger.info(f"已启动RTSP流监控: {stream_id}")
            return True, "监控已启动"
    
    def stop_stream(self, stream_id):
        """停止指定的RTSP流监控"""
        with self.manager_lock:
            if stream_id not in Config.RTSP_STREAMS:
                return False, f"未找到指定的流配置: {stream_id}"
            
            stream_config = Config.RTSP_STREAMS[stream_id]
            
            # 如果已经停止，直接返回成功
            if stream_id not in self.recording_threads or not self.recording_threads[stream_id].is_alive():
                if stream_config["status"] != "running":
                    return True, "监控已经停止"
            
            # 设置停止标志
            self.stop_flags[stream_id] = True
            stream_config["status"] = "stopping"
            
            logger.info(f"正在停止RTSP流监控: {stream_id}")
            
            # 保存状态变更
            Config.save_config()
            
            return True, "正在停止监控"
    
    def check_stream_status(self):
        """检查所有流的状态并更新配置"""
        with self.manager_lock:
            for stream_id in list(self.recording_threads.keys()):
                if stream_id in Config.RTSP_STREAMS:
                    # 检查线程是否还在运行
                    if not self.recording_threads[stream_id].is_alive():
                        logger.info(f"录制线程已结束: {stream_id}")
                        
                        # 关闭视频处理线程池
                        if stream_id in self.video_processors:
                            self.video_processors[stream_id].shutdown(wait=False)
                            del self.video_processors[stream_id]
                        
                        # 更新状态
                        Config.RTSP_STREAMS[stream_id]["status"] = "stopped"
                        
                        # 移除记录
                        del self.recording_threads[stream_id]
                        if stream_id in self.stop_flags:
                            del self.stop_flags[stream_id]
                        
                        # 保存状态变更
                        Config.save_config()
    
    def _recording_thread(self, stream_id):
        """录制线程的主函数"""
        stream_config = Config.RTSP_STREAMS[stream_id]
        rtsp_url = stream_config["rtsp_url"]
        videos_dir = stream_config["videos_dir"]
        
        segment_number = 1
        retries = 0
        
        logger.info(f"开始录制RTSP流 {stream_id}: {rtsp_url}")
        
        while not self.stop_flags.get(stream_id, True):
            # 生成输出文件名
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(videos_dir, f"{timestamp}.mp4")
            
            # 构建FFmpeg命令
            cmd = [
                "ffmpeg",
                "-i", rtsp_url,
                "-t", str(Config.SEGMENT_DURATION),
                "-c", "copy",
                "-y",
                output_file
            ]
            
            try:
                logger.info(f"开始录制片段 #{segment_number} - {stream_id}")
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=Config.SEGMENT_DURATION + 30,
                    check=False
                )
                
                if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 10000:
                    # 录制成功
                    logger.info(f"成功录制片段 #{segment_number} - {stream_id}")
                    segment_number += 1
                    retries = 0
                    
                    # 提交视频处理任务
                    if stream_id in self.video_processors:
                        self.video_processors[stream_id].submit(
                            self._process_video,
                            stream_id, 
                            output_file
                        )
                else:
                    # 录制失败
                    stderr = result.stderr.decode("utf-8", errors="replace")
                    logger.error(f"录制失败 - {stream_id}: {stderr[:200]}")
                    if os.path.exists(output_file):
                        os.remove(output_file)
                    retries += 1
            
            except Exception as e:
                logger.error(f"录制异常 - {stream_id}: {str(e)}")
                if os.path.exists(output_file):
                    os.remove(output_file)
                retries += 1
            
            # 检查重试次数
            if retries >= Config.MAX_RETRIES:
                logger.error(f"连续失败{retries}次，停止录制 - {stream_id}")
                with Config._config_lock:
                    stream_config["status"] = "error"
                    stream_config["last_error"] = f"连续录制失败{retries}次"
                # 保存错误状态
                Config.save_config()
                break
            
            # 如果失败，等待一段时间再重试
            if retries > 0:
                time.sleep(Config.RETRY_DELAY)
        
        logger.info(f"录制线程结束 - {stream_id}")
        
        # 更新状态为已停止
        with Config._config_lock:
            if stream_id in Config.RTSP_STREAMS and Config.RTSP_STREAMS[stream_id]["status"] != "error":
                Config.RTSP_STREAMS[stream_id]["status"] = "stopped"
        
        # 保存状态变更
        Config.save_config()
    
    def _process_video(self, stream_id, video_file):
        """处理单个视频文件"""
        if stream_id not in Config.RTSP_STREAMS:
            logger.error(f"处理视频时找不到流配置: {stream_id}")
            return False
            
        stream_config = Config.RTSP_STREAMS[stream_id]
        classroom_id = stream_config["classroom_id"]
        teacher_name = stream_config["teacher_name"]
        
        logger.info(f"开始处理视频 - {stream_id}: {video_file}")
        
        # 1. 提取音频
        audio_file = self._extract_audio(stream_id, video_file)
        if not audio_file:
            logger.error(f"无法从视频中提取音频 - {stream_id}: {video_file}")
            return False
        
        # 2. 语音转文字
        text_file = self._speech_to_text(stream_id, audio_file)
        if not text_file:
            logger.error(f"无法将音频转换为文字 - {stream_id}: {audio_file}")
            return False
        
        # 3. 分析文本内容
        has_inappropriate, analysis_file = self._analyze_text(stream_id, text_file)
        
        # 4. 如果存在不当言论，记录到中央文件
        if has_inappropriate and analysis_file:
            # 读取原文和分析结果
            try:
                with open(text_file, "r", encoding="utf-8") as f:
                    original_text = f.read()
                
                with open(analysis_file, "r", encoding="utf-8") as f:
                    analysis_result = f.read()
                
                # 添加记录
                self.inappropriate_manager.add_record(
                    classroom_id,
                    teacher_name,
                    "不当言论",  # 可以从分析结果中提取更具体的类型
                    original_text,
                    analysis_result
                )
                
                logger.info(f"检测到不当言论并记录 - {stream_id}: {os.path.basename(text_file)}")
            except Exception as e:
                logger.error(f"记录不当言论时出错 - {stream_id}: {str(e)}")
        
        logger.info(f"视频处理完成 - {stream_id}: {video_file}")
        return True
    
    def _extract_audio(self, stream_id, video_file):
        """从视频中提取音频"""
        if not os.path.exists(video_file):
            logger.error(f"视频文件不存在: {video_file}")
            return None
        
        stream_config = Config.RTSP_STREAMS[stream_id]
        
        # 生成音频文件名 (保持相同的文件名但更改目录和扩展名)
        base_name = os.path.basename(video_file).replace(".mp4", ".wav")
        audio_file = os.path.join(stream_config["audio_dir"], base_name)
        
        # 构建FFmpeg命令
        cmd = [
            "ffmpeg",
            "-i", video_file,
            "-vn",                  # 禁用视频
            "-acodec", "pcm_s16le", # 使用PCM 16位编码
            "-ar", "16000",         # 16kHz采样率 (适合语音识别)
            "-ac", "1",             # 单声道
            "-y",                   # 覆盖现有文件
            audio_file
        ]
        
        logger.info(f"提取音频 - {stream_id}: {os.path.basename(video_file)}")
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,  # 1分钟超时
                check=False
            )
            
            if result.returncode != 0:
                stderr_output = result.stderr.decode('utf-8', errors='replace')
                logger.error(f"音频提取错误 - {stream_id}: {stderr_output[:200]}")
                return None
            
            if not os.path.exists(audio_file) or os.path.getsize(audio_file) < 1000:
                logger.error(f"提取的音频文件不存在或太小 - {stream_id}: {audio_file}")
                return None
            
            logger.info(f"成功提取音频 - {stream_id}: {os.path.basename(audio_file)}")
            return audio_file
        
        except Exception as e:
            logger.error(f"提取音频时出错 - {stream_id}: {str(e)}")
            return None
    
    def _speech_to_text(self, stream_id, audio_file):
        """使用Whisper进行语音识别"""
        if not os.path.exists(audio_file):
            logger.error(f"音频文件不存在: {audio_file}")
            return None
        
        stream_config = Config.RTSP_STREAMS[stream_id]
        
        # 生成文本输出文件
        base_name = os.path.basename(audio_file).replace(".wav", ".txt")
        text_file = os.path.join(stream_config["transcript_dir"], base_name)
        
        try:
            logger.info(f"使用Whisper处理音频 - {stream_id}: {os.path.basename(audio_file)}")
            
            # 首次运行时会下载模型，可能需要等待一段时间
            model = whisper.load_model(Config.WHISPER_MODEL)
            
            # 使用Whisper转录音频
            result = model.transcribe(
                audio_file,
                language=Config.LANGUAGE,
                verbose=False,
                fp16=False  # 使用FP32以避免某些硬件兼容性问题
            )
            
            # 提取转录文本
            transcript = result["text"]
            
            # 写入文本文件
            with open(text_file, "w", encoding="utf-8") as f:
                f.write(transcript)
            
            logger.info(f"语音识别完成 - {stream_id}: {os.path.basename(text_file)}")
            return text_file
            
        except Exception as e:
            logger.error(f"Whisper语音识别过程中出错 - {stream_id}: {str(e)}")
            
            # 如果出错，创建一个包含错误信息的文本文件
            with open(text_file, "w", encoding="utf-8") as f:
                f.write(f"语音识别失败: {str(e)}\n")
                f.write("请检查Whisper模型安装和音频文件格式。")
            
            return None
    
    def _analyze_text(self, stream_id, text_file):
        """使用DeepSeek API分析文本内容，检测不当言论"""
        if not os.path.exists(text_file):
            logger.error(f"文本文件不存在: {text_file}")
            return False, None
        
        stream_config = Config.RTSP_STREAMS[stream_id]
        
        # 生成分析结果文件名
        base_name = os.path.basename(text_file).replace(".txt", "_analysis.txt")
        analysis_file = os.path.join(stream_config["analysis_dir"], base_name)
        
        # 读取文本内容
        try:
            with open(text_file, "r", encoding="utf-8") as f:
                text_content = f.read()
            
            if not text_content or len(text_content) < 10:
                logger.warning(f"文本内容为空或太短，跳过分析 - {stream_id}: {text_file}")
                return False, None
            
            logger.info(f"分析文本内容 - {stream_id}: {os.path.basename(text_file)}")
            
            # 调用DeepSeek API进行分析
            headers = {
                "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            # 构建提示
            prompt = f"""请分析以下文本内容:
            
{text_content}

请提供以下分析:
1. 文本大纲 (主要内容和结构)
2. 是否包含以下不当言论:
   a) 反动语言
   b) 违反中国法律的言论
   c) 不适合老师在课堂上讲的言论

请以结构化方式提供分析结果。最后，如果检测到上述任何类型的不当言论，请在最后一行明确标记: [包含不当言论:是]，否则标记: [包含不当言论:否]
"""
            
            # 构建API请求数据
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            }
            
            logger.info(f"调用DeepSeek API进行文本分析 - {stream_id}")
            
            # 调用API
            response = requests.post(
                Config.DEEPSEEK_API_URL,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            # 检查响应
            if response.status_code == 200:
                result = response.json()
                analysis_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # 保存分析结果
                with open(analysis_file, "w", encoding="utf-8") as f:
                    f.write(analysis_text)
                
                logger.info(f"文本分析完成 - {stream_id}: {os.path.basename(analysis_file)}")
                
                # 检查是否包含不当言论
                has_inappropriate = False
                
                # 查找标记 [包含不当言论:是]
                if "[包含不当言论:是]" in analysis_text:
                    has_inappropriate = True
                    logger.warning(f"检测到不当言论 - {stream_id}: {os.path.basename(text_file)}")
                
                return has_inappropriate, analysis_file
            else:
                logger.error(f"DeepSeek API调用失败 - {stream_id}: {response.status_code} - {response.text}")
                
                # 创建一个错误报告文件
                error_file = os.path.join(stream_config["analysis_dir"], 
                                         os.path.basename(text_file).replace(".txt", "_analysis_error.txt"))
                with open(error_file, "w", encoding="utf-8") as f:
                    f.write(f"API调用失败 ({response.status_code}): {response.text}")
                
                return False, None
        
        except Exception as e:
            logger.error(f"分析文本内容时出错 - {stream_id}: {str(e)}")
            
            # 创建错误报告文件
            error_file = os.path.join(stream_config["analysis_dir"],
                                     os.path.basename(text_file).replace(".txt", "_analysis_error.txt"))
            with open(error_file, "w", encoding="utf-8") as f:
                f.write(f"文本分析过程中出错: {str(e)}")
            
            return False, None

# 确保基本目录存在
def ensure_directories():
    """确保所有必要的目录结构存在"""
    # 基本输出目录
    os.makedirs(Config.BASE_OUTPUT_DIR, exist_ok=True)
    
    # 不当言论目录
    os.makedirs(Config.INAPPROPRIATE_CONTENT_DIR, exist_ok=True)
    
    # 对于每个已配置的流，确保其目录结构
    for stream_id, config in Config.RTSP_STREAMS.items():
        for dir_key in ["videos_dir", "audio_dir", "transcript_dir", "analysis_dir"]:
            os.makedirs(config[dir_key], exist_ok=True)

# 检查依赖项是否已安装
def check_dependencies():
    """检查依赖项是否已安装"""
    dependencies_ok = True
    
    try:
        import whisper
        logger.info("Whisper库已安装")
    except ImportError:
        logger.error("Whisper库未安装，请运行: pip install openai-whisper")
        dependencies_ok = False
    
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            check=False
        )
        if result.returncode != 0:
            raise Exception("FFmpeg命令返回非零值")
        logger.info("FFmpeg已安装")
    except Exception as e:
        logger.error(f"FFmpeg检查失败: {str(e)}")
        dependencies_ok = False
    
    return dependencies_ok

# 初始化函数
def initialize_system():
    """初始化RTSP监控系统"""
    # 检查依赖项
    if not check_dependencies():
        logger.error("系统依赖项检查失败，某些功能可能无法正常工作")
    
    # 确保目录结构
    ensure_directories()
    
    # 加载配置
    Config.load_config()
    
    logger.info("RTSP监控系统已初始化")

# 当作为独立模块运行时的初始化
if __name__ == "__main__":
    initialize_system()
