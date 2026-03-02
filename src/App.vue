<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';

// 核心配置：替换为你的服务器局域网IP
// 开发环境使用本机IP，生产环境（Docker）使用相对路径
const WS_URL = import.meta.env.DEV 
    ? 'ws://192.168.121.104:5680/ws' 
    : 'ws://127.0.0.1:80/ws';
// 初始化8个生产线列表（可根据实际名称修改）
const allWorkshops = [
    "A", "B", "C", "D",
    "E", "F", "G", "H"
];

// 响应式数据
const workshopStatusCache = ref<Record<string, { isStop: string; stopSeconds: number; updateTime: string }>>({});
const currentReportWorkshop = ref('');
const stopMinutes = ref(30); // 默认30分钟
const connStatus = ref({ connected: false, message: '未连接到服务器' });

// 格式化秒数为时分秒
function formatTime(totalSeconds: number): string {
    if (totalSeconds <= 0) return '0秒';
    
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    
    const parts: string[] = [];
    if (hours > 0) parts.push(`${hours}小时`);
    if (minutes > 0) parts.push(`${minutes}分`);
    if (seconds > 0 || parts.length === 0) parts.push(`${seconds}秒`);
    
    return parts.join('');
}

// 转换显示名称（A -> 生产线A）
function getDisplayName(code: string): string {
    return `生产线${code}`;
}

// WebSocket连接
let ws: WebSocket | null = null;
let countdownInterval: number | null = null;

// 初始化WebSocket连接
function initWebSocket() {
    ws = new WebSocket(WS_URL);
    
    // 连接成功
    ws.onopen = function() {
        connStatus.value = { connected: true, message: '已连接到服务器，可正常上报/接收状态' };
    };

    // 接收广播消息（更新看板）
    ws.onmessage = function(e) {
        const data = JSON.parse(e.data);
        // 服务端直接返回秒数，直接使用
        const seconds = data.stopMinutes || 0;
        // 更新缓存
        workshopStatusCache.value[data.workshopId] = {
            isStop: data.isStop,
            stopSeconds: seconds,
            updateTime: data.reportTime || new Date().toLocaleString()
        };
    };

    // 连接关闭
    ws.onclose = function() {
        connStatus.value = { connected: false, message: '连接已断开，3秒后自动重连...' };
        setTimeout(initWebSocket, 3000);
    };

    // 连接错误
    ws.onerror = function(error) {
        connStatus.value = { connected: false, message: '连接出错：' + (error as Event).type };
    };
}

// 启动倒计时
function startCountdown() {
    if (countdownInterval) {
        clearInterval(countdownInterval);
    }
    countdownInterval = window.setInterval(() => {
        let hasActiveCountdown = false;
        for (const [workshopId, info] of Object.entries(workshopStatusCache.value)) {
            if (info.isStop === '是' && info.stopSeconds > 0) {
                info.stopSeconds--;
                hasActiveCountdown = true;
                // 当倒计时结束时，标记为已停机
                if (info.stopSeconds === 0) {
                    info.updateTime = new Date().toLocaleString();
                    // 发送到服务器
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        const updateData = {
                            workshopId: workshopId,
                            isStop: '是',
                            stopMinutes: 0,
                            reportTime: info.updateTime
                        };
                        ws.send(JSON.stringify(updateData));
                    }
                }
            }
        }
        // 如果所有倒计时都结束了，停止定时器
        if (!hasActiveCountdown) {
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
            }
        }
    }, 1000); // 每秒更新一次
}

// 上报当前车间停机状态
function reportStatus() {
    // 检查连接状态
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert('⚠️ 服务器未连接，请稍等或刷新页面！');
        return;
    }

    // 直接获取分钟数，默认上报停机
    const minutes = parseInt(stopMinutes.value.toString()) || 0;
    if (minutes < 0) {
        alert('⚠️ 停机时长不能为负数！');
        return;
    }
    if (minutes === 0) {
        if (!confirm('⚠️ 停机时长为0分钟，确定提交吗？')) {
            return;
        }
    }

    // 将分钟转换为秒数
    const seconds = minutes * 60;
    
    // 构造上报数据
    const reportData = {
        workshopId: currentReportWorkshop.value,
        isStop: '是', // 默认上报停机
        stopMinutes: minutes,
        reportTime: new Date().toLocaleString()
    };

    // 发送数据到n8n
    ws.send(JSON.stringify(reportData));
    
    // 友好提示
    const tipMsg = `✅ 上报成功！\n车间：${getDisplayName(currentReportWorkshop.value)}\n今日计划停机\n剩余时长：${minutes}分钟（${seconds}秒）\n时间：${reportData.reportTime}`;
    alert(tipMsg);
    
    // 本地实时更新看板（无需等广播）
    workshopStatusCache.value[currentReportWorkshop.value] = {
        isStop: '是',
        stopSeconds: seconds,
        updateTime: reportData.reportTime
    };

    // 重置表单
    stopMinutes.value = 0;
    
    // 重新启动倒计时
    startCountdown();
}

// 上报已开机状态
function reportStart() {
    // 检查连接状态
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert('⚠️ 服务器未连接，请稍等或刷新页面！');
        return;
    }

    // 构造上报数据
    const reportData = {
        workshopId: currentReportWorkshop.value,
        isStop: '否',
        stopMinutes: 0,
        reportTime: new Date().toLocaleString()
    };

    // 发送数据到n8n
    ws.send(JSON.stringify(reportData));
    
    // 友好提示
    alert(`✅ 上报成功！\n车间：${getDisplayName(currentReportWorkshop.value)}\n已开机恢复生产\n时间：${reportData.reportTime}`);
    
    // 本地实时更新看板（无需等广播）
    workshopStatusCache.value[currentReportWorkshop.value] = {
        isStop: '否',
        stopSeconds: 0,
        updateTime: reportData.reportTime
    };
}

