from agents.extensions.models.litellm_model import LitellmModel
import inspect

print("LitellmModel dir:")
print(dir(LitellmModel))

if hasattr(LitellmModel, 'generate'):
    print("\nLitellmModel.generate signature:")
    print(inspect.signature(LitellmModel.generate))
