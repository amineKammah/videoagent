import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add backend source to path
sys.path.append(str(Path(__file__).parent.parent / "backend/src"))

from videoagent.agent.schemas import StoryboardSceneUpdatePayload, StoryboardSceneUpdate, StoryboardUpdatePayload
from videoagent.story import _StoryboardScene, _MatchedScene, VoiceOver
from videoagent.agent.tools import update_storyboard, update_storyboard_scene

class TestStoryboardUpdates(unittest.TestCase):
    def setUp(self):
        # Mock dependencies
        self.mock_storyboard_store = MagicMock()
        self.mock_event_store = MagicMock()
        
        # Patch them in tools.py
        patcher1 = patch('videoagent.agent.tools.storyboard_store', self.mock_storyboard_store)
        patcher2 = patch('videoagent.agent.tools.event_store', self.mock_event_store)
        patcher3 = patch('videoagent.agent.tools.session_id', 'test_session')
        
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(patcher3.stop)
        
        patcher1.start()
        patcher2.start()
        patcher3.start()

    def test_update_storyboard_preserves_fields(self):
        # Setup existing scene with specialized data
        existing_vo = VoiceOver(script="test", duration=5.0, audio_id="123")
        existing_match = _MatchedScene(
            source_video_id="vid1", 
            start_time=0, 
            end_time=5, 
            description="d", 
            keep_original_audio=False
        )
        existing_scene = _StoryboardScene(
            scene_id="s1",
            title="Old Title",
            purpose="Old Purpose",
            script="Old Script",
            voice_over=existing_vo,
            matched_scene=existing_match
        )
        self.mock_storyboard_store.load.return_value = [existing_scene]

        # Update payload (without specialized fields)
        update_scene = StoryboardSceneUpdate(
            scene_id="s1",
            title="New Title",
            purpose="New Purpose",
            script="New Script",
            use_voice_over=True
        )
        payload = StoryboardUpdatePayload(scenes=[update_scene])

        # Execute
        result = update_storyboard(payload)

        # Verify
        self.mock_storyboard_store.save.assert_called_once()
        saved_scenes = self.mock_storyboard_store.save.call_args[0][1]
        self.assertEqual(len(saved_scenes), 1)
        saved_scene = saved_scenes[0]
        
        self.assertEqual(saved_scene.title, "New Title")
        self.assertEqual(saved_scene.voice_over, existing_vo)
        self.assertEqual(saved_scene.matched_scene, existing_match)

    def test_update_storyboard_scene_preserves_fields(self):
        # Setup existing scene
        existing_vo = VoiceOver(script="test", duration=5.0, audio_id="123")
        existing_scene = _StoryboardScene(
            scene_id="s1",
            title="Old",
            purpose="Old",
            script="Old",
            voice_over=existing_vo
        )
        self.mock_storyboard_store.load.return_value = [existing_scene]

        # Update payload
        update_scene = StoryboardSceneUpdate(
            scene_id="s1",
            title="New Title",
            purpose="New Purpose",
            script="New Script",
            use_voice_over=True
        )
        payload = StoryboardSceneUpdatePayload(scene=update_scene)

        # Execute
        result = update_storyboard_scene(payload)

        # Verify
        self.mock_storyboard_store.save.assert_called_once()
        saved_scenes = self.mock_storyboard_store.save.call_args[0][1]
        self.assertEqual(len(saved_scenes), 1)
        self.assertEqual(saved_scenes[0].title, "New Title")
        self.assertEqual(saved_scenes[0].voice_over, existing_vo)

    def test_new_scene_has_defaults(self):
         # Setup empty
        self.mock_storyboard_store.load.return_value = []

        # Update payload with new scene
        update_scene = StoryboardSceneUpdate(
            scene_id="new1",
            title="New",
            purpose="New",
            script="New",
            use_voice_over=True
        )
        payload = StoryboardUpdatePayload(scenes=[update_scene])

        # Execute
        update_storyboard(payload)

        # Verify
        saved_scenes = self.mock_storyboard_store.save.call_args[0][1]
        self.assertIsNone(saved_scenes[0].voice_over)
        self.assertIsNone(saved_scenes[0].matched_scene)

if __name__ == '__main__':
    unittest.main()
