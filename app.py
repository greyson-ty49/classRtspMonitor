#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RTSP流录制与分析系统 - Web界面
------------------------------
这个Flask应用为RTSP监控系统提供了一个网页界面，使用户能够：
1. 添加新的RTSP流
2. 查看所有已配置的RTSP流
3. 启动或停止单个流监控
4. 一键启动或停止所有流监控
5. 实时查看检测到的不当言论
"""

import os
import json
import time
import threading
import datetime
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_socketio import SocketIO, emit

# 导入现有的RTSP监控系统模块
# 注意：我们只导入需要的类，并做必要的修改以适应Web应用
from rtsp_recorder import Config, RTSPStreamManager, InappropriateContentManager

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("rtsp_web.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# 创建Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = 'rtsp_monitoring_secret_key'
socketio = SocketIO(app, async_mode='threading')

# 初始化RTSP流管理器
stream_manager = RTSPStreamManager()

# 加载配置
Config.load_config()

# 全局变量，用于存储不当言论更新时间戳
last_inappropriate_update = time.time()

# 路由: 主页
@app.route('/')
def index():
    """渲染主页"""
    return render_template('index.html')

# API: 获取所有RTSP流
@app.route('/api/streams', methods=['GET'])
def get_streams():
    """返回所有配置的RTSP流信息"""
    streams_data = []
    
    for stream_id, config in Config.RTSP_STREAMS.items():
        stream_num = Config.STREAM_NUMBERS.get(stream_id, "-")
        streams_data.append({
            'id': stream_id,
            'number': stream_num,
            'classroom_id': config['classroom_id'],
            'teacher_name': config['teacher_name'],
            'rtsp_url': config['rtsp_url'],
            'status': config['status'],
            'last_error': config['last_error']
        })
    
    return jsonify(streams_data)

# API: 添加RTSP流
@app.route('/api/streams', methods=['POST'])
def add_stream():
    """添加新的RTSP流"""
    data = request.json
    classroom_id = data.get('classroom_id')
    teacher_name = data.get('teacher_name')
    rtsp_url = data.get('rtsp_url')
    
    # 验证输入
    if not classroom_id or not teacher_name or not rtsp_url:
        return jsonify({'success': False, 'message': '所有字段都是必填的'})
    
    # 测试RTSP连接
    success, message = stream_manager.test_rtsp_connection(rtsp_url)
    connection_status = {'success': success, 'message': message}
    
    # 如果连接成功或用户选择忽略错误，继续添加流
    if success or data.get('ignore_error'):
        stream_id = Config.add_stream(classroom_id, teacher_name, rtsp_url)
        return jsonify({
            'success': True, 
            'message': f'成功添加RTSP流: {stream_id}',
            'connection_test': connection_status,
            'stream_id': stream_id
        })
    
    # 返回连接测试结果，让前端决定是否继续
    return jsonify({
        'success': False, 
        'message': '连接测试失败',
        'connection_test': connection_status
    })

# API: 启动RTSP流监控
@app.route('/api/streams/<stream_id>/start', methods=['POST'])
def start_stream(stream_id):
    """启动指定的RTSP流监控"""
    success, message = stream_manager.start_stream(stream_id)
    if success:
        socketio.emit('stream_status_change', {
            'stream_id': stream_id,
            'status': 'running'
        })
    
    return jsonify({
        'success': success,
        'message': message
    })

# API: 停止RTSP流监控
@app.route('/api/streams/<stream_id>/stop', methods=['POST'])
def stop_stream(stream_id):
    """停止指定的RTSP流监控"""
    success, message = stream_manager.stop_stream(stream_id)
    if success:
        socketio.emit('stream_status_change', {
            'stream_id': stream_id,
            'status': 'stopped'
        })
    
    return jsonify({
        'success': success,
        'message': message
    })

# API: 启动所有RTSP流监控
@app.route('/api/streams/start-all', methods=['POST'])
def start_all_streams():
    """启动所有RTSP流监控"""
    results = []
    for stream_id in Config.RTSP_STREAMS:
        success, message = stream_manager.start_stream(stream_id)
        results.append({
            'stream_id': stream_id,
            'success': success,
            'message': message
        })
        if success:
            socketio.emit('stream_status_change', {
                'stream_id': stream_id,
                'status': 'running'
            })
    
    return jsonify({
        'success': True,
        'results': results
    })

# API: 停止所有RTSP流监控
@app.route('/api/streams/stop-all', methods=['POST'])
def stop_all_streams():
    """停止所有RTSP流监控"""
    results = []
    for stream_id in Config.RTSP_STREAMS:
        if Config.RTSP_STREAMS[stream_id]["status"] == "running":
            success, message = stream_manager.stop_stream(stream_id)
            results.append({
                'stream_id': stream_id,
                'success': success,
                'message': message
            })
            if success:
                socketio.emit('stream_status_change', {
                    'stream_id': stream_id,
                    'status': 'stopped'
                })
    
    return jsonify({
        'success': True,
        'results': results
    })

# API: 获取不当言论记录
@app.route('/api/inappropriate-content', methods=['GET'])
def get_inappropriate_content():
    """获取不当言论记录"""
    content = stream_manager.inappropriate_manager.get_latest_records()
    return jsonify({
        'content': content
    })

# 定时任务：检查不当言论更新并推送到客户端
def check_inappropriate_content_updates():
    """定期检查不当言论更新并推送到客户端"""
    global last_inappropriate_update
    
    while True:
        try:
            # 检查不当言论文件是否有更新
            file_path = stream_manager.inappropriate_manager.current_file
            if file_path and os.path.exists(file_path):
                file_mtime = os.path.getmtime(file_path)
                
                # 如果文件时间戳比上次检查更新，推送更新
                if file_mtime > last_inappropriate_update:
                    content = stream_manager.inappropriate_manager.get_latest_records()
                    socketio.emit('inappropriate_content_update', {
                        'content': content
                    })
                    last_inappropriate_update = file_mtime
                    logger.info("推送不当言论更新到客户端")
        
        except Exception as e:
            logger.error(f"检查不当言论更新时出错: {str(e)}")
        
        # 每5秒检查一次
        time.sleep(5)

# 启动后台线程
@socketio.on('connect')
def handle_connect():
    """新客户端连接时的处理"""
    # 推送当前所有流状态
    for stream_id, config in Config.RTSP_STREAMS.items():
        emit('stream_status_change', {
            'stream_id': stream_id,
            'status': config['status']
        })
    
    # 推送当前不当言论内容
    content = stream_manager.inappropriate_manager.get_latest_records()
    emit('inappropriate_content_update', {
        'content': content
    })

if __name__ == '__main__':
    # 启动后台线程，监控不当言论更新
    bg_thread = threading.Thread(
        target=check_inappropriate_content_updates,
        daemon=True
    )
    bg_thread.start()
    
    # 启动Flask应用
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
