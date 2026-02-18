try:
    from videoagent.agent.service import VideoAgentService
    print("VideoAgentService imported successfully")
except Exception as e:
    print(f"Error importing VideoAgentService: {e}")
    import traceback
    traceback.print_exc()