// 生命周期钩子
onMounted(() => {
    // 初始化空缓存，等待服务端发送状态
    allWorkshops.forEach(workshop => {
        workshopStatusCache.value[workshop] = {
            isStop: "否",
            stopSeconds: 0,
            updateTime: "等待服务端同步..."
        };
    });

    // 从URL参数获取当前上报的车间
    const params = new URLSearchParams(window.location.search);
    currentReportWorkshop.value = params.get('workshop') || allWorkshops[0] || '';

    // 初始化WebSocket连接
    initWebSocket();
    
    // 启动倒计时
    startCountdown();
});

onUnmounted(() => {
    if (countdownInterval) {
        clearInterval(countdownInterval);
    }
    if (ws) {
        ws.close();
    }
});
</script>

<template>
    <div class="main-container">
        <!-- 左侧：所有车间停机状态看板 -->
        <div class="board-section">
            <h2>今天你要停机吗</h2>
            <div id="workshopBoard">
                <div 
                    v-for="(info, workshopId) in workshopStatusCache" 
                    :key="workshopId"
                    :class="[
                        'board-item', 
                        info.isStop === '是' 
                            ? (info.stopSeconds > 0 ? 'board-yes' : 'board-stopped') 
                            : 'board-no'
                    ]"
                >
                    <span>{{ getDisplayName(workshopId) }}</span>
                    <div class="board-subtitle">
                        <span v-if="info.isStop === '是'">
                            <span v-if="info.stopSeconds > 0">
                                距离停机还有{{ formatTime(info.stopSeconds) }}
                            </span>
                            <span v-else>
                                已停机
                            </span>
                        </span>
                        <span v-else>
                            无停机计划
                        </span>
                        <span>更新时间：{{ info.updateTime }}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- 右侧：当前车间快速上报 -->
        <div class="report-section">
           
            <!-- 当前车间显示（URL参数自动绑定） -->
            <div class="current-workshop">
                当前车间：{{ getDisplayName(currentReportWorkshop) }}
            </div>
            
            <!-- 上报表单 -->
            <div class="report-form">
                <div class="form-item">
                    <label class="form-label">计划停机剩余时长（分钟）：</label>
                    <input type="number" v-model="stopMinutes" class="form-input" min="0" placeholder="如：30、60、120">
                </div>
            </div>

            <!-- 按钮容器 -->
            <div class="btn-container">
                <!-- 上报按钮 -->
                <button class="report-btn" @click="reportStatus">📤 提交停机时间</button>

                <!-- 已开机按钮（始终显示） -->
                <button 
                    class="report-btn start-btn" 
                    @click="reportStart"
                >
                    🔧 已开机
                </button>
            </div>

            <!-- 连接状态 -->
            <div :class="['conn-status', connStatus.connected ? 'conn-connected' : 'conn-disconnected']">
                {{ connStatus.message }}
            </div>
        </div>
    </div>
</template>

<style scoped>
/* 基础样式 */
.main-container {
  display: flex;
  gap: 20px;
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
  flex-wrap: wrap;
}

/* 左侧看板区域 */
.board-section {
  flex: 2;
  min-width: 300px;
  background: #f9f9f9;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

/* 右侧上报区域 */
.report-section {
  flex: 1;
  min-width: 300px;
  background: #f9f9f9;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

/* 标题样式 */
h2 {
  text-align: center;
  color: #333;
  margin-bottom: 20px;
  font-size: 1.5rem;
}

/* 看板车间项 */
.board-item {
  padding: 15px;
  margin: 10px 0;
  border-radius: 6px;
  color: white;
  font-size: 1.1rem;
}

.board-no { background-color: #4CAF50; } /* 无停机计划 */
.board-yes { background-color: #FF9800; } /* 有停机计划 */
.board-stopped { background-color: #f44336; } /* 已停机 */

.board-subtitle {
  font-size: 0.9rem;
  opacity: 0.9;
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
}

/* 当前车间显示 */
.current-workshop {
  font-size: 1.2rem;
  text-align: center;
  padding: 12px;
  background-color: #e3f2fd;
  border-radius: 6px;
  margin-bottom: 15px;
  color: #1976D2;
  font-weight: bold;
}

/* 上报表单 */
.report-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 15px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 1rem;
  color: #666;
}

.form-select, .form-input {
  padding: 10px;
  font-size: 1rem;
  border: 1px solid #ddd;
  border-radius: 4px;
  outline: none;
  transition: border-color 0.3s;
}

.form-select:focus, .form-input:focus {
  border-color: #2196F3;
}

/* 按钮容器 */
.btn-container {
  display: flex;
  gap: 10px;
  margin-top: 15px;
}

/* 上报按钮 */
.report-btn {
  flex: 1;
  padding: 12px;
  font-size: 1rem;
  border: none;
  border-radius: 4px;
  color: white;
  background-color: #2196F3;
  cursor: pointer;
  transition: background-color 0.3s;
}

.report-btn:hover {
  background-color: #1976D2;
}

/* 已开机按钮 */
.start-btn {
  background-color: #4CAF50;
}

.start-btn:hover {
  background-color: #388E3C;
}

/* 连接状态提示 */
.conn-status {
  text-align: center;
  font-size: 0.9rem;
  margin-top: 15px;
  padding: 8px;
  border-radius: 4px;
}

.conn-connected {
  color: #4CAF50;
  background-color: #e8f5e8;
}

.conn-disconnected {
  color: #f44336;
  background-color: #ffebee;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .main-container {
    flex-direction: column;
  }
  
  .board-section,
  .report-section {
    width: 100%;
  }
}
</style>