import asyncio
import json
import logging
import os
import pymysql
from datetime import datetime
from typing import Dict, Set
import websockets
from websockets.server import WebSocketServerProtocol

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 从环境变量读取MySQL数据库配置
DB_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', '远程MySQL服务器IP'),  # 数据库主机
    'user': os.environ.get('MYSQL_USER', 'root'),  # 数据库用户
    'password': os.environ.get('MYSQL_PASSWORD', 'password'),  # 数据库密码
    'db': os.environ.get('MYSQL_DATABASE', 'workshop_db'),  # 数据库名称
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

connected_clients: Set[WebSocketServerProtocol] = set()

# 车间状态存储
# 结构: {workshopId: {isStop, originalMinutes, reportTimestamp, reportTimeStr}}
workshop_status: Dict[str, dict] = {}

# 初始化8个生产线
workshop_names = ["A", "B", "C", "D", 
                  "E", "F", "G", "H"]
for name in workshop_names:
    workshop_status[name] = {
        "workshopId": name,
        "isStop": False,  # 使用布尔值
        "originalMinutes": 0,  # 原始停机时长（分钟）
        "reportTimestamp": None,  # 上报时间戳（秒）
        "reportTimeStr": "未更新"  # 上报时间字符串
    }


def init_database():
    """初始化数据库表"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            # 创建车间状态表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS workshop_status (
                id INT AUTO_INCREMENT PRIMARY KEY,
                workshop_id VARCHAR(10) NOT NULL UNIQUE,
                is_stop TINYINT(1) NOT NULL DEFAULT 0,
                original_minutes INT NOT NULL DEFAULT 0,
                report_timestamp INT,
                report_time_str VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            ''')
            
            # 创建提交历史记录表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS workshop_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                workshop_id VARCHAR(10) NOT NULL,
                is_stop TINYINT(1) NOT NULL DEFAULT 0,
                original_minutes INT NOT NULL DEFAULT 0,
                report_timestamp INT,
                report_time_str VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_workshop_id (workshop_id),
                INDEX idx_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            ''')
            conn.commit()
        conn.close()
        logging.info("数据库初始化完成")
    except Exception as e:
        logging.error(f"数据库初始化失败: {e}")


def load_status_from_db():
    """从数据库加载状态"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM workshop_status")
            results = cursor.fetchall()
            for row in results:
                workshop_status[row['workshop_id']] = {
                    "workshopId": row['workshop_id'],
                    "isStop": bool(row['is_stop']),  
                    "originalMinutes": row['original_minutes'],
                    "reportTimestamp": row['report_timestamp'],
                    "reportTimeStr": row['report_time_str']
                }
        conn.close()
        logging.info("从数据库加载状态完成")
    except Exception as e:
        logging.error(f"从数据库加载状态失败: {e}")


