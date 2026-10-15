def calculate(x: float, y: float, operation: str) -> dict:
    operations = {
        "add": lambda: x + y,
        "subtract": lambda: x - y,
        "multiply": lambda: x * y,
        "divide": lambda: x / y if y != 0 else None,
    }
    if operation not in operations:
        return {"error": "Unsupported operation"}
    if operation == "divide" and y == 0:
        return {"error": "Cannot divide by zero"}
    return {"x": x, "y": y, "operation": operation, "result": operations[operation]()}
