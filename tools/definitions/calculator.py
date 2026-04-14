from tools.registry import register_tool
import sympy

@register_tool(
    name="calculator",
    description="Evaluate a mathematical expression. Supports arithmetic, algebra, trig, calculus.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string",
                           "description": "e.g. '2**10', 'sqrt(144)', 'integrate(x**2, x)'"}
        },
        "required": ["expression"]
    },
    permission_tier="read",
    task_types=["calculation", "math", "general"],
)
async def calculator(expression: str) -> dict:
    try:
        result = sympy.sympify(expression)
        return {"result": str(result), "expression": expression}
    except Exception as e:
        return {"error": str(e), "expression": expression}