def save_status_to_db(workshop_id: str, status: dict):
    """保存状态到数据库"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            # 使用UPSERT操作
            sql = '''
            INSERT INTO workshop_status 
            (workshop_id, is_stop, original_minutes, report_timestamp, report_time_str)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            is_stop = VALUES(is_stop),
            original_minutes = VALUES(original_minutes),
            report_timestamp = VALUES(report_timestamp),
            report_time_str = VALUES(report_time_str)
            '''
            cursor.execute(sql, (
                workshop_id,
                status['isStop'],
                status['originalMinutes'],
                status['reportTimestamp'],
                status['reportTimeStr']
            ))
            conn.commit()
        conn.close()
        logging.info(f"状态保存到数据库: {workshop_id}")
    except Exception as e:
        logging.error(f"保存状态到数据库失败: {e}")


def save_history_to_db(workshop_id: str, status: dict):
    """保存提交历史记录到数据库"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = '''
            INSERT INTO workshop_history 
            (workshop_id, is_stop, original_minutes, report_timestamp, report_time_str)
            VALUES (%s, %s, %s, %s, %s)
            '''
            cursor.execute(sql, (
                workshop_id,
                status['isStop'],
                status['originalMinutes'],
                status['reportTimestamp'],
                status['reportTimeStr']
            ))
            conn.commit()
        conn.close()
        logging.info(f"历史记录保存到数据库: {workshop_id}")
    except Exception as e:
        logging.error(f"保存历史记录到数据库失败: {e}")


def calculate_remaining_seconds(status: dict) -> int:
    """计算剩余秒数"""
    if not status["isStop"]:  # 使用布尔值判断
        return 0
    
    if status["reportTimestamp"] is None:
        return 0
    
    # 原始时长（秒）
    original_seconds = status["originalMinutes"] * 60
    
    # 已经过去的时间（秒）
    elapsed_seconds = int(datetime.now().timestamp()) - status["reportTimestamp"]
    
    # 剩余时间
    remaining = original_seconds - elapsed_seconds
    
    return max(0, remaining)  # 不小于0


def get_status_with_remaining(status: dict) -> dict:
    """获取包含剩余秒数的状态"""
    remaining_seconds = calculate_remaining_seconds(status)
    
    # 如果剩余时间为0且原本是停机状态，标记为已停机（stopMinutes=0）
    if remaining_seconds == 0 and status["isStop"]:
        return {
            "workshopId": status["workshopId"],
            "isStop": True,
            "stopMinutes": 0,  # 0表示已停机
            "reportTime": status["reportTimeStr"]
        }
    else:
        # 返回剩余秒数（不再转换为分钟）
        return {
            "workshopId": status["workshopId"],
            "isStop": status["isStop"],
            "stopMinutes": remaining_seconds,  # 直接返回秒数
            "reportTime": status["reportTimeStr"]
        }


async def broadcast_message(message: dict, exclude_client: WebSocketServerProtocol = None):
    """广播消息给所有连接的客户端"""
    if not connected_clients:
        return
    
    message_json = json.dumps(message, ensure_ascii=False)
    tasks = []
    
    for client in connected_clients:
        if client != exclude_client:
            tasks.append(client.send(message_json))
    
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        logging.info(f"广播消息给 {len(tasks)} 个客户端")


async def handle_message(websocket: WebSocketServerProtocol, message_str: str):
    """处理客户端发来的消息"""
    try:
        data = json.loads(message_str)
        workshop_id = data.get("workshopId")
        is_stop = data.get("isStop")
        stop_minutes = data.get("stopMinutes", 0)
        report_time_str = data.get("reportTime", datetime.now().strftime("%Y/%m/%d %H:%M:%S"))
        
        logging.info(f"收到消息: 车间={workshop_id}, 是否停机={is_stop}, 停机时长={stop_minutes}分钟")
        
        if workshop_id:
            # 存储原始数据
            workshop_status[workshop_id] = {
                "workshopId": workshop_id,
                "isStop": is_stop,
                "originalMinutes": stop_minutes,
                "reportTimestamp": int(datetime.now().timestamp()),
                "reportTimeStr": report_time_str
            }
            
            # 保存到数据库（最新状态）
            save_status_to_db(workshop_id, workshop_status[workshop_id])
            
            # 保存到历史记录表（每一次提交）
            save_history_to_db(workshop_id, workshop_status[workshop_id])
            
            # 广播时返回剩余时间
            broadcast_data = get_status_with_remaining(workshop_status[workshop_id])
            await broadcast_message(broadcast_data, exclude_client=websocket)
            
            logging.info(f"更新车间状态: {workshop_id} -> {is_stop}, 剩余{stop_minutes}分钟")
        
    except json.JSONDecodeError as e:
        logging.error(f"JSON解析错误: {e}")
    except Exception as e:
        logging.error(f"处理消息时出错: {e}")


async def handle_client(websocket: WebSocketServerProtocol, path: str = None):
    """处理客户端连接"""
    client_addr = websocket.remote_address
    logging.info(f"新客户端连接: {client_addr}")
    
    connected_clients.add(websocket)
    
    try:
        # 发送所有车间的当前状态（包含剩余时间）
        for workshop_id, status in workshop_status.items():
            init_message = get_status_with_remaining(status)
            await websocket.send(json.dumps(init_message, ensure_ascii=False))
        
        # 监听客户端消息
        async for message in websocket:
            await handle_message(websocket, message)
            
    except websockets.exceptions.ConnectionClosed:
        logging.info(f"客户端断开连接: {client_addr}")
    except Exception as e:
        logging.error(f"客户端连接错误: {e}")
    finally:
        connected_clients.discard(websocket)
        logging.info(f"当前连接数: {len(connected_clients)}")


async def main():
    """启动WebSocket服务器"""
    # 初始化数据库
    init_database()
    # 从数据库加载状态
    load_status_from_db()
    
    host = "0.0.0.0"
    port = 5680
    
    logging.info(f"WebSocket服务器启动中...")
    logging.info(f"监听地址: ws://{host}:{port}/ws")
    logging.info(f"按 Ctrl+C 停止服务器")
    
    async with websockets.serve(handle_client, host, port):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("服务器已停止")
