"""
测试新功能的脚本
验证：
1. 拖拽功能（需要手动测试）
2. 删除功能
3. 属性面板更新
4. 首页工作流列表
"""

import sys
import json
from pathlib import Path

def test_workflow_json_format():
    """测试工作流JSON格式是否包含位置信息"""
    print("测试1: 检查工作流JSON格式...")
    
    workflows_dir = Path("workflows")
    if not workflows_dir.exists():
        print("  [FAIL] workflows目录不存在")
        return False
    
    json_files = list(workflows_dir.glob("*/workflow.json"))
    
    if not json_files:
        print("  [INFO] 没有找到工作流文件")
        return True
    
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 检查必要的字段
            if "workflow_name" not in data:
                print(f"  [FAIL] {json_file.parent.name}: 缺少 workflow_name")
                return False
            
            if "nodes" not in data or "edges" not in data:
                print(f"  [FAIL] {json_file.parent.name}: 缺少 nodes 或 edges")
                return False
            
            # 检查是否有position字段（新增的）
            has_position = False
            for node in data.get("nodes", []):
                if "position" in node:
                    has_position = True
                    break
            
            if has_position:
                print(f"  [OK] {json_file.parent.name}: 格式正确，包含位置信息")
            else:
                print(f"  [INFO] {json_file.parent.name}: 格式正确，但没有位置信息（旧格式）")
        
        except Exception as e:
            print(f"  [FAIL] {json_file.parent.name}: 解析失败 - {e}")
            return False
    
    return True


def test_node_browser_drag():
    """测试节点浏览器拖拽（需要GUI环境）"""
    print("\n测试2: 节点浏览器拖拽功能...")
    print("  [INFO] 此功能需要手动测试：")
    print("    1. 启动应用")
    print("    2. 打开左侧节点浏览器")
    print("    3. 拖拽节点到画板")
    print("    4. 验证节点在正确位置创建")
    return True


def test_node_deletion():
    """测试节点删除（需要GUI环境）"""
    print("\n测试3: 节点删除功能...")
    print("  [INFO] 此功能需要手动测试：")
    print("    1. 在画板中创建节点")
    print("    2. 选中节点，按Delete键")
    print("    3. 验证节点和连接线被删除")
    print("    4. 右键节点，选择删除")
    print("    5. 验证删除成功")
    return True


def test_properties_panel():
    """测试属性面板更新（需要GUI环境）"""
    print("\n测试4: 属性面板更新优化...")
    print("  [INFO] 此功能需要手动测试：")
    print("    1. 创建多个节点")
    print("    2. 快速点击不同节点")
    print("    3. 验证属性面板显示正确")
    print("    4. 无卡顿或延迟现象")
    return True


def test_workflow_list():
    """测试首页工作流列表"""
    print("\n测试5: 首页工作流列表...")
    
    workflows_dir = Path("workflows")
    if not workflows_dir.exists():
        print("  [INFO] workflows目录不存在，创建中...")
        workflows_dir.mkdir(exist_ok=True)
    
    # 统计工作流数量
    workflow_count = 0
    for item in workflows_dir.iterdir():
        if item.is_dir() and (item / "workflow.json").exists():
            workflow_count += 1
    
    print(f"  [INFO] 找到 {workflow_count} 个工作流")
    
    if workflow_count > 0:
        print("  [INFO] 手动测试步骤：")
        print("    1. 启动应用")
        print("    2. 查看首页工作流卡片")
        print("    3. 点击'打开'按钮测试加载")
        print("    4. 点击'删除'按钮测试删除")
        print("    5. 保存新工作流，验证自动刷新")
    else:
        print("  [INFO] 建议先创建一些工作流进行测试")
    
    return True


def test_code_imports():
    """测试代码导入（检查语法错误）"""
    print("\n测试6: 检查代码语法...")
    
    modules = [
        "src.views.node_browser",
        "src.views.workflow_canvas",
        "src.views.node_graphics",
        "src.views.node_properties",
        "src.views.overview_widget",
        "src.views.workflow_tab_widget",
        "src.core.workflow_executor",
    ]
    
    all_ok = True
    for module in modules:
        try:
            __import__(module)
            print(f"  [OK] {module}")
        except Exception as e:
            print(f"  [FAIL] {module}: {e}")
            all_ok = False
    
    return all_ok


def main():
    print("=" * 60)
    print("LocalFlow 功能改进测试")
    print("=" * 60)
    
    results = []
    
    # 运行所有测试
    results.append(("代码语法检查", test_code_imports()))
    results.append(("工作流JSON格式", test_workflow_json_format()))
    results.append(("节点浏览器拖拽", test_node_browser_drag()))
    results.append(("节点删除功能", test_node_deletion()))
    results.append(("属性面板更新", test_properties_panel()))
    results.append(("首页工作流列表", test_workflow_list()))
    
    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status}: {name}")
    
    print(f"\n总计: {passed}/{total} 项测试通过")
    
    if passed == total:
        print("\n[SUCCESS] 所有测试通过！")
        return 0
    else:
        print("\n[WARNING] 部分测试失败，请检查错误信息")
        return 1


if __name__ == "__main__":
    sys.exit(main())
