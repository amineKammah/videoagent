from agents import RunConfig
import inspect

print("RunConfig dir:")
print(dir(RunConfig))

print("\nRunConfig __init__ signature:")
try:
    print(inspect.signature(RunConfig.__init__))
except:
    print("Could not get signature")
