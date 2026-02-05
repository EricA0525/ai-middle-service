"""
Market Insight Agent - HTML Renderer
=====================================
HTML 渲染工具，用于将生成的内容渲染为完整的 HTML 报告。

功能：
1. 加载和解析模板
2. 填充内容到模板
3. 内联 CSS 和 SVG
4. 输出自包含的 HTML 文件

设计思想：
1. 使用 Jinja2 模板引擎
2. 完全自包含的输出（无外部依赖）
3. 保持与参考模板一致的视觉风格

后续开发方向：
1. 支持模板热更新
2. 添加 PDF 导出支持
3. 支持自定义主题
"""

from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape


class HTMLRenderer:
    """
    HTML 渲染器
    
    将生成的内容渲染为完整的 HTML 报告。
    """
    
    def __init__(
        self,
        template_dir: Optional[str] = None,
    ):
        """
        初始化渲染器
        
        Args:
            template_dir: 模板目录路径
        """
        default_dir = Path(__file__).resolve().parent.parent / "templates"
        self.template_dir = Path(template_dir) if template_dir else default_dir

        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            auto_reload=True,
        )
    
    def render(
        self,
        template_name: str,
        context: Dict[str, Any],
    ) -> str:
        """
        渲染模板
        
        Args:
            template_name: 模板文件名
            context: 渲染上下文数据
            
        Returns:
            渲染后的 HTML 字符串
        """
        logger.info(f"Rendering template: {template_name}")

        template = self.env.get_template(template_name)
        return template.render(**context)
    
    def render_string(
        self,
        template_string: str,
        context: Dict[str, Any],
    ) -> str:
        """
        渲染模板字符串
        
        Args:
            template_string: 模板字符串
            context: 渲染上下文数据
            
        Returns:
            渲染后的 HTML 字符串
        """
        template = Template(template_string)
        return template.render(**context)
    
    def load_template(self, template_name: str) -> str:
        """
        加载模板文件
        
        Args:
            template_name: 模板文件名
            
        Returns:
            模板内容字符串
        """
        template_path = self.template_dir / template_name
        
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            logger.warning(f"Template not found: {template_path}")
            return ""
    
    def _render_placeholder(
        self,
        template_name: str,
        context: Dict[str, Any],
    ) -> str:
        """
        生成占位 HTML（开发用）
        """
        return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <title>报告渲染占位</title>
    <style>
        body {{ 
            font-family: system-ui; 
            background: #0b0d12; 
            color: #e9ecf3; 
            padding: 40px; 
        }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .notice {{
            background: rgba(122,162,255,0.2);
            border: 1px solid rgba(122,162,255,0.5);
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}
        pre {{
            background: rgba(0,0,0,0.3);
            padding: 16px;
            border-radius: 8px;
            overflow-x: auto;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📄 HTML 渲染器</h1>
        <div class="notice">
            <p><strong>模板：</strong>{template_name}</p>
            <p>此为开发阶段的占位输出。完成 Jinja2 集成后将渲染真实模板。</p>
        </div>
        <h2>渲染上下文</h2>
        <pre>{self._format_context(context)}</pre>
    </div>
</body>
</html>
"""
    
    def _format_context(self, context: Dict[str, Any]) -> str:
        """格式化上下文数据用于显示"""
        import json
        try:
            return json.dumps(context, indent=2, ensure_ascii=False, default=str)
        except Exception:
            return str(context)


# 创建全局实例
html_renderer = HTMLRenderer()
