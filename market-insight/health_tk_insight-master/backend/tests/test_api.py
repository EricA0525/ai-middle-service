"""
Market Insight Agent - API Tests
=================================
API 接口测试
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


# 创建测试客户端
client = TestClient(app)


class TestHealthCheck:
    """健康检查测试"""
    
    def test_health_check_returns_healthy(self):
        """测试健康检查端点"""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "app_name" in data
        assert "environment" in data


class TestBrandHealthAPI:
    """品牌健康度诊断 API 测试"""
    
    def test_create_task_success(self):
        """测试成功创建任务"""
        response = client.post(
            "/api/v1/brand-health",
            json={
                "brand_name": "TestBrand",
                "region": "中国大陆",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "task_id" in data["data"]
        assert data["data"]["status"] == "processing"
    
    def test_create_task_with_competitors(self):
        """测试带竞品的任务创建"""
        response = client.post(
            "/api/v1/brand-health",
            json={
                "brand_name": "TestBrand",
                "competitors": ["CompetitorA", "CompetitorB"],
                "region": "美国",
            },
        )
        
        assert response.status_code == 200
        assert response.json()["success"] is True
    
    def test_create_task_missing_brand_name(self):
        """测试缺少品牌名称时返回错误"""
        response = client.post(
            "/api/v1/brand-health",
            json={
                "region": "中国大陆",
            },
        )
        
        assert response.status_code == 422  # Validation Error
    
    def test_create_task_missing_region(self):
        """测试缺少地区时返回错误"""
        response = client.post(
            "/api/v1/brand-health",
            json={
                "brand_name": "TestBrand",
            },
        )
        
        assert response.status_code == 422  # Validation Error


class TestTikTokInsightAPI:
    """TikTok 社媒洞察 API 测试"""
    
    def test_create_task_success(self):
        """测试成功创建任务"""
        response = client.post(
            "/api/v1/tiktok-insight",
            json={
                "category": "美妆",
                "selling_points": ["长效控油", "便携式"],
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "task_id" in data["data"]
    
    def test_create_task_missing_category(self):
        """测试缺少品类时返回错误"""
        response = client.post(
            "/api/v1/tiktok-insight",
            json={
                "selling_points": ["卖点1"],
            },
        )
        
        assert response.status_code == 422
    
    def test_create_task_missing_selling_points(self):
        """测试缺少卖点时返回错误"""
        response = client.post(
            "/api/v1/tiktok-insight",
            json={
                "category": "美妆",
            },
        )
        
        assert response.status_code == 422


class TestTasksAPI:
    """任务管理 API 测试"""
    
    def test_get_task_not_found(self):
        """测试查询不存在的任务"""
        response = client.get("/api/v1/tasks/nonexistent_task_id")
        
        assert response.status_code == 404
    
    def test_get_task_after_creation(self):
        """测试创建后查询任务"""
        # 先创建任务
        create_response = client.post(
            "/api/v1/brand-health",
            json={
                "brand_name": "TestBrand",
                "region": "中国大陆",
            },
        )
        task_id = create_response.json()["data"]["task_id"]
        
        # 查询任务状态
        # 注意：由于后台任务是异步执行的，状态可能已变化
        status_response = client.get(f"/api/v1/tasks/{task_id}")
        
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["data"]["task_id"] == task_id

    def test_list_tasks_contains_created_task(self):
        """测试任务列表接口返回最近任务"""
        create_response = client.post(
            "/api/v1/brand-health",
            json={
                "brand_name": "ListBrand",
                "region": "中国大陆",
            },
        )
        task_id = create_response.json()["data"]["task_id"]

        list_response = client.get("/api/v1/tasks?limit=10")
        assert list_response.status_code == 200
        payload = list_response.json()
        assert payload["success"] is True
        items = payload["data"]["items"]
        assert any(item["task_id"] == task_id for item in items)

    def test_download_report_after_completion(self):
        """测试任务完成后下载 HTML 报告（文件流）"""
        create_response = client.post(
            "/api/v1/brand-health",
            json={
                "brand_name": "StreamBrand",
                "region": "中国大陆",
            },
        )
        task_id = create_response.json()["data"]["task_id"]

        report_url = None
        for _ in range(30):
            status = client.get(f"/api/v1/tasks/{task_id}").json()["data"]
            if status["status"] == "completed":
                report_url = status.get("report_url")
                break
            time.sleep(0.05)

        assert report_url is not None

        report_response = client.get(report_url)
        assert report_response.status_code == 200
        assert "text/html" in report_response.headers.get("content-type", "").lower()
        assert "<html" in report_response.text.lower()


# ========== 运行测试 ==========
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
