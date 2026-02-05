"""
Market Insight Agent - SVG Generator
=====================================
SVG 图表生成器，用于生成报告中的各类图表。

支持图表类型：
1. 折线图 (Line Chart)
2. 柱状图 (Bar Chart)
3. 雷达图 (Radar Chart)
4. 环图 (Donut Chart)
5. 散点图 (Scatter Chart)

设计思想：
1. 纯 SVG 输出，无需 JS
2. 保持与参考模板一致的视觉风格
3. 支持自适应尺寸

后续开发方向：
1. 完善各图表类型的实现
2. 添加动画效果（CSS 动画）
3. 支持更多自定义配置
"""

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


class SVGGenerator:
    """
    SVG 图表生成器
    
    根据数据生成各类 SVG 图表。
    """
    
    # 默认颜色方案（与参考模板一致）
    DEFAULT_COLORS = {
        "primary": "#7aa2ff",
        "secondary": "#ffd36b",
        "good": "#5ee38f",
        "warn": "#ffd36b",
        "bad": "#ff6b6b",
        "text": "#e9ecf3",
        "muted": "#aab3c5",
        "grid": "rgba(255,255,255,0.10)",
    }
    
    def __init__(self):
        self.colors = self.DEFAULT_COLORS.copy()
        self._padding = {"l": 44, "r": 16, "t": 26, "b": 34}
    
    def generate_line_chart(
        self,
        data: List[Dict[str, Any]],
        width: int = 760,
        height: int = 260,
        x_key: str = "x",
        y_key: str = "y",
        title: Optional[str] = None,
    ) -> str:
        """
        生成折线图
        
        Args:
            data: 数据点列表，如 [{"x": "Week 1", "y": 58}, ...]
            width: 图表宽度
            height: 图表高度
            x_key: X 轴数据键名
            y_key: Y 轴数据键名
            title: 图表标题
            
        Returns:
            SVG 代码字符串
        """
        logger.debug(f"Generating line chart with {len(data)} data points")

        if not data:
            return self._get_placeholder_svg(width, height, "折线图 (无数据)", data)

        xs = [str(p.get(x_key, "")) for p in data]
        ys = [float(p.get(y_key, 0) or 0) for p in data]

        y_min, y_max = min(ys), max(ys)
        if y_min == y_max:
            y_min -= 1
            y_max += 1

        pad = self._padding
        plot_w = width - pad["l"] - pad["r"]
        plot_h = height - pad["t"] - pad["b"]

        def x_at(i: int) -> float:
            if len(xs) == 1:
                return pad["l"] + plot_w / 2
            return pad["l"] + (i / (len(xs) - 1)) * plot_w

        def y_at(v: float) -> float:
            return pad["t"] + (1 - (v - y_min) / (y_max - y_min)) * plot_h

        points = [(x_at(i), y_at(v)) for i, v in enumerate(ys)]
        poly = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)

        grid_lines = []
        y_ticks = 4
        for i in range(y_ticks + 1):
            y = pad["t"] + (i / y_ticks) * plot_h
            grid_lines.append(
                f'<line x1="{pad["l"]}" y1="{y:.2f}" x2="{width-pad["r"]}" y2="{y:.2f}" '
                f'stroke="{self.colors["grid"]}" stroke-width="1"/>'
            )

        x_labels = []
        for i, lab in enumerate(xs):
            if len(xs) > 8 and i % 2 == 1:
                continue
            x = x_at(i)
            x_labels.append(
                f'<text x="{x:.2f}" y="{height-12}" text-anchor="middle" fill="{self.colors["muted"]}" font-size="11">{self._escape(lab)}</text>'
            )

        y_labels = []
        for i in range(y_ticks + 1):
            v = y_max - (i / y_ticks) * (y_max - y_min)
            y = pad["t"] + (i / y_ticks) * plot_h
            y_labels.append(
                f'<text x="{pad["l"]-8}" y="{y+4:.2f}" text-anchor="end" fill="{self.colors["muted"]}" font-size="11">{v:.0f}</text>'
            )

        circles = []
        for x, y in points:
            circles.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.2" fill="{self.colors["primary"]}" stroke="#0b0d12" stroke-width="1.5"/>'
            )

        title_html = (
            f'<text x="{pad["l"]}" y="16" text-anchor="start" fill="{self.colors["text"]}" font-size="13" font-weight="600">{self._escape(title or "")}</text>'
            if title
            else ""
        )

        # Area fill
        area = poly + f" {points[-1][0]:.2f},{pad['t']+plot_h:.2f} {points[0][0]:.2f},{pad['t']+plot_h:.2f}"

        return f"""
<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">
  <defs>
    <linearGradient id="lineFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{self.colors["primary"]}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="{self.colors["primary"]}" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="{width}" height="{height}" rx="12" ry="12"
        fill="rgba(255,255,255,.02)" stroke="rgba(255,255,255,.08)"/>
  {title_html}
  {"".join(grid_lines)}
  <path d="M {area.replace(' ', ' L ')}" fill="url(#lineFill)" stroke="none"/>
  <polyline points="{poly}" fill="none" stroke="{self.colors["primary"]}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>
  {"".join(circles)}
  {"".join(y_labels)}
  {"".join(x_labels)}
</svg>
"""
    
    def generate_bar_chart(
        self,
        data: List[Dict[str, Any]],
        width: int = 520,
        height: int = 220,
        label_key: str = "label",
        value_key: str = "value",
        horizontal: bool = False,
    ) -> str:
        """
        生成柱状图
        
        Args:
            data: 数据列表，如 [{"label": "18-24", "value": 30}, ...]
            width: 图表宽度
            height: 图表高度
            label_key: 标签键名
            value_key: 数值键名
            horizontal: 是否水平显示
            
        Returns:
            SVG 代码字符串
        """
        logger.debug(f"Generating bar chart with {len(data)} bars")
        if not data:
            return self._get_placeholder_svg(width, height, "柱状图 (无数据)", data)

        labels = [str(d.get(label_key, "")) for d in data]
        values = [float(d.get(value_key, 0) or 0) for d in data]
        v_max = max(values) if values else 1.0
        if v_max <= 0:
            v_max = 1.0

        pad = {"l": 44, "r": 16, "t": 18, "b": 34}
        plot_w = width - pad["l"] - pad["r"]
        plot_h = height - pad["t"] - pad["b"]

        bars = []
        if not horizontal:
            bar_w = plot_w / max(len(values), 1)
            for i, v in enumerate(values):
                x = pad["l"] + i * bar_w + bar_w * 0.18
                w = bar_w * 0.64
                h = (v / v_max) * plot_h
                y = pad["t"] + (plot_h - h)
                bars.append(
                    f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="8" ry="8" fill="{self.colors["primary"]}" fill-opacity="0.85"/>'
                )
        else:
            row_h = plot_h / max(len(values), 1)
            for i, v in enumerate(values):
                y = pad["t"] + i * row_h + row_h * 0.18
                h = row_h * 0.64
                w = (v / v_max) * plot_w
                x = pad["l"]
                bars.append(
                    f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="8" ry="8" fill="{self.colors["primary"]}" fill-opacity="0.85"/>'
                )

        grid = []
        for i in range(5):
            x = pad["l"] + (i / 4) * plot_w
            grid.append(
                f'<line x1="{x:.2f}" y1="{pad["t"]}" x2="{x:.2f}" y2="{pad["t"]+plot_h:.2f}" stroke="{self.colors["grid"]}" stroke-width="1"/>'
            )

        x_labels = []
        if not horizontal:
            for i, lab in enumerate(labels):
                x = pad["l"] + (i + 0.5) * (plot_w / max(len(labels), 1))
                x_labels.append(
                    f'<text x="{x:.2f}" y="{height-12}" text-anchor="middle" fill="{self.colors["muted"]}" font-size="11">{self._escape(lab)}</text>'
                )
        else:
            for i, lab in enumerate(labels):
                y = pad["t"] + (i + 0.5) * (plot_h / max(len(labels), 1)) + 4
                x_labels.append(
                    f'<text x="{pad["l"]-8}" y="{y:.2f}" text-anchor="end" fill="{self.colors["muted"]}" font-size="11">{self._escape(lab)}</text>'
                )

        return f"""
<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">
  <rect x="0" y="0" width="{width}" height="{height}" rx="12" ry="12"
        fill="rgba(255,255,255,.02)" stroke="rgba(255,255,255,.08)"/>
  {"".join(grid)}
  {"".join(bars)}
  {"".join(x_labels)}
</svg>
"""
    
    def generate_radar_chart(
        self,
        data: List[Dict[str, Any]],
        dimensions: List[str],
        width: int = 760,
        height: int = 260,
    ) -> str:
        """
        生成雷达图
        
        Args:
            data: 数据系列列表，如 [{"name": "品牌A", "values": [80, 70, 60, 90, 85]}, ...]
            dimensions: 维度标签列表，如 ["声量", "内容活跃", "渠道覆盖", ...]
            width: 图表宽度
            height: 图表高度
            
        Returns:
            SVG 代码字符串
        """
        logger.debug(f"Generating radar chart with {len(dimensions)} dimensions")
        if not dimensions:
            return self._get_placeholder_svg(width, height, "雷达图 (无维度)", data)

        cx, cy = width / 2, height / 2 + 6
        r = min(width, height) * 0.34
        n = len(dimensions)

        def pt(i: int, rr: float) -> Tuple[float, float]:
            import math

            ang = -math.pi / 2 + (2 * math.pi * i / n)
            return cx + rr * math.cos(ang), cy + rr * math.sin(ang)

        grid = []
        rings = 4
        for k in range(1, rings + 1):
            rr = r * (k / rings)
            poly = " ".join(f"{pt(i, rr)[0]:.2f},{pt(i, rr)[1]:.2f}" for i in range(n))
            grid.append(
                f'<polygon points="{poly}" fill="none" stroke="{self.colors["grid"]}" stroke-width="1"/>'
            )

        axes = []
        labels = []
        for i, dim in enumerate(dimensions):
            x, y = pt(i, r)
            axes.append(
                f'<line x1="{cx:.2f}" y1="{cy:.2f}" x2="{x:.2f}" y2="{y:.2f}" stroke="{self.colors["grid"]}" stroke-width="1"/>'
            )
            lx, ly = pt(i, r + 18)
            anchor = "middle"
            if lx < cx - 10:
                anchor = "end"
            elif lx > cx + 10:
                anchor = "start"
            labels.append(
                f'<text x="{lx:.2f}" y="{ly:.2f}" text-anchor="{anchor}" fill="{self.colors["muted"]}" font-size="11">{self._escape(dim)}</text>'
            )

        series = []
        for idx, s in enumerate(data or []):
            vals = s.get("values") or []
            if len(vals) != n:
                continue
            pts = []
            for i, v in enumerate(vals):
                vv = max(0.0, min(100.0, float(v)))
                pts.append(pt(i, r * (vv / 100.0)))
            poly = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
            color = self.colors["primary"] if idx == 0 else self.colors["secondary"]
            series.append(
                f'<polygon points="{poly}" fill="{color}" fill-opacity="0.16" stroke="{color}" stroke-width="2"/>'
            )

        return f"""
<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">
  <rect x="0" y="0" width="{width}" height="{height}" rx="12" ry="12"
        fill="rgba(255,255,255,.02)" stroke="rgba(255,255,255,.08)"/>
  {"".join(grid)}
  {"".join(axes)}
  {"".join(series)}
  {"".join(labels)}
</svg>
"""
    
    def generate_donut_chart(
        self,
        data: List[Dict[str, Any]],
        width: int = 240,
        height: int = 220,
        inner_radius: int = 50,
        outer_radius: int = 70,
    ) -> str:
        """
        生成环图
        
        Args:
            data: 数据列表，如 [{"label": "一线城市", "value": 40}, ...]
            width: 图表宽度
            height: 图表高度
            inner_radius: 内圆半径
            outer_radius: 外圆半径
            
        Returns:
            SVG 代码字符串
        """
        logger.debug(f"Generating donut chart with {len(data)} segments")
        if not data:
            return self._get_placeholder_svg(width, height, "环图 (无数据)", data)

        import math

        cx, cy = width / 2, height / 2 + 4
        total = sum(max(0.0, float(d.get("value", 0) or 0)) for d in data) or 1.0
        r = outer_radius
        ir = inner_radius

        def arc(start: float, end: float) -> str:
            x1 = cx + r * math.cos(start)
            y1 = cy + r * math.sin(start)
            x2 = cx + r * math.cos(end)
            y2 = cy + r * math.sin(end)
            large = 1 if end - start > math.pi else 0
            xi2 = cx + ir * math.cos(end)
            yi2 = cy + ir * math.sin(end)
            xi1 = cx + ir * math.cos(start)
            yi1 = cy + ir * math.sin(start)
            return (
                f"M {x1:.2f} {y1:.2f} "
                f"A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f} "
                f"L {xi2:.2f} {yi2:.2f} "
                f"A {ir} {ir} 0 {large} 0 {xi1:.2f} {yi1:.2f} Z"
            )

        palette = [self.colors["primary"], self.colors["good"], self.colors["secondary"], self.colors["warn"], self.colors["bad"]]
        start = -math.pi / 2
        segs = []
        legend = []
        for i, d in enumerate(data):
            v = max(0.0, float(d.get("value", 0) or 0))
            frac = v / total
            end = start + frac * 2 * math.pi
            color = palette[i % len(palette)]
            segs.append(f'<path d="{arc(start, end)}" fill="{color}" fill-opacity="0.85"/>')
            label = self._escape(str(d.get("label", f"S{i+1}")))
            legend.append(
                f'<g transform="translate(18 {18 + i*16})"><rect x="0" y="3" width="10" height="10" rx="2" fill="{color}" />'
                f'<text x="16" y="12" fill="{self.colors["muted"]}" font-size="11">{label}</text></g>'
            )
            start = end

        return f"""
<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">
  <rect x="0" y="0" width="{width}"
        height="{height}" rx="12" ry="12"
        fill="rgba(255,255,255,.02)" stroke="rgba(255,255,255,.08)"/>
  {"".join(segs)}
  {"".join(legend)}
</svg>
"""
    
    def generate_scatter_chart(
        self,
        data: List[Dict[str, Any]],
        width: int = 360,
        height: int = 220,
        x_key: str = "x",
        y_key: str = "y",
        label_key: str = "label",
    ) -> str:
        """
        生成散点图（痛点矩阵）
        
        Args:
            data: 数据点列表，如 [{"x": 80, "y": 70, "label": "易清洗"}, ...]
            width: 图表宽度
            height: 图表高度
            x_key: X 轴数据键名
            y_key: Y 轴数据键名
            label_key: 标签键名
            
        Returns:
            SVG 代码字符串
        """
        logger.debug(f"Generating scatter chart with {len(data)} points")
        if not data:
            return self._get_placeholder_svg(width, height, "散点图 (无数据)", data)

        pad = {"l": 40, "r": 16, "t": 18, "b": 28}
        plot_w = width - pad["l"] - pad["r"]
        plot_h = height - pad["t"] - pad["b"]

        def x_at(v: float) -> float:
            vv = max(0.0, min(100.0, v))
            return pad["l"] + (vv / 100.0) * plot_w

        def y_at(v: float) -> float:
            vv = max(0.0, min(100.0, v))
            return pad["t"] + (1 - vv / 100.0) * plot_h

        grid = []
        for i in range(5):
            x = pad["l"] + (i / 4) * plot_w
            y = pad["t"] + (i / 4) * plot_h
            grid.append(
                f'<line x1="{x:.2f}" y1="{pad["t"]}" x2="{x:.2f}" y2="{pad["t"]+plot_h:.2f}" stroke="{self.colors["grid"]}" stroke-width="1"/>'
            )
            grid.append(
                f'<line x1="{pad["l"]}" y1="{y:.2f}" x2="{pad["l"]+plot_w:.2f}" y2="{y:.2f}" stroke="{self.colors["grid"]}" stroke-width="1"/>'
            )

        points = []
        labels = []
        for d in data:
            x = x_at(float(d.get(x_key, 0) or 0))
            y = y_at(float(d.get(y_key, 0) or 0))
            label = self._escape(str(d.get(label_key, "")))
            points.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.2" fill="{self.colors["secondary"]}" fill-opacity="0.9" stroke="#0b0d12" stroke-width="1.5"/>'
            )
            labels.append(
                f'<text x="{x+7:.2f}" y="{y-7:.2f}" fill="{self.colors["muted"]}" font-size="11">{label}</text>'
            )

        axis_labels = (
            f'<text x="{pad["l"]+plot_w/2:.2f}" y="{height-8}" text-anchor="middle" fill="{self.colors["muted"]}" font-size="11">影响度 →</text>'
            f'<text x="12" y="{pad["t"]+plot_h/2:.2f}" text-anchor="middle" fill="{self.colors["muted"]}" font-size="11" transform="rotate(-90 12 {pad["t"]+plot_h/2:.2f})">可满足性 →</text>'
        )

        return f"""
<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">
  <rect x="0" y="0" width="{width}" height="{height}" rx="12" ry="12"
        fill="rgba(255,255,255,.02)" stroke="rgba(255,255,255,.08)"/>
  {"".join(grid)}
  {"".join(points)}
  {"".join(labels)}
  {axis_labels}
</svg>
"""
    
    def _get_placeholder_svg(
        self,
        width: int,
        height: int,
        title: str,
        data: Any = None,
    ) -> str:
        """
        生成占位 SVG（开发用）
        """
        data_info = f"数据点: {len(data) if data else 0}" if data else ""
        
        return f"""
<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">
    <rect x="0" y="0" width="{width}" height="{height}" 
          fill="rgba(255,255,255,.02)" stroke="rgba(255,255,255,.08)"/>
    <text x="{width//2}" y="{height//2 - 10}" 
          text-anchor="middle" fill="{self.colors['muted']}" font-size="14">
        {title}
    </text>
    <text x="{width//2}" y="{height//2 + 15}" 
          text-anchor="middle" fill="{self.colors['muted']}" font-size="12">
        {data_info}
    </text>
</svg>
"""
    
    # ========== 工具方法 ==========
    
    def _calculate_scale(
        self,
        values: List[float],
        target_range: Tuple[float, float],
    ) -> Tuple[float, float]:
        """
        计算数据缩放比例
        
        Args:
            values: 原始数值列表
            target_range: 目标范围 (min, max)
            
        Returns:
            (scale, offset) 用于转换: y = value * scale + offset
        """
        if not values:
            return 1.0, 0.0
        
        v_min, v_max = min(values), max(values)
        t_min, t_max = target_range
        
        if v_max == v_min:
            return 1.0, t_min
        
        scale = (t_max - t_min) / (v_max - v_min)
        offset = t_min - v_min * scale
        
        return scale, offset

    def _escape(self, text: str) -> str:
        import html as _html

        return _html.escape(text or "")
    
    def _polar_to_cartesian(
        self,
        cx: float,
        cy: float,
        radius: float,
        angle_degrees: float,
    ) -> Tuple[float, float]:
        """
        极坐标转笛卡尔坐标
        
        Args:
            cx, cy: 圆心坐标
            radius: 半径
            angle_degrees: 角度（度）
            
        Returns:
            (x, y) 坐标
        """
        import math
        angle_radians = math.radians(angle_degrees - 90)  # 从顶部开始
        x = cx + radius * math.cos(angle_radians)
        y = cy + radius * math.sin(angle_radians)
        return x, y


# 创建全局实例
svg_generator = SVGGenerator()
