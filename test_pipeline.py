#!/usr/bin/env python3
"""Test the pipeline system with a sample task."""
import asyncio
import json
from orchestrator.pipeline import PipelineDefinition, PipelineExecutor

async def main():
    print("=" * 60)
    print("Testing Multi-LLM Pipeline")
    print("=" * 60)

    # Load pipeline
    print("\n1. Loading pipeline configuration...")
    pipeline_def = PipelineDefinition('workflows/current_pipeline.yaml')
    print(f"   ✓ Loaded: {pipeline_def.config.get('name', 'unnamed pipeline')}")
    print(f"   ✓ Stages: {len(pipeline_def.stages)}")

    # Create executor
    executor = PipelineExecutor(pipeline_def)

    # Test task
    task = "Create a simple Python CLI tool that converts Markdown files to HTML"

    print(f"\n2. Task: {task}")
    print(f"\n3. Pipeline stages:")
    for i, stage in enumerate(pipeline_def.stages, 1):
        print(f"   {i}. {stage.name}")
        print(f"      - Model: {stage.model}")
        print(f"      - Type: {stage.model_type.value}")

    print(f"\n4. Running pipeline...")
    print("   (This will execute each stage sequentially)")

    try:
        results = await executor.execute(task)

        print(f"\n5. Results:")
        for stage_id, result in results.items():
            status_icon = "✓" if result.status == "success" else "✗"
            print(f"\n   {status_icon} {stage_id}")
            print(f"      Status: {result.status}")
            print(f"      Execution time: {result.execution_time:.1f}s")
            if result.error:
                print(f"      Error: {result.error}")
            if result.output:
                # Show first 200 chars of output
                preview = result.output[:200].replace('\n', ' ')
                print(f"      Output preview: {preview}...")

        # Save results
        output_data = executor.get_final_results()
        with open("test_results.json", "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\n6. Results saved to test_results.json")

        print("\n" + "=" * 60)
        print("Pipeline test completed!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Pipeline execution failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
