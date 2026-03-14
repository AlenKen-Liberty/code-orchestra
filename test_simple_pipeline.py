#!/usr/bin/env python3
"""
Simple end-to-end test: Opus → Gemini → Codex → Haiku

不启动 ACP 服务器，直接调用 CLI wrappers。
"""
import asyncio
import json
from agents.claude_code_wrapper import invoke_claude, CLIError as ClaudeError
from agents.codex_wrapper import invoke_codex, CLIError as CodexError
from agents.gemini_wrapper import invoke_gemini, CLIError as GeminiError


async def test_simple_pipeline():
    """
    简化流程测试：
    1. Opus 设计一个小程序
    2. Gemini 确认并输出编码要求
    3. Codex 实现代码
    4. Haiku 进行审查
    """
    print("=" * 70)
    print("简化多模型管道测试: Opus → Gemini → Codex → Haiku")
    print("=" * 70)

    # 初始任务
    task = "创建一个 Python 函数，计算两个数字的和"
    print(f"\n📝 初始任务: {task}\n")

    results = {}

    # ========== Stage 1: Opus 设计 ==========
    print("\n" + "=" * 70)
    print("Stage 1️⃣  - OPUS (设计)")
    print("=" * 70)

    opus_prompt = f"""你是一个系统设计师。请为以下任务设计一个简单的实现方案：

任务: {task}

请提供：
1. 函数签名
2. 核心逻辑描述
3. 边界条件处理
"""

    try:
        print("\n📤 Opus prompt:")
        print(f"  {opus_prompt[:100]}...")
        print("\n⏳ 调用 Claude Opus...")

        design = await invoke_claude(
            opus_prompt,
            model="claude-opus-4-6",
            timeout=30
        )
        results["design"] = design
        print("\n✅ Opus 设计完成:")
        print(design[:300] + "..." if len(design) > 300 else design)

    except ClaudeError as e:
        print(f"\n❌ Opus 失败: {e}")
        return results

    # ========== Stage 2: Gemini 确认 ==========
    print("\n" + "=" * 70)
    print("Stage 2️⃣  - GEMINI (确认和编码需求)")
    print("=" * 70)

    gemini_prompt = f"""你是一个代码审查员。请确认以下设计方案，并生成 Codex 的编码需求：

【设计方案】
{design}

请输出：
1. 对设计的确认（是否清晰、是否可实现）
2. 给 Codex 的具体编码需求（包括函数签名、输入输出、测试用例）

要求编码需求必须：
- 包含完整的 Python 函数签名
- 说明需要处理的边界情况
- 给出示例用法
"""

    try:
        print("\n📤 Gemini prompt:")
        print(f"  {gemini_prompt[:100]}...")
        print("\n⏳ 调用 Gemini 3.1 Pro Preview...")

        gemini_feedback = await invoke_gemini(
            gemini_prompt,
            model="gemini-3.1-pro-preview",
            timeout=30
        )
        results["gemini_feedback"] = gemini_feedback
        print("\n✅ Gemini 确认完成:")
        print(gemini_feedback[:300] + "..." if len(gemini_feedback) > 300 else gemini_feedback)

    except (GeminiError, FileNotFoundError, Exception) as e:
        print(f"\n⚠️  Gemini 调用失败（geminicli 未安装）: {type(e).__name__}")
        print("💡 使用备选方案：用 Opus 代替 Gemini 生成编码需求...\n")

        # 备选方案：用 Opus 代替 Gemini
        backup_prompt = f"""基于以下设计方案，生成 Codex 的编码需求：

【设计】
{design}

请输出编码需求，包括：
1. 确认设计清晰有效
2. 给出完整的 Python 代码框架和函数签名
3. 列出测试用例
"""
        try:
            gemini_feedback = await invoke_claude(
                backup_prompt,
                model="claude-opus-4-6",
                timeout=30
            )
            results["gemini_feedback"] = f"[使用 Opus 替代 Gemini (geminicli 未安装)]\n{gemini_feedback}"
            print("✅ Opus 生成编码需求:")
            print(gemini_feedback[:300] + "..." if len(gemini_feedback) > 300 else gemini_feedback)
        except ClaudeError as e2:
            print(f"❌ 备选方案也失败: {e2}")
            return results

    # ========== Stage 3: Codex 编码 ==========
    print("\n" + "=" * 70)
    print("Stage 3️⃣  - CODEX (实现)")
    print("=" * 70)

    codex_prompt = f"""根据以下编码需求，实现完整的 Python 代码：

【编码需求】
{gemini_feedback}

请输出：
1. 完整的实现代码
2. 测试代码
3. 使用说明

代码必须可以直接运行，包含所有必需的 import 和异常处理。
"""

    try:
        print("\n📤 Codex prompt:")
        print(f"  {codex_prompt[:100]}...")
        print("\n⏳ 调用 Codex...")

        implementation = await invoke_codex(
            codex_prompt,
            timeout=30
        )
        results["implementation"] = implementation
        print("\n✅ Codex 实现完成:")
        print(implementation[:400] + "..." if len(implementation) > 400 else implementation)

    except CodexError as e:
        print(f"\n❌ Codex 失败: {e}")
        return results

    # ========== Stage 4: Haiku 审查 ==========
    print("\n" + "=" * 70)
    print("Stage 4️⃣  - HAIKU (代码审查)")
    print("=" * 70)

    haiku_prompt = f"""你是一个代码审查专家。请审查以下代码实现：

【设计】
{design[:200]}...

【编码需求】
{gemini_feedback[:200]}...

【实现代码】
{implementation}

请进行以下审查：
1. 代码是否实现了设计要求
2. 代码质量（可读性、异常处理等）
3. 是否有 bug 或改进空间
4. 最后给出结论：approved 或 revise

输出格式：
```json
{{
  "verdict": "approved" | "revise",
  "issues": [...],
  "comments": "..."
}}
```
"""

    try:
        print("\n📤 Haiku prompt:")
        print(f"  {haiku_prompt[:100]}...")
        print("\n⏳ 调用 Claude Haiku...")

        review = await invoke_claude(
            haiku_prompt,
            model="claude-haiku-4-5-20251001",
            timeout=30
        )
        results["review"] = review
        print("\n✅ Haiku 审查完成:")
        print(review[:400] + "..." if len(review) > 400 else review)

    except ClaudeError as e:
        print(f"\n❌ Haiku 失败: {e}")
        return results

    # ========== 输出最终结果 ==========
    print("\n" + "=" * 70)
    print("✅ 完整流程执行成功！")
    print("=" * 70)

    return results


async def main():
    try:
        results = await test_simple_pipeline()

        # 保存完整结果
        print("\n" + "=" * 70)
        print("💾 保存结果到 test_simple_results.json")
        print("=" * 70)

        with open("test_simple_results.json", "w") as f:
            # 只保存关键部分（避免过长）
            summary = {
                "design": results.get("design", "")[:500],
                "gemini_feedback": results.get("gemini_feedback", "")[:500],
                "implementation": results.get("implementation", "")[:500],
                "review": results.get("review", "")[:500],
            }
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print("✅ 结果已保存到 test_simple_results.json")

        # 显示完整结果位置
        print("\n完整结果位置：")
        print("  - Stage 1 Opus 设计: results['design']")
        print("  - Stage 2 Gemini 反馈: results['gemini_feedback']")
        print("  - Stage 3 Codex 实现: results['implementation']")
        print("  - Stage 4 Haiku 审查: results['review']")

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
