
import inspect
from agents import Agent, Usage

print("Inspecting Usage class:")
print(dir(Usage))

u = Usage(input_tokens=10, output_tokens=20)
print(f"Usage object: {u}")
if hasattr(u, "requests"):
    print("Usage has requests field")
else:
    print("Usage does NOT have requests field")
    
# Check if we can find where it is converted to dict/json
try:
    import json
    print(f"JSON dump: {json.dumps(u.__dict__ if hasattr(u, '__dict__') else u, default=str)}")
except Exception as e:
    print(f"JSON dump failed: {e}")
