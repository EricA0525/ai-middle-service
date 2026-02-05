"""
端到端测试 - 品牌健康度分析（第二版）
"""
import httpx
import json
import time
import sys
sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:8000/api/v1"


def main():
    # 1. 提交品牌健康度分析任务
    print("1. Submitting brand health task...")
    response = httpx.post(
        f"{BASE_URL}/brand-health",
        json={
            "brand_name": "索尼",
            "category": "耳机",  # 新增：指定品类
            "region": "中国大陆",
            "competitors": ["Bose", "Apple AirPods"]
        },
        timeout=30
    )
    print(f"   Status: {response.status_code}")
    data = response.json()
    print(f"   Response: {json.dumps(data, ensure_ascii=False, indent=2)}")

    task_id = data.get("data", {}).get("task_id")
    if not task_id:
        print("   Task ID not found!")
        return

    print(f"   Task ID: {task_id}")

    # 2. 轮询任务状态
    print("\n2. Polling task status...")
    status = None
    task = {}
    report_url = None
    for i in range(60):
        time.sleep(3)
        try:
            status_response = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=10)
            status_data = status_response.json()
            task = status_data.get("data", {})
            status = task.get("status")
            progress = task.get("progress", 0)
            message = task.get("message", "")
            print(f"   [{i+1}] Status: {status}, Progress: {progress}%, Message: {message}")
            
            if status == "completed":
                report_url = task.get("report_url")
                break
            elif status == "failed":
                break
        except Exception as e:
            print(f"   [{i+1}] Error polling: {e}")

    print("\n3. Task result:")
    if status == "completed" and report_url:
        print(f"   Report URL: {report_url}")
        
        # 3. 下载报告
        print("\n4. Downloading report...")
        report_response = httpx.get(f"http://localhost:8000{report_url}", timeout=30)
        print(f"   Status: {report_response.status_code}")
        
        if report_response.status_code == 200:
            html_content = report_response.text
            print(f"   Report length: {len(html_content)} chars")
            print(f"   Report preview (first 500 chars):\n{html_content[:500]}")
            
            # 保存结果
            with open("test_result.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            print("\n   [OK] Report saved to test_result.html")
        else:
            print(f"   [FAIL] Download failed: {report_response.text}")
            
    elif status == "failed":
        print(f"   [FAIL] Error: {task.get('error', 'Unknown error')}")
        print(f"   Details: {task.get('details', 'N/A')}")
    else:
        print(f"   [WARN] Unexpected status: {status}")


if __name__ == "__main__":
    main()
