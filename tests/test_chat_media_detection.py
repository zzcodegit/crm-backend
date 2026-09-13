import unittest

from types import SimpleNamespace

from routers.chat import _allowed_media_for_upload, _normalize_attachment_media_type


class ChatMediaDetectionTests(unittest.TestCase):
    def test_voice_filename_with_webm_is_audio_even_if_video_mime(self):
        media_type, ok = _allowed_media_for_upload("voice-123.webm", "video/webm")
        self.assertTrue(ok)
        self.assertEqual(media_type, "audio")

    def test_audio_mime_is_audio(self):
        media_type, ok = _allowed_media_for_upload("random.webm", "audio/webm")
        self.assertTrue(ok)
        self.assertEqual(media_type, "audio")

    def test_video_file_stays_video(self):
        media_type, ok = _allowed_media_for_upload("clip.webm", "video/webm")
        self.assertTrue(ok)
        self.assertEqual(media_type, "video")

    def test_image_is_image(self):
        media_type, ok = _allowed_media_for_upload("photo.jpg", "image/jpeg")
        self.assertTrue(ok)
        self.assertEqual(media_type, "image")

    def test_unknown_file_is_rejected(self):
        media_type, ok = _allowed_media_for_upload("archive.zip", "application/zip")
        self.assertFalse(ok)
        self.assertEqual(media_type, "")

    def test_legacy_voice_webm_video_type_is_normalized_to_audio(self):
        att = SimpleNamespace(media_type="video", filename="voice-100.webm", mime_type="video/webm")
        self.assertEqual(_normalize_attachment_media_type(att), "audio")

    def test_audio_mime_video_record_is_normalized_to_audio(self):
        att = SimpleNamespace(media_type="video", filename="upload.webm", mime_type="audio/webm")
        self.assertEqual(_normalize_attachment_media_type(att), "audio")

    def test_regular_video_stays_video_in_normalization(self):
        att = SimpleNamespace(media_type="video", filename="clip.webm", mime_type="video/webm")
        self.assertEqual(_normalize_attachment_media_type(att), "video")

    def test_is_voice_note_flag_forces_webm_to_audio(self):
        media_type, ok = _allowed_media_for_upload("random-uuid.webm", "video/webm", is_voice_note=True)
        self.assertTrue(ok)
        self.assertEqual(media_type, "audio")


if __name__ == "__main__":
    unittest.main()
