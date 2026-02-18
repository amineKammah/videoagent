try:
    from agents import ModelSettings
    import inspect
    print("ModelSettings dir:")
    print(dir(ModelSettings))
    print("\nModelSettings __init__ signature:")
    print(inspect.signature(ModelSettings.__init__))
except ImportError:
    print("Could not import ModelSettings from agents")

try:
    from agents.model_settings import Reasoning
    print("\nReasoning dir:")
    print(dir(Reasoning))
except ImportError:
    print("Could not import Reasoning from agents.model_settings")
