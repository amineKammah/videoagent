from agents.extensions.models.litellm_model import LitellmModel
import inspect

try:
    print("LitellmModel file:")
    print(inspect.getfile(LitellmModel))
except Exception as e:
    print(f"Error getting file: {e}")
