import agents
try:
    from agents.model_settings import Reasoning
    print("Found Reasoning in agents.model_settings")
except ImportError:
    pass

try:
    from agents import Reasoning
    print("Found Reasoning in agents")
except ImportError:
    pass
