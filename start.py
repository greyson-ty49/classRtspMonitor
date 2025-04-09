#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RTSP流监控系统启动脚本
---------------------
这个脚本用于启动RTSP流监控系统的Web界面。
它会执行以下操作：
1. 检查依赖项
2. 初始化目录结构
3. 加载配置
4. 启动Flask Web服务器
"""

import os
import sys
import subprocess
import time
import webbrowser

def check_python_dependencies():
    """检查Python依赖项"""
    try:
        import flask
        import flask_socketio
        import whisper
        import requests
        print("✓ Python依赖项已安装")
        return True
    except ImportError as e:
        print(f"✗ 缺少Python依赖项: {e}")
        print("  请运行: pip install -r requirements.txt")
        return False

def check_ffmpeg():
    """检查FFmpeg是否已安装"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            check=False
        )
        if result.returncode == 0:
            print("✓ FFmpeg已安装")
            return True
        else:
            print("✗ FFmpeg安装检查失败")
            return False
    except Exception:
        print("✗ 未找到FFmpeg")
        print("  请安装FFmpeg并确保它在系统PATH中")
        return False

def create_directories():
    """创建必要的目录结构"""
    try:
        # 检查目录是否存在
        if not os.path.exists("templates"):
            print("✗ 未找到templates目录")
            print("  请确保在正确的目录中运行此脚本")
            return False
        
        # 创建必要的目录
        os.makedirs("captured_videos", exist_ok=True)
        os.makedirs("inappropriate_contents", exist_ok=True)
        
        # 创建配置文件（如果不存在）
        if not os.path.exists("rtsp_config.json"):
            with open("rtsp_config.json", "w", encoding="utf-8") as f:
                f.write('{"rtsp_streams": {}}')
            print("✓ 创建了默认配置文件")
        else:
            print("✓ 配置文件已存在")
        
        print("✓ 目录结构已准备")
        return True
    except Exception as e:
        print(f"✗ 创建目录结构失败: {e}")
        return False

def start_web_server():
    """启动Flask Web服务器"""
    try:
        # 检查app.py是否存在
        if not os.path.exists("app.py"):
            print("✗ 未找到app.py")
            print("  请确保在正确的目录中运行此脚本")
            return False
        
        print("\n" + "="*60)
        print("正在启动RTSP流监控系统Web界面...")
        print("="*60)
        print("请访问: http://localhost:5000")
        print("按Ctrl+C停止服务器")
        print("="*60 + "\n")
        
        # 在新线程中打开浏览器
        def open_browser():
            time.sleep(2)  # 等待服务器启动
            webbrowser.open("http://localhost:5000")
        
        import threading
        browser_thread = threading.Thread(target=open_browser)
        browser_thread.daemon = True
        browser_thread.start()
        
        # 启动Flask应用
        os.system("python app.py")
        
        return True
    except Exception as e:
        print(f"✗ 启动Web服务器失败: {e}")
        return False

def main():
    """主函数"""
    print("\n" + "="*60)
    print("RTSP流监控系统 - 启动检查")
    print("="*60)
    
    # 1. 检查Python依赖项
    if not check_python_dependencies():
        return 1
    
    # 2. 检查FFmpeg
    if not check_ffmpeg():
        choice = input("FFmpeg未找到，是否仍要继续? (y/n): ").lower()
        if choice != 'y':
            return 1
    
    # 3. 创建目录结构
    if not create_directories():
        return 1
    
    # 4. 启动Web服务器
    start_web_server()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
