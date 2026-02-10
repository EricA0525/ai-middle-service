#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试脚本：验证Redis Stream队列系统和API
"""

import sys
import time
import json
import redis
from config import Config

def test_redis_connection():
    """测试Redis连接"""
    print("1️⃣  Testing Redis connection...")
    try:
        client = Config.get_redis_client()
        client.ping()
        print("   ✓ Redis connection successful")
        return client
    except Exception as e:
        print(f"   ✗ Redis connection failed: {e}")
        return None

def test_stream_operations(client):
    """测试Stream操作"""
    print("\n2️⃣  Testing Redis Stream operations...")
    
    try:
        # 清理测试数据
        try:
            client.delete(Config.STREAM_KEY)
            client.delete(Config.ACTIVE_COUNT_KEY)
            client.delete(Config.THRESHOLD_KEY)
        except:
            pass
        
        # 初始化阈值
        client.set(Config.THRESHOLD_KEY, Config.DEFAULT_THRESHOLD)
        client.set(Config.ACTIVE_COUNT_KEY, 0)
        
        # 添加测试任务到Stream
        task_id = "test-task-001"
        task_data = {
            "prompt": "测试提示词",
            "model_name": "Hailuo",
            "model_version": "2.3"
        }
        
        message_id = client.xadd(
            Config.STREAM_KEY,
            {
                "task_id": task_id,
                "task_data": json.dumps(task_data, ensure_ascii=False)
            }
        )
        print(f"   ✓ Added task to stream: {message_id}")
        
        # 读取Stream信息
        stream_info = client.xinfo_stream(Config.STREAM_KEY)
        print(f"   ✓ Stream length: {stream_info.get('length', 0)}")
        
        # 创建任务状态
        task_key = f"{Config.TASK_STATUS_PREFIX}{task_id}"
        client.hset(task_key, mapping={
            "task_id": task_id,
            "status": "queued",
            "created_at": str(int(time.time()))
        })
        print(f"   ✓ Task status created")
        
        # 读取任务状态
        task_status = client.hgetall(task_key)
        print(f"   ✓ Task status: {task_status.get('status')}")
        
        return True
        
    except Exception as e:
        print(f"   ✗ Stream operations failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_concurrency_control(client):
    """测试并发控制"""
    print("\n3️⃣  Testing concurrency control...")
    
    try:
        # 获取当前阈值
        threshold = client.get(Config.THRESHOLD_KEY)
        print(f"   ✓ Current threshold: {threshold}")
        
        # 获取活跃计数
        active_count = client.get(Config.ACTIVE_COUNT_KEY)
        print(f"   ✓ Active count: {active_count}")
        
        # 模拟增加活跃任务
        client.incr(Config.ACTIVE_COUNT_KEY)
        new_count = client.get(Config.ACTIVE_COUNT_KEY)
        print(f"   ✓ After increment: {new_count}")
        
        # 模拟减少活跃任务
        client.decr(Config.ACTIVE_COUNT_KEY)
        final_count = client.get(Config.ACTIVE_COUNT_KEY)
        print(f"   ✓ After decrement: {final_count}")
        
        # 模拟阈值调整
        original_threshold = int(client.get(Config.THRESHOLD_KEY))
        client.set(Config.THRESHOLD_KEY, original_threshold - 2)
        new_threshold = client.get(Config.THRESHOLD_KEY)
        print(f"   ✓ Threshold decreased: {original_threshold} -> {new_threshold}")
        
        # 恢复阈值
        client.set(Config.THRESHOLD_KEY, original_threshold)
        restored_threshold = client.get(Config.THRESHOLD_KEY)
        print(f"   ✓ Threshold restored: {restored_threshold}")
        
        return True
        
    except Exception as e:
        print(f"   ✗ Concurrency control test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def cleanup(client):
    """清理测试数据"""
    print("\n4️⃣  Cleaning up test data...")
    try:
        client.delete(Config.STREAM_KEY)
        client.delete(Config.ACTIVE_COUNT_KEY)
        client.delete(Config.THRESHOLD_KEY)
        client.delete(f"{Config.TASK_STATUS_PREFIX}test-task-001")
        print("   ✓ Test data cleaned up")
    except Exception as e:
        print(f"   ✗ Cleanup failed: {e}")

def main():
    """运行所有测试"""
    print("=" * 60)
    print("AIGC Queue System Test Suite")
    print("=" * 60)
    
    # 测试Redis连接
    client = test_redis_connection()
    if not client:
        print("\n❌ Tests failed: Cannot connect to Redis")
        print("   Make sure Redis is running (docker-compose up redis)")
        sys.exit(1)
    
    # 运行测试
    results = []
    results.append(test_stream_operations(client))
    results.append(test_concurrency_control(client))
    
    # 清理
    cleanup(client)
    
    # 汇总结果
    print("\n" + "=" * 60)
    if all(results):
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
        sys.exit(1)
    print("=" * 60)

if __name__ == "__main__":
    main()
